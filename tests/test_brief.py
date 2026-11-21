import base64
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from reposcout.brief import ProjectExplainer
from reposcout.core import Store, now_cn


class ProjectBriefTest(unittest.TestCase):
    def test_visible_repositories_are_prepared_without_opening_a_brief(self):
        from reposcout.server import prepare_visible_briefs

        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root))
            day = now_cn().date().isoformat()
            store.ignore_repo("example/ignored", True)
            with store.connect() as db:
                db.executemany("INSERT INTO trending(day,position,slug,description) VALUES (?,?,?,?)", [
                    (day, 1, "example/visible", "Visible project"),
                    (day, 2, "example/sent", "Sent project"),
                    (day, 3, "example/ignored", "Ignored project"),
                ])
                db.execute("INSERT INTO recommendation_items(day,slug) VALUES (?,?)", (day, "example/visible"))
                db.execute("INSERT INTO recommendation_items(day,slug) VALUES (?,?)", (day, "example/ignored"))
                db.execute("INSERT INTO deliveries(day,status,message_id,subject,body) VALUES (?,?,?,?,?)",
                           (day, "sent", "test-message", "test", "test"))
                db.execute("INSERT INTO delivery_items(day,kind,item_id) VALUES (?,'repo',?)",
                           (day, "example/sent"))
            store.request_project_brief("nightly-labs/openbot")
            store.finish_project_brief("nightly-labs/openbot", {
                "purpose": "已缓存", "usage": "用法", "requirements": "无", "caveats": "无", "sources": []
            })
            store.request_project_brief("earendil-works/pi")
            store.interrupt_project_briefs()

            generated = []
            def finish(slug):
                generated.append(slug)
                store.finish_project_brief(slug, {
                    "purpose": "提前生成", "usage": "用法", "requirements": "无", "caveats": "无", "sources": []
                })

            prepare_visible_briefs(store, finish)
            self.assertEqual(store.project_brief("example/visible")["state"], "completed")
            self.assertEqual(store.project_brief("example/sent")["state"], "completed")
            self.assertIn("earendil-works/pi", generated)
            self.assertNotIn("nightly-labs/openbot", generated)
            self.assertIsNone(store.project_brief("example/ignored"))
            prepared_count = len(generated)
            prepare_visible_briefs(store, finish)
            self.assertEqual(len(generated), prepared_count)

    def test_server_prefetches_a_visible_brief_without_a_request(self):
        from reposcout.server import serve

        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root))
            day = now_cn().date().isoformat()
            with store.connect() as db:
                db.execute("INSERT INTO trending(day,position,slug,description) VALUES (?,?,?,?)",
                           (day, 1, "example/visible", "Visible project"))
                db.execute("INSERT INTO recommendation_items(day,slug) VALUES (?,?)", (day, "example/visible"))

            def wait_for_brief():
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if (store.project_brief("example/visible") or {}).get("state") == "completed":
                        return
                    time.sleep(0.01)
                self.fail("visible brief was not prepared on server startup")

            result = {"purpose": "提前生成", "usage": "用法", "requirements": "无", "caveats": "无", "sources": []}
            with patch("reposcout.server.ProjectExplainer", return_value=lambda slug: result), \
                 patch("reposcout.server.ThreadingHTTPServer") as server:
                server.return_value.serve_forever.side_effect = wait_for_brief
                serve(store, port=8765)
            self.assertEqual(store.project_brief("example/visible")["purpose"], "提前生成")

    def test_brief_claim_is_cached_and_interrupted_jobs_can_retry(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root))
            first, started = store.request_project_brief("https://github.com/example/tool")
            self.assertTrue(started)
            self.assertEqual(first["state"], "running")
            _, started = store.request_project_brief("example/tool")
            self.assertFalse(started)

            result = {"purpose": "整理项目资料", "usage": "输入 GitHub 链接", "requirements": "gh",
                      "caveats": "仅支持 GitHub", "sources": [{"title": "README", "url": "https://github.com/example/tool"}]}
            store.finish_project_brief("example/tool", result)
            cached, started = store.request_project_brief("example/tool")
            self.assertFalse(started)
            self.assertEqual(cached["purpose"], result["purpose"])
            self.assertEqual(cached["sources"], result["sources"])

            _, started = store.request_project_brief("example/tool", refresh=True)
            self.assertTrue(started)
            store.interrupt_project_briefs()
            self.assertEqual(store.project_brief("example/tool")["state"], "failed")
            _, started = store.request_project_brief("example/tool")
            self.assertTrue(started)

    def test_explainer_reads_readme_and_setup_file_before_summarizing(self):
        slug = "mvanhorn/last30days-skill"
        readme = {"encoding": "base64", "content": base64.b64encode(b"Searches recent discussions").decode(),
                  "html_url": f"https://github.com/{slug}/blob/main/README.md"}
        config = {"encoding": "base64", "content": base64.b64encode(b"X needs local setup").decode(),
                  "html_url": f"https://github.com/{slug}/blob/main/CONFIGURATION.md"}
        commands = []

        def fake_run(command, **kwargs):
            commands.append(command)
            if command[:2] == ["gh", "api"]:
                endpoint = command[2]
                payload = ({f"repos/{slug}": {"description": "Recent research", "private": False},
                            f"repos/{slug}/readme": readme,
                            f"repos/{slug}/contents": [{"name": "CONFIGURATION.md", "type": "file"}],
                            f"repos/{slug}/contents/CONFIGURATION.md": config})[endpoint]
                return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
            self.assertEqual(command[command.index("-s") + 1], "read-only")
            self.assertEqual(command[-1], "-")
            self.assertIn("Searches recent discussions", kwargs["input"])
            self.assertIn("X needs local setup", kwargs["input"])
            Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps({
                "purpose": "了解近期讨论", "usage": "输入研究主题", "requirements": "X 需要本地配置", "caveats": "仅覆盖近期"
            }), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("reposcout.brief.subprocess.run", side_effect=fake_run):
            result = ProjectExplainer()(slug)
        self.assertEqual(result["purpose"], "了解近期讨论")
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(len(commands), 5)

    def test_private_repository_is_rejected_before_reading_source(self):
        with patch("reposcout.brief.subprocess.run", return_value=subprocess.CompletedProcess(
            ["gh", "api"], 0, json.dumps({"private": True}), "")) as run:
            with self.assertRaisesRegex(ValueError, "仅支持公开 GitHub 仓库"):
                ProjectExplainer()("example/private")
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
