import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reposcout.brief import ProjectExplainer
from reposcout.core import Store


class ProjectBriefTest(unittest.TestCase):
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
