"""Loopback-only board and local actions."""
from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .brief import ProjectExplainer
from .core import Store

WEB_DIR = Path(__file__).resolve().parent / "web"


def serve(store: Store, port: int = 8765) -> None:
    brief_slot = threading.Semaphore(1)

    def generate_brief(slug: str) -> None:
        # 简介与每日扫描分开执行；串行调用 Codex，避免多次点击挤占调研资源。
        with brief_slot:
            try:
                store.finish_project_brief(slug, ProjectExplainer()(slug))
            except Exception as exc:
                store.finish_project_brief(slug, error=f"{type(exc).__name__}: {exc}"[-1500:])

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
            if self.path not in ("/api/action", "/api/brief"):
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
                if self.path == "/api/brief":
                    brief, started = store.request_project_brief(payload["value"], payload.get("refresh") is True)
                    if started:
                        threading.Thread(target=generate_brief, args=(brief["slug"],), daemon=True).start()
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
    print(f"RepoScout 看板：http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
