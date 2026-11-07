"""GitHub, Codex/pr-hint, macOS Keychain and QQ SMTP adapters."""
from __future__ import annotations

import json
import imaplib
import smtplib
import subprocess
from email.message import EmailMessage
from pathlib import Path

from .core import Candidate, DefinitiveMailError, ReviewOutcome, now_cn


OUTCOME_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["state", "candidates", "cutoff", "error"],
    "properties": {
        "state": {"type": "string", "enum": ["completed", "failed", "incomplete"]},
        "cutoff": {"type": "string"}, "error": {"type": "string"},
        "candidates": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "url", "reason", "kind", "identity"],
            "properties": {key: {"type": "string"} for key in ("title", "url", "reason", "kind", "identity")}
        }}
    }
}


class CodexReviewer:
    """Invokes the installed pr-hint skill; it never judges opportunities itself."""
    def __init__(self, data_dir: Path):
        self.research_dir = data_dir / "research"
        self.research_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def __call__(self, slug: str, day: str) -> ReviewOutcome:
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=30)
        if auth.returncode:
            return ReviewOutcome("failed", error="gh auth status: GitHub CLI is not authenticated")
        folder = self.research_dir / day / slug.replace("/", "__")
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        schema_path = folder / "outcome-schema.json"
        output_path = folder / "outcome.json"
        schema_path.write_text(json.dumps(OUTCOME_SCHEMA, ensure_ascii=False), encoding="utf-8")
        report_name = f"PR_HINT_REPORT_{slug.replace('/', '-')}.md"
        progress_name = f"PR_HINT_PROGRESS_{slug.replace('/', '-')}.md"
        prompt = f"""使用 $pr-hint 调研 https://github.com/{slug}。这是 RepoScout 每日任务的固定授权：
调研模式：全量 GitHub 审查；优先贡献类型：feat > fix > refactor/perf；主推荐数量：最多 4。
只处理这个仓库，按 skill 的完整研究流程写进度和报告，保留失败及未覆盖范围。
本次输出文件必须在当前目录：{report_name} 和 {progress_name}。
最后按提供的 JSON Schema 输出机器结果。仅在完整审查并核验后用 state=completed；
未完成、HTTP 429、核验不足或确认门禁未通过用 incomplete/failed，candidates 留空。
completed 时 candidates 只列报告中最多四项主推荐，每项给独立可读的 reason 和 GitHub 证据 URL；
若主推荐没有 Issue/PR，url 可指向 GitHub 源码证据，identity 必须是稳定的 source:仓库内路径:符号，
跨提交保持一致；有 Issue/PR 时 identity 设为空字符串。
没有机会时允许空数组。cutoff 写完整日期、时间和时区；error 保留关键英文错误。
不要更改目标仓库代码或创建 PR。"""
        command = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write",
                   "--output-schema", str(schema_path),
                   "--output-last-message", str(output_path), "-C", str(folder), prompt]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=12 * 60 * 60)
        except subprocess.TimeoutExpired:
            report_path = folder / report_name
            progress_path = folder / progress_name
            return ReviewOutcome("incomplete", report=report_path.read_text(encoding="utf-8") if report_path.is_file() else "",
                                 progress=progress_path.read_text(encoding="utf-8") if progress_path.is_file() else "",
                                 cutoff=now_cn().isoformat(), error="Codex review timed out after 12 hours")
        report_path = folder / report_name
        progress_path = folder / progress_name
        report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
        progress = progress_path.read_text(encoding="utf-8") if progress_path.is_file() else ""
        if result.returncode or not output_path.is_file():
            error = (result.stderr or result.stdout)[-1500:].strip()
            return ReviewOutcome("failed", report=report, progress=progress,
                                 error=f"codex exec exited {result.returncode}: {error}")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            candidates = tuple(Candidate(**candidate) for candidate in payload["candidates"])
            return ReviewOutcome(payload["state"], candidates, report, progress,
                                 payload["cutoff"], payload["error"])
        except (ValueError, KeyError, TypeError) as exc:
            return ReviewOutcome("incomplete", report=report, progress=progress,
                                 error=f"Invalid pr-hint outcome: {exc}")


class QQSender:
    def __init__(self, address: str):
        if not address or "@" not in address:
            raise DefinitiveMailError("请先配置 QQ 邮箱地址")
        self.address = address

    def _authorization_code(self) -> str:
        password = subprocess.run(
            ["security", "find-generic-password", "-s", "RepoScout QQ SMTP", "-a", self.address, "-w"],
            capture_output=True, text=True)
        if password.returncode:
            raise DefinitiveMailError("macOS Keychain 未找到 RepoScout QQ SMTP 授权码")
        return password.stdout.strip()

    def __call__(self, subject: str, body: str, message_id: str) -> None:
        authorization_code = self._authorization_code()
        message = EmailMessage()
        message["From"] = self.address
        message["To"] = self.address
        message["Subject"] = subject
        message["Message-ID"] = message_id
        message.set_content(body, charset="utf-8")
        try:
            with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30) as smtp:
                smtp.login(self.address, authorization_code)
                smtp.send_message(message)
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused) as exc:
            raise DefinitiveMailError(f"{type(exc).__name__}: {exc}") from exc

    def received(self, message_id: str) -> bool:
        """Check the configured mailbox for the exact Message-ID after a test send."""
        with imaplib.IMAP4_SSL("imap.qq.com", 993, timeout=30) as mailbox:
            mailbox.login(self.address, self._authorization_code())
            status, _ = mailbox.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError(f"IMAP select failed: {status}")
            status, ids = mailbox.search(None, "HEADER", "Message-ID", f'"{message_id}"')
            if status != "OK":
                raise RuntimeError(f"IMAP search failed: {status}")
            return bool(ids and ids[0])


def configure_keychain(address: str) -> None:
    if "@" not in address:
        raise ValueError("请输入有效邮箱地址")
    # -w without a value prompts securely. Never place the authorization code in argv or logs.
    subprocess.run(["security", "add-generic-password", "-U", "-s", "RepoScout QQ SMTP",
                    "-a", address, "-w"], check=True)
