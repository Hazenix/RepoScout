import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from reposcout.core import (
    Candidate, DefinitiveMailError, ReviewOutcome, Store, ZONE, deliver, parse_trending,
    reconcile_delivery, restore_backup, run_day, tick,
)

DAY = datetime(2026, 11, 6, 13, 0, tzinfo=ZONE)
EVENING = datetime(2026, 11, 6, 18, 5, tzinfo=ZONE)


def complete(*candidates):
    return ReviewOutcome("completed", tuple(candidates), "# 报告\n完整范围", "# 进度\n完整范围", "2026-11-06 17:55 CST")


class DailyRunTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "data")

    def test_board_actions_and_trending_order_persist(self):
        self.store.follow("https://github.com/acme/kept")
        self.store.ignore_repo("acme/ignored", True)
        self.store.ignore_repo("acme/undone", True)
        self.store.ignore_repo("acme/undone", False)
        self.store.unfollow("nightly-labs/openbot")
        self.store.follow("https://github.com/acme/kept.git")
        self.store.follow("https://github.com/ACME/KEPT")
        trending = [("acme/kept", "followed"), ("acme/ignored", "ignored"),
                    ("acme/undone", "first"), ("acme/new", "second")]
        calls = []
        run_day(self.store, lambda: trending, lambda slug, day: calls.append(slug) or complete(), DAY)
        view = Store(self.store.root).view(DAY.date().isoformat())
        self.assertEqual([row["slug"] for row in view["trending"]], ["acme/undone", "acme/new"])
        self.assertEqual(sum(row["slug"] == "acme/kept" for row in view["repositories"]), 1)
        self.assertNotIn("nightly-labs/openbot", calls)
        self.assertEqual(view["scan"]["state"], "completed")

    def test_full_run_email_first_time_only_and_failure_isolated(self):
        candidate = Candidate("修复登录流程", "https://github.com/earendil-works/pi/issues/42", "复现已确认，缺少失败回退。", "fix")
        calls = []
        def review(slug, day):
            calls.append(slug)
            if slug == "nightly-labs/openbot":
                return ReviewOutcome("failed", error="HTTP 429")
            return complete(candidate) if slug == "earendil-works/pi" else complete()
        trending = [("new/one", "快速增长的本机工具"), ("new/two", "新的开源库")]
        view = run_day(self.store, lambda: trending, review, DAY)
        self.assertEqual(view["scan"]["state"], "partial")
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(view["opportunities"]), 1)
        self.assertEqual(view["runs"][2]["state"], "failed")
        messages = []
        self.assertEqual(deliver(self.store, lambda *args: messages.append(args), DAY), "before_send_window")
        self.assertEqual(deliver(self.store, lambda *args: messages.append(args), EVENING), "sent")
        self.assertEqual(len(messages), 1)
        sent_view = self.store.view(DAY.date().isoformat())
        self.assertEqual(sent_view["trending"], [])
        self.assertEqual([row["slug"] for row in sent_view["sent_pending"]], ["new/one", "new/two"])
        self.assertIn("新仓库", messages[0][1])
        self.assertIn("新 PR 机会", messages[0][1])
        self.assertIn("https://github.com/earendil-works/pi/issues/42", messages[0][1])
        run_day(self.store, lambda: trending, review, DAY)
        self.assertEqual(len(calls), 4)
        self.assertEqual(deliver(self.store, lambda *args: messages.append(args), EVENING), "nothing_pending")
        self.assertEqual(len(messages), 1)

    def test_next_day_keeps_opportunity_identity_and_suppresses_sent_repo(self):
        candidate = Candidate("同一机会", "https://github.com/earendil-works/pi/issues/42", "原始理由", "fix")
        run_day(self.store, lambda: [("acme/repeated", "第一天")],
                lambda slug, day: complete(candidate) if slug == "earendil-works/pi" else complete(), DAY)
        self.assertEqual(deliver(self.store, lambda *args: None, EVENING), "sent")
        next_day = datetime(2026, 11, 7, 13, 0, tzinfo=ZONE)
        view = run_day(self.store, lambda: [("ACME/REPEATED", "第二天")],
                       lambda slug, day: complete(candidate) if slug == "earendil-works/pi" else complete(), next_day)
        self.assertEqual(view["trending"], [])
        self.assertEqual([row["slug"] for row in view["sent_pending"]], ["acme/repeated"])
        self.assertEqual(len(view["opportunities"]), 1)
        self.assertEqual(view["opportunities"][0]["status"], "current")
        self.assertEqual(deliver(self.store, lambda *args: self.fail("repeated mail"),
                                 datetime(2026, 11, 7, 18, 0, tzinfo=ZONE)), "nothing_pending")

    def test_daily_recommendations_do_not_backfill_after_ten_are_sent(self):
        trending = [(f"acme/repo-{number}", f"第 {number} 个") for number in range(12)]
        view = run_day(self.store, lambda: trending, lambda slug, day: complete(), DAY)
        self.assertEqual([row["slug"] for row in view["trending"]], [slug for slug, _ in trending[:10]])
        self.assertEqual(deliver(self.store, lambda *args: None, EVENING), "sent")
        sent_view = self.store.view(DAY.date().isoformat())
        self.assertEqual(sent_view["trending"], [])
        self.assertEqual(len(sent_view["sent_pending"]), 10)
        next_day = datetime(2026, 11, 7, 13, tzinfo=ZONE)
        next_view = run_day(self.store, lambda: trending, lambda slug, day: complete(), next_day)
        self.assertEqual([row["slug"] for row in next_view["trending"]], [slug for slug, _ in trending[10:]])

    def test_definitive_mail_failure_retries_frozen_previous_message(self):
        run_day(self.store, lambda: [("acme/old", "昨日推荐")], lambda slug, day: complete(), DAY)
        def rejected(*args):
            raise DefinitiveMailError("SMTP 550")
        self.assertEqual(deliver(self.store, rejected, EVENING), "failed")
        captured = []
        next_day = datetime(2026, 11, 7, 18, tzinfo=ZONE)
        self.assertEqual(tick(self.store, lambda: [], lambda slug, day: complete(),
                              lambda *args: captured.append(args), next_day,
                              finished_at=lambda: next_day), "previous_delivery_retried")
        self.assertEqual(len(captured), 1)
        self.assertIn("2026-11-06", captured[0][0])
        self.assertEqual(self.store.view("2026-11-06")["delivery"]["status"], "sent")
        self.assertEqual(tick(self.store, lambda: self.fail("duplicate scan"),
                              lambda slug, day: self.fail("duplicate review"),
                              lambda *args: self.fail("duplicate mail"), next_day,
                              finished_at=lambda: next_day), "nothing_pending")

    def test_unmailed_opportunity_absent_from_next_review_is_not_new_next_day(self):
        candidate = Candidate("昨日机会", "https://github.com/earendil-works/pi/issues/42", "昨日核验", "fix")
        run_day(self.store, lambda: [],
                lambda slug, day: complete(candidate) if slug == "earendil-works/pi" else complete(), DAY)
        next_day = datetime(2026, 11, 7, 13, tzinfo=ZONE)
        view = run_day(self.store, lambda: [], lambda slug, day: complete(), next_day)
        self.assertEqual(view["opportunities"][0]["last_seen"], "2026-11-06")
        self.assertEqual(deliver(self.store, lambda *args: self.fail("stale opportunity mailed"),
                                 datetime(2026, 11, 7, 18, tzinfo=ZONE)), "nothing_pending")

    def test_source_only_opportunity_uses_stable_identity_across_commits(self):
        first = Candidate("源码缺口", "https://github.com/earendil-works/pi/blob/abc/src/login.ts",
                          "具体入口缺少回退。", "fix", "source:src/login.ts:retry")
        second = Candidate("源码缺口", "https://github.com/earendil-works/pi/blob/def/src/login.ts",
                           "再次核验同一入口。", "fix", "source:src/login.ts:retry")
        run_day(self.store, lambda: [],
                lambda slug, day: complete(first) if slug == "earendil-works/pi" else complete(), DAY)
        next_day = datetime(2026, 11, 7, 13, tzinfo=ZONE)
        view = run_day(self.store, lambda: [],
                       lambda slug, day: complete(second) if slug == "earendil-works/pi" else complete(), next_day)
        self.assertEqual(len(view["opportunities"]), 1)
        self.assertEqual(view["opportunities"][0]["last_seen"], "2026-11-07")

    def test_candidate_without_stable_source_identity_makes_review_incomplete(self):
        candidate = Candidate("源码缺口", "https://github.com/earendil-works/pi/blob/abc/src/login.ts", "原因", "fix")
        view = run_day(self.store, lambda: [],
                       lambda slug, day: complete(candidate) if slug == "earendil-works/pi" else complete(), DAY)
        self.assertEqual(view["opportunities"], [])
        run = next(item for item in view["runs"] if item["slug"] == "earendil-works/pi")
        self.assertEqual(run["state"], "incomplete")

    def test_failed_or_incomplete_review_never_publishes_candidates(self):
        bad = Candidate("未核验", "https://github.com/nightly-labs/openbot/issues/12", "未完成", "fix")
        def review(slug, day):
            if slug == "nightly-labs/openbot":
                return ReviewOutcome("incomplete", (bad,), "半份报告", "进度", "2026-11-06 15:00 CST", "HTTP 429")
            return complete()
        view = run_day(self.store, lambda: [], review, DAY)
        self.assertEqual(view["opportunities"], [])
        self.assertEqual(deliver(self.store, lambda *args: self.fail("empty mail"), EVENING), "nothing_pending")
        self.assertEqual(view["scan"]["state"], "partial")

    def test_historical_import_recheck_and_backup_restore_keep_delivery_history(self):
        source = Path(self.temp.name) / "imports"
        source.mkdir()
        mapping = {"nightly-labs-openbot": "nightly-labs/openbot", "earendil-works-pi": "earendil-works/pi",
                   "OpenViking": "volcengine/OpenViking", "deer-flow": "bytedance/deer-flow"}
        for name, slug in mapping.items():
            (source / f"PR_HINT_REPORT_{name}.md").write_text(
                f"# 历史\n## 总结\n截至 2026-11-04 12:00 CST\n- 主推荐 1 项：[旧机会](https://github.com/{slug}/issues/7)\n## 详情\n", encoding="utf-8")
        self.assertEqual(self.store.import_history(source), 4)
        view = self.store.view()
        self.assertTrue(all(item["pending_recheck"] for item in view["opportunities"]))
        self.assertTrue(all(item["report_day"] == "2026-11-04" for item in view["history"]))
        self.assertEqual(self.store.import_history(source), 0)
        sent = []
        run_day(self.store, lambda: [("acme/new", "新仓库")], lambda slug, day: complete(), DAY)
        self.assertEqual(deliver(self.store, lambda *args: sent.append(args), EVENING), "sent")
        backup = self.store.backup(Path(self.temp.name) / "backup")
        restore_backup(backup, Path(self.temp.name) / "restored")
        restored = Store(Path(self.temp.name) / "restored")
        self.assertEqual(restored.view()["opportunities"], self.store.view()["opportunities"])
        self.assertEqual(restored.view()["repositories"], self.store.view()["repositories"])
        self.assertEqual(deliver(restored, lambda *args: self.fail("duplicate mail"), EVENING), "nothing_pending")

    def test_trending_failure_is_visible_and_does_not_erase_choices(self):
        self.store.ignore_repo("old/ignored", True)
        def fail():
            raise RuntimeError("HTTP 429")
        view = run_day(self.store, fail, lambda slug, day: complete(), DAY)
        self.assertEqual(view["scan"]["trending_state"], "failed")
        self.assertIn("HTTP 429", view["scan"]["trending_error"])
        self.assertEqual(view["trending"], [])
        self.assertEqual(view["ignored"][0]["slug"], "old/ignored")

    def test_delayed_send_and_smtp_uncertainty(self):
        def later(): return datetime(2026, 11, 6, 19, 0, tzinfo=ZONE)
        sent = []
        result = tick(self.store, lambda: [("acme/new", "新仓库")], lambda slug, day: complete(),
                      lambda *args: sent.append(args), DAY, finished_at=later)
        self.assertEqual(result, "sent")
        self.assertEqual(len(sent), 1)
        other = Store(Path(self.temp.name) / "other")
        run_day(other, lambda: [("acme/new", "新仓库")], lambda slug, day: complete(), DAY)
        self.assertEqual(deliver(other, lambda *args: (_ for _ in ()).throw(TimeoutError("SMTP timeout")), EVENING), "uncertain")
        self.assertEqual(deliver(other, lambda *args: self.fail("unsafe retry"), EVENING), "nothing_pending")
        self.assertEqual(reconcile_delivery(other, lambda _: False, DAY.date().isoformat()), "not_found_still_uncertain")
        self.assertEqual(reconcile_delivery(other, lambda _: True, DAY.date().isoformat()), "confirmed_sent")
        self.assertEqual(other.view(DAY.date().isoformat())["delivery"]["status"], "sent")

    def test_review_finishing_after_midnight_sends_original_days_digest(self):
        sent = []
        result = tick(self.store, lambda: [("acme/new", "新仓库")],
                      lambda slug, day: complete(), lambda *args: sent.append(args), DAY,
                      finished_at=lambda: datetime(2026, 11, 7, 2, 0, tzinfo=ZONE))
        self.assertEqual(result, "sent")
        self.assertIn("2026-11-06", sent[0][0])
        self.assertEqual(self.store.view(DAY.date().isoformat())["delivery"]["status"], "sent")

    def test_startup_reconciles_crashed_previous_day(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO scans(day,started_at,catch_up,state,trending_state) VALUES ('2026-11-05','2026-11-05T13:00:00+08:00',0,'running','completed')")
            db.execute("INSERT INTO repo_runs(day,slug,state) VALUES ('2026-11-05','nightly-labs/openbot','running')")
        view = run_day(self.store, lambda: [], lambda slug, day: complete(), DAY, catch_up=True)
        self.assertTrue(view["scan"]["catch_up"])
        previous = next(row for row in view["scan_history"] if row["day"] == "2026-11-05")
        self.assertEqual(previous["state"], "partial")
        previous_run = next(row for row in view["run_history"] if row["day"] == "2026-11-05")
        self.assertEqual(previous_run["state"], "incomplete")

    def test_scan_history_identifies_missing_day_and_actual_times(self):
        run_day(self.store, lambda: [], lambda slug, day: complete(), DAY)
        self.assertEqual(self.store.view("2026-11-07")["missing_days"], [])
        later = datetime(2026, 11, 8, 14, 20, tzinfo=ZONE)
        view = run_day(self.store, lambda: [], lambda slug, day: complete(), later, catch_up=True)
        self.assertEqual(view["missing_days"], ["2026-11-07"])
        self.assertEqual(view["scan_history"][0]["started_at"], later.isoformat())
        self.assertTrue(view["scan_history"][0]["finished_at"])

    def test_parser_preserves_page_order(self):
        html = '<article class="Box-row"><h2><a href="/one/first">one / first</a></h2><p class="col-9">First item</p></article>' \
               '<article class="Box-row"><h2><a href="/two/second">two / second</a></h2><p class="col-9">Second item</p></article>'
        self.assertEqual(parse_trending(html), [("one/first", "First item"), ("two/second", "Second item")])

    def test_historical_summary_does_not_import_supporting_pr(self):
        from reposcout.core import extract_historical_candidates
        report = """## 总结
1. **[fix] [#1 修复问题](https://github.com/acme/tool/issues/1)**：相邻 [PR #2](https://github.com/acme/tool/pull/2) 未覆盖本问题。
## 候选详情
"""
        self.assertEqual([item.url for item in extract_historical_candidates(report)],
                         ["https://github.com/acme/tool/issues/1"])


if __name__ == "__main__":
    unittest.main()
