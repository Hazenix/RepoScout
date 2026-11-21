"""Loopback-only board and local actions."""
from __future__ import annotations

import json
import mimetypes
import sys
import threading
from itertools import count
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, PriorityQueue
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from .brief import ProjectExplainer
from .core import BRIEF_INTERRUPTED_ERROR, Store
from .pulls import PullRequestMonitor

WEB_DIR = Path(__file__).resolve().parent / "web"


def prepare_visible_briefs(store: Store, enqueue: Callable[[str], None]) -> None:
    """Queue missing briefs for repositories shown in the current board."""
    state = store.view()
    seen = set()
    for section in ("trending", "sent_pending", "repositories"):
        for repository in state[section]:
            slug = repository["slug"]
            if slug in seen:
                continue
            seen.add(slug)
            cached = store.project_brief(slug)
            if cached and not (cached["state"] == "failed" and cached["error"] == BRIEF_INTERRUPTED_ERROR):
                continue
            brief, started = store.request_project_brief(slug)
            if started:
                enqueue(brief["slug"])


def serve(store: Store, port: int = 8765) -> None:
    brief_jobs: PriorityQueue[tuple[int, int, str]] = PriorityQueue()
    order = count()
    stopping = threading.Event()
    pr_monitor = PullRequestMonitor(store)

    def enqueue_brief(slug: str, priority: int) -> None:
        brief_jobs.put((priority, next(order), slug))

    def generate_brief(slug: str) -> None:
        try:
            store.finish_project_brief(slug, ProjectExplainer()(slug))
        except Exception as exc:
            store.finish_project_brief(slug, error=f"{type(exc).__name__}: {exc}"[-1500:])

    def run_brief_jobs() -> None:
        # 单个 worker 串行调用 Codex；手动打开的项目优先于后台预生成队列。
        while not stopping.is_set():
            try:
                _, _, slug = brief_jobs.get(timeout=1)
            except Empty:
                continue
            try:
                if (store.project_brief(slug) or {}).get("state") == "running":
                    generate_brief(slug)
            except Exception as exc:
                print(f"项目简介后台任务失败 {slug}: {type(exc).__name__}: {exc}", file=sys.stderr)
            finally:
                brief_jobs.task_done()

    def prefetch_briefs() -> None:
        while not stopping.is_set():
            try:
                prepare_visible_briefs(store, lambda slug: enqueue_brief(slug, 1))
            except Exception as exc:
                print(f"预生成项目简介失败: {type(exc).__name__}: {exc}", file=sys.stderr)
            stopping.wait(60)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # 用户关闭简介窗口后，后台分析仍会写入缓存。
                pass

        def do_GET(self) -> None:
            if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                self._send(403, b"Forbidden", "text/plain")
                return
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/api/state":
                self._send(200, json.dumps(store.view(), ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return
            if path == "/api/prs":
                self._send(200, json.dumps(pr_monitor.snapshot(), ensure_ascii=False).encode(),
                           "application/json; charset=utf-8")
                return
            if path == "/api/brief":
                try:
                    value = parse_qs(parsed.query)["value"][0]
                    brief = store.project_brief(value)
                except (ValueError, KeyError, IndexError) as exc:
                    self._send(400, json.dumps({"error": str(exc)}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                    return
                if brief is None:
                    self._send(404, json.dumps({"error": "尚未生成项目简介"}, ensure_ascii=False).encode(),
                               "application/json; charset=utf-8")
                    return
                self._send(200, json.dumps(brief, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return
            if path.startswith("/reports/"):
                relative = path.removeprefix("/reports/")
                target = (store.root / relative).resolve()
                if not target.is_relative_to(store.reports) or not target.is_file() or target.suffix != ".md":
                    self._send(404, b"Not Found", "text/plain")
                    return
                self._send(200, target.read_bytes(), "text/markdown; charset=utf-8")
                return
            if path == "/":
                path = "/index.html"
            target = (WEB_DIR / path.lstrip("/")).resolve()
            if not target.is_relative_to(WEB_DIR) or not target.is_file():
                self._send(404, b"Not Found", "text/plain")
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type == "application/javascript":
                content_type += "; charset=utf-8"
            self._send(200, target.read_bytes(), content_type)

        def do_POST(self) -> None:
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if origin != f"http://{host}" or host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                self._send(403, b"Forbidden", "text/plain")
                return
            if self.path not in ("/api/action", "/api/brief", "/api/prs"):
                self._send(404, b"Not Found", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0:
                self._send(400, b"Invalid Content-Length", "text/plain")
                return
            if length > 4096:
                self._send(413, b"Payload Too Large", "text/plain")
                return
            try:
                payload = json.loads(self.rfile.read(length))
                if self.path == "/api/prs":
                    pr_monitor.refresh()
                    self._send(202, json.dumps(pr_monitor.snapshot(), ensure_ascii=False).encode(),
                               "application/json; charset=utf-8")
                    return
                if self.path == "/api/brief":
                    brief, started = store.request_project_brief(payload["value"], payload.get("refresh") is True)
                    if started or brief["state"] == "running":
                        enqueue_brief(brief["slug"], 0)
                    self._send(202 if brief["state"] == "running" else 200,
                               json.dumps(brief, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                    return
                action = payload["action"]
                value = payload["value"]
                if action == "follow":
                    store.follow(value)
                elif action == "unfollow":
                    store.unfollow(value)
                elif action == "ignore":
                    store.ignore_repo(value, True)
                elif action == "undo_ignore":
                    store.ignore_repo(value, False)
                elif action == "opportunity_status":
                    store.set_opportunity_status(value, payload["status"])
                else:
                    raise ValueError("未知操作")
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self._send(400, json.dumps({"error": str(exc)}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return
            self._send(200, json.dumps(store.view(), ensure_ascii=False).encode(), "application/json; charset=utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    store.interrupt_project_briefs()
    brief_worker = threading.Thread(target=run_brief_jobs, daemon=True)
    brief_worker.start()
    prefetch_thread = threading.Thread(target=prefetch_briefs, daemon=True)
    prefetch_thread.start()
    pr_monitor.start()
    print(f"RepoScout 看板：http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    finally:
        stopping.set()
        pr_monitor.close()
        prefetch_thread.join(timeout=2)
        brief_worker.join(timeout=2)
        server.server_close()
