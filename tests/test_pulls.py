import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from reposcout.core import Store
from reposcout.pulls import PullRequestMonitor, fetch_pull_requests


def pull(number, state="OPEN", merged_at=None):
    return {"id": f"PR_{number}", "number": number, "title": f"Change {number}",
            "url": f"https://github.com/example/tool/pull/{number}", "state": state,
            "mergedAt": merged_at, "isDraft": False,
            "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-11-21T00:00:00Z",
            "repository": {"nameWithOwner": "example/tool", "isPrivate": False},
            "reviewDecision": "REVIEW_REQUIRED", "additions": 10, "deletions": 2}


def page(nodes, total_count, has_next=False, cursor=None):
    return {"data": {"viewer": {"login": "example", "pullRequests": {
        "totalCount": total_count, "nodes": nodes,
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}}}}


def response(payload):
    return subprocess.CompletedProcess(["gh", "api", "graphql"], 0, json.dumps(payload), "")


class PullRequestReaderTest(unittest.TestCase):
    def test_reads_all_pages_and_distinguishes_merged_from_closed(self):
        first = [pull(number) for number in range(1, 101)]
        last = [pull(101, "MERGED", "2026-11-20T00:00:00Z"), pull(102, "CLOSED")]
        with patch("reposcout.pulls.subprocess.run", side_effect=[
            response(page(first, 102, True, "cursor-100")), response(page(last, 102))
        ]) as run:
            snapshot = fetch_pull_requests()
        self.assertEqual(len(snapshot["items"]), 102)
        self.assertEqual(snapshot["login"], "example")
        self.assertIn("after=cursor-100", run.call_args_list[1].args[0])
        self.assertEqual(snapshot["items"][-2]["state"], "MERGED")
        self.assertEqual(snapshot["items"][-1]["state"], "CLOSED")

    def test_deduplicates_ids_at_a_page_boundary(self):
        with patch("reposcout.pulls.subprocess.run", side_effect=[
            response(page([pull(1)], 2, True, "next")), response(page([pull(1), pull(2)], 2))
        ]):
            snapshot = fetch_pull_requests()
        self.assertEqual(len(snapshot["items"]), 2)

    def test_rejects_truncated_or_looping_pages(self):
        cases = [
            [response(page([pull(1)], 2))],
            [response(page([pull(1)], 2, True, None))],
            [response(page([pull(1)], 2, True, "same")),
             response(page([pull(1)], 2, True, "same"))],
        ]
        for pages in cases:
            with self.subTest(pages=len(pages)), \
                 patch("reposcout.pulls.subprocess.run", side_effect=pages):
                with self.assertRaises(RuntimeError):
                    fetch_pull_requests()

    def test_rejects_graphql_errors_and_timeout(self):
        with patch("reposcout.pulls.subprocess.run", return_value=response({
            "errors": [{"message": "Resource not accessible by integration"}], "data": None
        })):
            with self.assertRaisesRegex(RuntimeError, "Resource not accessible by integration"):
                fetch_pull_requests()
        with patch("reposcout.pulls.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 60)):
            with self.assertRaisesRegex(RuntimeError, "timed out after 60 seconds"):
                fetch_pull_requests()


class PullRequestMonitorTest(unittest.TestCase):
    def wait_for_sync(self, monitor):
        deadline = time.monotonic() + 2
        while monitor.snapshot()["syncing"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(monitor.snapshot()["syncing"])

    def test_failure_keeps_last_complete_cache_and_restart_reads_it(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root))
            snapshot = {"login": "example", "updated_at": "2026-11-21T12:00:00+08:00",
                        "items": [{"id": "PR_1", "state": "OPEN"}]}
            outcomes = iter([snapshot, RuntimeError("HTTP 502 Bad Gateway")])

            def read():
                result = next(outcomes)
                if isinstance(result, Exception):
                    raise result
                return result

            monitor = PullRequestMonitor(store, reader=read)
            self.assertIsNone(monitor.snapshot()["updated_at"])
            monitor.refresh()
            self.wait_for_sync(monitor)
            monitor.refresh()
            self.wait_for_sync(monitor)
            self.assertEqual(monitor.snapshot()["items"], snapshot["items"])
            self.assertEqual(monitor.snapshot()["updated_at"], snapshot["updated_at"])
            self.assertIn("HTTP 502 Bad Gateway", monitor.snapshot()["error"])
            restored = PullRequestMonitor(store)
            self.assertEqual(restored.snapshot()["items"], snapshot["items"])
            monitor.close()
            restored.close()

    def test_overlapping_refreshes_start_only_one_reader(self):
        entered = threading.Event()
        finish = threading.Event()
        calls = []
        with tempfile.TemporaryDirectory() as root:
            def read():
                calls.append(True)
                entered.set()
                finish.wait(2)
                return {"login": "example", "updated_at": "2026-11-21T12:00:00+08:00", "items": []}

            monitor = PullRequestMonitor(Store(Path(root)), reader=read)
            self.assertTrue(monitor.refresh())
            self.assertTrue(entered.wait(1))
            self.assertFalse(monitor.refresh())
            finish.set()
            self.wait_for_sync(monitor)
            self.assertEqual(len(calls), 1)
            self.assertEqual(monitor.snapshot()["items"], [])
            self.assertEqual(monitor.snapshot()["error"], "")
            monitor.close()

    def test_close_stops_scheduler_and_does_not_publish_an_inflight_result(self):
        entered = threading.Event()
        finish = threading.Event()
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root))

            def read():
                entered.set()
                finish.wait(2)
                return {"login": "example", "updated_at": "2026-11-21T12:00:00+08:00", "items": []}

            monitor = PullRequestMonitor(store, reader=read, interval=0.01)
            monitor.start()
            self.assertTrue(entered.wait(1))
            monitor.close()
            finish.set()
            self.wait_for_sync(monitor)
            self.assertFalse(monitor.refresh())
            self.assertIsNone(monitor.snapshot()["updated_at"])
            self.assertEqual(store.get_setting("pr_monitor_snapshot"), "")


if __name__ == "__main__":
    unittest.main()
