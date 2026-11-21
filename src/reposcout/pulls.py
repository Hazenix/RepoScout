"""Read and cache the authenticated GitHub user's authored pull requests."""
from __future__ import annotations

import json
import subprocess
import threading
from typing import Callable

from .core import Store, now_cn


SNAPSHOT_KEY = "pr_monitor_snapshot"
PULL_REQUEST_QUERY = """
query RepoScoutPullRequests($after: String) {
  viewer {
    login
    pullRequests(first: 100, after: $after, orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        id number title url state mergedAt isDraft createdAt updatedAt
        repository { nameWithOwner isPrivate }
        reviewDecision additions deletions
      }
    }
  }
}
"""


def fetch_pull_requests() -> dict:
    """Read every page before publishing, so counts never describe a partial scan."""
    items: dict[str, dict] = {}
    cursor = None
    cursors = set()
    login = None
    expected_count = None
    while True:
        command = ["gh", "api", "graphql", "-f", f"query={PULL_REQUEST_QUERY}"]
        if cursor is not None:
            command += ["-f", f"after={cursor}"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("gh api graphql timed out after 60 seconds") from exc
        if result.returncode:
            raise RuntimeError(f"gh api graphql exited {result.returncode}: {result.stderr[-1200:].strip()}")
        try:
            payload = json.loads(result.stdout)
            if payload.get("errors"):
                raise RuntimeError("GitHub GraphQL: " + "; ".join(
                    str(error.get("message", error)) for error in payload["errors"]))
            viewer = payload["data"]["viewer"]
            page = viewer["pullRequests"]
            page_login, page_count = viewer["login"], page["totalCount"]
            if not isinstance(page_login, str) or not isinstance(page_count, int) or page_count < 0:
                raise ValueError("invalid login or totalCount")
            if login is not None and (login != page_login or expected_count != page_count):
                raise RuntimeError("GitHub PR collection changed during pagination; refresh again")
            login, expected_count = page_login, page_count
            for node in page["nodes"]:
                item = _pull_request(node)
                items[item["id"]] = item
            page_info = page["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("missing or repeated pagination cursor")
            cursors.add(cursor)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise RuntimeError(f"Invalid GitHub PR response: {exc}") from exc
    if len(items) != expected_count:
        raise RuntimeError(f"Incomplete GitHub PR collection: expected {expected_count}, received {len(items)}")
    return {"login": login, "updated_at": now_cn().isoformat(),
            "items": sorted(items.values(), key=lambda item: item["updated_at"], reverse=True)}


def _pull_request(node: dict) -> dict:
    state = "MERGED" if node["mergedAt"] else node["state"]
    if state not in ("OPEN", "MERGED", "CLOSED"):
        raise ValueError(f"unknown pull request state: {state}")
    item = {"id": node["id"], "number": node["number"], "title": node["title"],
            "url": node["url"], "state": state, "is_draft": node["isDraft"],
            "repository": node["repository"]["nameWithOwner"],
            "is_private": node["repository"]["isPrivate"],
            "created_at": node["createdAt"], "updated_at": node["updatedAt"],
            "merged_at": node["mergedAt"], "review_decision": node["reviewDecision"],
            "additions": node["additions"], "deletions": node["deletions"]}
    if not all(isinstance(item[key], str) and item[key] for key in
               ("id", "title", "url", "repository", "created_at", "updated_at")):
        raise ValueError("missing pull request text fields")
    if not all(isinstance(item[key], int) and not isinstance(item[key], bool) and item[key] >= 0
               for key in ("number", "additions", "deletions")):
        raise ValueError("invalid pull request counts")
    if not all(isinstance(item[key], bool) for key in ("is_draft", "is_private")):
        raise ValueError("invalid pull request flags")
    return item


class PullRequestMonitor:
    """Keep one complete local snapshot and serialize manual and periodic refreshes."""

    def __init__(self, store: Store, reader: Callable[[], dict] = fetch_pull_requests,
                 interval: float = 15 * 60):
        self.store = store
        self.reader = reader
        self.interval = interval
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._scheduler: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._syncing = False
        self._error = ""
        self._snapshot = {"login": "", "updated_at": None, "items": []}
        cached = store.get_setting(SNAPSHOT_KEY)
        if cached:
            try:
                snapshot = json.loads(cached)
                if not (isinstance(snapshot["login"], str) and isinstance(snapshot["updated_at"], str)
                        and isinstance(snapshot["items"], list)):
                    raise ValueError("invalid cached snapshot")
                self._snapshot = snapshot
            except (ValueError, KeyError, TypeError) as exc:
                self._error = f"Invalid cached PR snapshot: {exc}"

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot | {"items": [dict(item) for item in self._snapshot["items"]],
                                     "syncing": self._syncing, "error": self._error}

    def refresh(self) -> bool:
        with self._lock:
            if self._syncing or self._stopping.is_set():
                return False
            self._syncing = True
            self._error = ""
            self._worker = threading.Thread(target=self._sync, daemon=True)
            self._worker.start()
            return True

    def _sync(self) -> None:
        try:
            snapshot = self.reader()
            # 全量成功才替换缓存；GitHub 或网络失败时保留上次完整数据。
            with self._lock:
                if not self._stopping.is_set():
                    self.store.set_setting(SNAPSHOT_KEY, json.dumps(snapshot, ensure_ascii=False))
                    self._snapshot = snapshot
        except Exception as exc:
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"[-1500:]
        finally:
            with self._lock:
                self._syncing = False

    def start(self) -> None:
        if self._scheduler is not None:
            return
        self._scheduler = threading.Thread(target=self._run, daemon=True)
        self._scheduler.start()

    def _run(self) -> None:
        while not self._stopping.is_set():
            self.refresh()
            self._stopping.wait(self.interval)

    def close(self) -> None:
        self._stopping.set()
        if self._scheduler is not None:
            self._scheduler.join(timeout=2)
