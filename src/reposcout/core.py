"""Local state and the single daily-run boundary."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Shanghai")
INITIAL_REPOS = (
    "nightly-labs/openbot", "earendil-works/pi",
    "volcengine/OpenViking", "bytedance/deer-flow",
)
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ISSUE_PATTERN = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/(issues|pull)/(\d+)$")
ELIGIBLE_TRENDING_SQL = """
    SELECT t.slug,t.description,t.position FROM trending t
    LEFT JOIN repositories r ON r.slug=t.slug
    WHERE t.day=? AND COALESCE(r.followed,0)=0 AND COALESCE(r.ignored,0)=0
    AND NOT EXISTS (SELECT 1 FROM delivery_items di JOIN deliveries d ON d.day=di.day
        WHERE di.kind='repo' AND di.item_id=t.slug AND d.status='sent')
    ORDER BY t.position LIMIT 10
"""
PENDING_TRENDING_SQL = """
    SELECT t.slug,t.description,t.position FROM recommendation_items ri
    JOIN trending t ON t.day=ri.day AND t.slug=ri.slug
    LEFT JOIN repositories r ON r.slug=t.slug
    WHERE ri.day=? AND COALESCE(r.followed,0)=0 AND COALESCE(r.ignored,0)=0
    AND NOT EXISTS (SELECT 1 FROM delivery_items di JOIN deliveries d ON d.day=di.day
        WHERE di.kind='repo' AND di.item_id=t.slug AND d.status='sent')
    ORDER BY t.position
"""
PENDING_OPPORTUNITIES_SQL = """
    SELECT o.* FROM opportunities o
    WHERE o.historical=0 AND o.status='current' AND o.last_seen=?
    AND EXISTS (SELECT 1 FROM repo_runs rr WHERE rr.day=o.last_seen AND rr.slug=o.slug AND rr.state='completed')
    AND NOT EXISTS (SELECT 1 FROM delivery_items di JOIN deliveries d ON d.day=di.day
        WHERE di.kind='opportunity' AND di.item_id=o.id AND d.status='sent')
    ORDER BY o.slug, o.first_seen, o.id
"""


def now_cn() -> datetime:
    return datetime.now(ZONE)


def repo_slug(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/")
    if value.endswith(".git"):
        value = value[:-4]
    if not REPO_PATTERN.fullmatch(value):
        raise ValueError("请输入 GitHub 仓库 URL，例如 https://github.com/owner/repo")
    return value


def opportunity_id(url: str, identity: str = "") -> str:
    match = ISSUE_PATTERN.fullmatch(url.rstrip("/"))
    if match:
        return "/".join((match[1].lower(), match[2].lower(), match[3], match[4]))
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or len(parts) < 3:
        raise ValueError("机会证据链接必须是 GitHub URL")
    if not identity.startswith("source:") or not re.fullmatch(r"source:[A-Za-z0-9_./:#-]{3,300}", identity):
        raise ValueError("无 Issue/PR 的源码机会需要稳定的 source: 路径与符号标识")
    return f"{parts[0].lower()}/{parts[1].lower()}/{identity.lower()}"


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    reason: str
    kind: str = ""
    identity: str = ""


@dataclass(frozen=True)
class ReviewOutcome:
    state: str  # completed, failed, incomplete
    candidates: tuple[Candidate, ...] = ()
    report: str = ""
    progress: str = ""
    cutoff: str = ""
    error: str = ""


class ReviewRunner(Protocol):
    def __call__(self, slug: str, day: str) -> ReviewOutcome: ...


class TrendingReader(Protocol):
    def __call__(self) -> list[tuple[str, str]]: ...


class MailSender(Protocol):
    def __call__(self, subject: str, body: str, message_id: str) -> None: ...


class TrendingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, str]] = []
        self.in_article = False
        self.article_depth = 0
        self.in_heading = False
        self.in_link = False
        self.in_description = False
        self.slug = ""
        self.description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if tag == "article" and "Box-row" in classes:
            self.in_article = True
            self.article_depth = 1
            self.slug = ""
            self.description = ""
            return
        if not self.in_article:
            return
        if tag == "article":
            self.article_depth += 1
        if tag == "h2":
            self.in_heading = True
        if tag == "a" and self.in_heading:
            href = attr.get("href") or ""
            try:
                self.slug = repo_slug(href.lstrip("/"))
                self.in_link = True
            except ValueError:
                pass
        if tag == "p" and "col-9" in classes:
            self.in_description = True

    def handle_data(self, data: str) -> None:
        if self.in_description:
            self.description += data

    def handle_endtag(self, tag: str) -> None:
        if not self.in_article:
            return
        if tag == "a":
            self.in_link = False
        if tag == "h2":
            self.in_heading = False
        if tag == "p":
            self.in_description = False
        if tag == "article":
            self.article_depth -= 1
            if self.article_depth == 0:
                if self.slug and self.slug.lower() not in {item[0].lower() for item in self.rows}:
                    self.rows.append((self.slug, " ".join(self.description.split())))
                self.in_article = False


def parse_trending(html: str) -> list[tuple[str, str]]:
    parser = TrendingParser()
    parser.feed(html)
    if not parser.rows:
        raise ValueError("GitHub Trending 页面没有可识别的仓库")
    return parser.rows


def fetch_trending() -> list[tuple[str, str]]:
    import subprocess
    try:
        response = subprocess.run(
            ["curl", "--fail", "--location", "--retry", "2", "--max-time", "40",
             "--silent", "--show-error", "--user-agent", "RepoScout/0.1",
             "https://github.com/trending?since=daily"],
            capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        # curl 的 HTTP 错误详情在 stderr，默认异常文案只包含退出码。
        raise RuntimeError((exc.stderr or "").strip() or str(exc)) from exc
    return parse_trending(response.stdout)


class Store:
    def __init__(self, data_dir: Path):
        self.root = data_dir.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.reports = self.root / "reports"
        self.reports.mkdir(exist_ok=True, mode=0o700)
        self.database = self.root / "reposcout.db"
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _init(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS repositories (
                    slug TEXT PRIMARY KEY COLLATE NOCASE, followed INTEGER NOT NULL DEFAULT 0,
                    ignored INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trending (
                    day TEXT NOT NULL, position INTEGER NOT NULL, slug TEXT NOT NULL COLLATE NOCASE,
                    description TEXT NOT NULL, PRIMARY KEY(day, slug)
                );
                CREATE TABLE IF NOT EXISTS recommendation_items (
                    day TEXT NOT NULL, slug TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY(day, slug)
                );
                CREATE TABLE IF NOT EXISTS scans (
                    day TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                    catch_up INTEGER NOT NULL, state TEXT NOT NULL,
                    trending_state TEXT NOT NULL, trending_error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS repo_runs (
                    day TEXT NOT NULL, slug TEXT NOT NULL, state TEXT NOT NULL,
                    started_at TEXT, finished_at TEXT, report_path TEXT,
                    progress_path TEXT, cutoff TEXT, error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(day, slug)
                );
                CREATE TABLE IF NOT EXISTS historical_reports (
                    slug TEXT PRIMARY KEY, report_day TEXT NOT NULL, report_path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS opportunities (
                    id TEXT PRIMARY KEY, slug TEXT NOT NULL, title TEXT NOT NULL,
                    url TEXT NOT NULL, reason TEXT NOT NULL, kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'current', pending_recheck INTEGER NOT NULL DEFAULT 0,
                    historical INTEGER NOT NULL DEFAULT 0, first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deliveries (
                    day TEXT PRIMARY KEY, status TEXT NOT NULL, message_id TEXT NOT NULL,
                    subject TEXT NOT NULL, body TEXT NOT NULL, sent_at TEXT,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS delivery_items (
                    day TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL COLLATE NOCASE,
                    PRIMARY KEY(day, kind, item_id)
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_briefs (
                    slug TEXT PRIMARY KEY COLLATE NOCASE, state TEXT NOT NULL,
                    purpose TEXT NOT NULL DEFAULT '', usage TEXT NOT NULL DEFAULT '',
                    requirements TEXT NOT NULL DEFAULT '', caveats TEXT NOT NULL DEFAULT '',
                    sources TEXT NOT NULL DEFAULT '[]', error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
            """)
            for slug in INITIAL_REPOS:
                db.execute("INSERT OR IGNORE INTO repositories(slug, followed, added_at) VALUES (?, 1, ?)", (slug, now_cn().isoformat()))

    def follow(self, value: str) -> str:
        slug = repo_slug(value)
        with self.connect() as db:
            db.execute("INSERT INTO repositories(slug, followed, ignored, added_at) VALUES (?,1,0,?) ON CONFLICT(slug) DO UPDATE SET followed=1, ignored=0", (slug, now_cn().isoformat()))
        return slug

    def unfollow(self, value: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE repositories SET followed=0 WHERE slug=?", (repo_slug(value),))

    def ignore_repo(self, value: str, ignored: bool) -> None:
        slug = repo_slug(value)
        with self.connect() as db:
            db.execute("INSERT INTO repositories(slug, ignored, added_at) VALUES (?,?,?) ON CONFLICT(slug) DO UPDATE SET ignored=?", (slug, int(ignored), now_cn().isoformat(), int(ignored)))

    def set_opportunity_status(self, item_id: str, status: str) -> None:
        if status not in ("current", "invalid", "ignored"):
            raise ValueError("无效的机会状态")
        with self.connect() as db:
            db.execute("UPDATE opportunities SET status=? WHERE id=?", (status, item_id))

    def project_brief(self, value: str) -> dict | None:
        slug = repo_slug(value)
        with self.connect() as db:
            row = db.execute("SELECT * FROM project_briefs WHERE slug=?", (slug,)).fetchone()
        if row is None:
            return None
        brief = dict(row)
        brief["sources"] = json.loads(brief["sources"])
        return brief

    def request_project_brief(self, value: str, refresh: bool = False) -> tuple[dict, bool]:
        """Claim one generation per repository; repeated requests reuse the cached result."""
        slug = repo_slug(value)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM project_briefs WHERE slug=?", (slug,)).fetchone()
            if row and (row["state"] == "running" or (row["state"] == "completed" and not refresh)):
                brief = dict(row)
                brief["sources"] = json.loads(brief["sources"])
                return brief, False
            db.execute("""INSERT INTO project_briefs(slug,state,updated_at) VALUES (?,'running',?)
                ON CONFLICT(slug) DO UPDATE SET state='running', purpose='', usage='',
                requirements='', caveats='', sources='[]', error='', updated_at=excluded.updated_at""",
                (slug, now_cn().isoformat()))
        return self.project_brief(slug), True

    def finish_project_brief(self, value: str, result: dict | None = None, error: str = "") -> None:
        slug = repo_slug(value)
        result = result or {}
        with self.connect() as db:
            db.execute("""UPDATE project_briefs SET state=?, purpose=?, usage=?, requirements=?,
                caveats=?, sources=?, error=?, updated_at=? WHERE slug=? AND state='running'""",
                ("failed" if error else "completed", result.get("purpose", ""), result.get("usage", ""),
                 result.get("requirements", ""), result.get("caveats", ""),
                 json.dumps(result.get("sources", []), ensure_ascii=False), error,
                 now_cn().isoformat(), slug))

    def interrupt_project_briefs(self) -> None:
        # 服务进程重启后，旧进程的后台分析不会继续；允许用户重新触发。
        with self.connect() as db:
            db.execute("""UPDATE project_briefs SET state='failed', error='本机服务重启，点击重新生成',
                updated_at=? WHERE state='running'""", (now_cn().isoformat(),))

    def get_setting(self, key: str) -> str:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return str(row[0]) if row else ""

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?", (key, value, value))

    def view(self, day: str | None = None) -> dict:
        day = day or now_cn().date().isoformat()
        with self.connect() as db:
            repos = [dict(row) for row in db.execute("SELECT * FROM repositories WHERE followed=1 ORDER BY added_at, slug")]
            ignored = [dict(row) for row in db.execute("SELECT * FROM repositories WHERE ignored=1 ORDER BY slug")]
            scan = db.execute("SELECT * FROM scans WHERE day=?", (day,)).fetchone()
            latest = db.execute("SELECT * FROM scans ORDER BY day DESC LIMIT 1").fetchone()
            runs = [dict(row) for row in db.execute("SELECT * FROM repo_runs WHERE day=? ORDER BY slug", (day,))]
            scan_history = [dict(row) for row in db.execute("SELECT * FROM scans ORDER BY day DESC LIMIT 30")]
            first_scan = db.execute("SELECT MIN(day) FROM scans").fetchone()[0]
            recent_start = max(date.fromisoformat(first_scan), date.fromisoformat(day) - timedelta(days=29)) if first_scan else None
            scanned_days = {row["day"] for row in db.execute("SELECT day FROM scans WHERE day>=?", (recent_start.isoformat(),))} if recent_start else set()
            missing_days = []
            if recent_start:
                current = recent_start
                while current < date.fromisoformat(day):
                    if current.isoformat() not in scanned_days:
                        missing_days.append(current.isoformat())
                    current += timedelta(days=1)
            run_history = ([dict(row) for row in db.execute("SELECT * FROM repo_runs WHERE day>=? ORDER BY day DESC,slug",
                                                        (scan_history[-1]["day"],))] if scan_history else [])
            opportunities = [dict(row) for row in db.execute("SELECT * FROM opportunities ORDER BY slug, first_seen DESC")]
            history = [dict(row) for row in db.execute("SELECT * FROM historical_reports ORDER BY slug")]
            trending = [dict(row) for row in db.execute(PENDING_TRENDING_SQL, (day,))]
            pending_mail_items = len(trending) + len(db.execute(PENDING_OPPORTUNITIES_SQL, (day,)).fetchall())
            sent_pending = [dict(row) for row in db.execute("""
                SELECT di.item_id AS slug, MAX(di.day) AS sent_day,
                    COALESCE((SELECT t.description FROM trending t WHERE t.slug=di.item_id
                              ORDER BY t.day DESC LIMIT 1),'') AS description
                FROM delivery_items di JOIN deliveries d ON d.day=di.day
                LEFT JOIN repositories r ON r.slug=di.item_id
                LEFT JOIN trending sent ON sent.day=di.day AND sent.slug=di.item_id
                WHERE di.kind='repo' AND d.status='sent'
                  AND COALESCE(r.followed,0)=0 AND COALESCE(r.ignored,0)=0
                GROUP BY di.item_id ORDER BY sent_day DESC, MIN(sent.position), di.item_id
            """)]
            delivery = db.execute("SELECT * FROM deliveries WHERE day=?", (day,)).fetchone()
        return {"day": day, "trending": trending, "sent_pending": sent_pending,
                "repositories": repos, "ignored": ignored,
                "opportunities": opportunities, "scan": dict(scan) if scan else None,
                "latest_scan": dict(latest) if latest else None, "runs": runs, "history": history,
                "scan_history": scan_history, "run_history": run_history,
                "missing_days": missing_days,
                "delivery": dict(delivery) if delivery else None,
                "pending_mail_items": pending_mail_items}

    def _save_report(self, day: str, slug: str, outcome: ReviewOutcome) -> tuple[str, str]:
        folder = self.reports / day / slug.replace("/", "__")
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        report_path = folder / "report.md"
        progress_path = folder / "progress.md"
        if outcome.report:
            report_path.write_text(outcome.report, encoding="utf-8")
        if outcome.progress:
            progress_path.write_text(outcome.progress, encoding="utf-8")
        return (str(report_path.relative_to(self.root)) if outcome.report else "",
                str(progress_path.relative_to(self.root)) if outcome.progress else "")

    def import_history(self, source: Path) -> int:
        names = {"nightly-labs/openbot": "nightly-labs-openbot", "earendil-works/pi": "earendil-works-pi",
                 "volcengine/OpenViking": "OpenViking", "bytedance/deer-flow": "deer-flow"}
        sources = {slug: source / f"PR_HINT_REPORT_{name}.md" for slug, name in names.items()}
        for path in sources.values():
            if not path.is_file():
                raise FileNotFoundError(path)
        total = 0
        with self.connect() as db:
            for slug, path in sources.items():
                report = path.read_text(encoding="utf-8")
                match = re.search(r"20\d\d-\d\d-\d\d", report[:5000])
                report_day = match.group(0) if match else date.fromtimestamp(path.stat().st_mtime).isoformat()
                folder = self.reports / "historical" / slug.replace("/", "__")
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination = folder / "report.md"
                destination.write_text(report, encoding="utf-8")
                db.execute("INSERT OR IGNORE INTO historical_reports(slug,report_day,report_path) VALUES (?,?,?)",
                           (slug, report_day, str(destination.relative_to(self.root))))
                for candidate in extract_historical_candidates(report):
                    item_id = opportunity_id(candidate.url)
                    cursor = db.execute("INSERT OR IGNORE INTO opportunities(id,slug,title,url,reason,kind,status,pending_recheck,historical,first_seen,last_seen) VALUES (?,?,?,?,?,?,'current',1,1,?,?)",
                                        (item_id, slug, candidate.title, candidate.url, candidate.reason, candidate.kind, report_day, report_day))
                    total += cursor.rowcount
        return total

    def backup(self, target: Path) -> Path:
        target = target.expanduser().resolve()
        if target.is_relative_to(self.root):
            raise ValueError("备份目录必须位于运行数据目录之外")
        if target.exists():
            raise FileExistsError(target)
        staging = target.with_name(target.name + ".partial")
        if staging.exists():
            raise FileExistsError(staging)
        staging.mkdir(parents=True, mode=0o700)
        try:
            with self.connect() as src, sqlite3.connect(staging / "reposcout.db") as dst:
                src.backup(dst)
            if self.reports.exists():
                shutil.copytree(self.reports, staging / "reports")
            manifest = {}
            for path in staging.rglob("*"):
                if path.is_file():
                    manifest[str(path.relative_to(staging))] = hashlib.sha256(path.read_bytes()).hexdigest()
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            verify_backup(staging)
            staging.rename(target)
            return target
        except Exception:
            shutil.rmtree(staging)
            raise


def verify_backup(path: Path) -> None:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    actual = {str(item.relative_to(path)) for item in path.rglob("*") if item.is_file() and item.name != "manifest.json"}
    if actual != set(manifest):
        raise ValueError("备份文件清单与实际内容不一致")
    for name, digest in manifest.items():
        raw_item = path / name
        item = raw_item.resolve()
        if not item.is_relative_to(path.resolve()) or raw_item.is_symlink():
            raise ValueError(f"备份路径不安全: {name}")
        if hashlib.sha256(item.read_bytes()).hexdigest() != digest:
            raise ValueError(f"备份校验失败: {name}")
    with sqlite3.connect(path / "reposcout.db") as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("备份数据库 integrity_check 失败")


def restore_backup(source: Path, target: Path) -> None:
    verify_backup(source)
    target = target.expanduser().resolve()
    if target.is_relative_to(source.resolve()):
        raise ValueError("恢复目标不能位于备份目录内")
    if target.exists():
        raise FileExistsError("恢复目标必须不存在；现有数据未更改")
    staging = target.with_name(target.name + ".partial")
    if staging.exists():
        raise FileExistsError(staging)
    shutil.copytree(source, staging, ignore=shutil.ignore_patterns("manifest.json"))
    staging.rename(target)


def extract_historical_candidates(report: str) -> list[Candidate]:
    """Import only links from the report's concise recommendation area."""
    section = report.split("## 总结", 1)[-1].split("\n## ", 1)[0]
    candidates = []
    seen = set()
    pattern = r"\[([^\]]+)\]\((https://github\.com/[^)]+/(?:issues|pull)/\d+)\)"
    for line in section.splitlines():
        numbered = bool(re.match(r"^\s*\d+\.\s", line))
        if not numbered and not ("主推荐" in line or "本轮找到" in line):
            continue
        links = re.findall(pattern, line)
        if numbered:
            links = links[:1]  # Later links in the same point are supporting evidence.
        for title, url in links:
            try:
                item_id = opportunity_id(url)
            except ValueError:
                continue
            if item_id not in seen:
                candidates.append(Candidate(title=title, url=url, reason="历史报告，待重新核验"))
                seen.add(item_id)
    return candidates[:4]


def _timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return moment.astimezone(ZONE).isoformat()


def run_day(store: Store, trending_reader: TrendingReader, reviewer: ReviewRunner,
            moment: datetime, catch_up: bool = False, deadline: datetime | None = None) -> dict:
    """One idempotent daily run; failed repositories do not block the others."""
    moment = moment.astimezone(ZONE)
    day = moment.date().isoformat()
    with store.connect() as db:
        db.execute("UPDATE repo_runs SET state='incomplete', error='运行中断，已跨日' WHERE day<? AND state IN ('pending','running')", (day,))
        db.execute("UPDATE scans SET state='partial', finished_at=? WHERE day<? AND state='running'",
                   (_timestamp(moment), day))
        existing = db.execute("SELECT * FROM scans WHERE day=?", (day,)).fetchone()
        delivery_started = db.execute("SELECT 1 FROM deliveries WHERE day=?", (day,)).fetchone() is not None
        if existing and existing["state"] in ("completed", "partial") and (existing["trending_state"] != "failed" or delivery_started):
            return store.view(day)
        if not existing:
            db.execute("INSERT INTO scans(day,started_at,catch_up,state,trending_state) VALUES (?,?,?,'running','pending')",
                       (day, _timestamp(moment), int(catch_up)))
            slugs = [row[0] for row in db.execute("SELECT slug FROM repositories WHERE followed=1 ORDER BY added_at,slug")]
            db.executemany("INSERT INTO repo_runs(day,slug,state) VALUES (?,?,'pending')", ((day, slug) for slug in slugs))
        elif existing["state"] == "running":
            db.execute("UPDATE repo_runs SET state='incomplete', error='进程中断；本日不重复运行' WHERE day=? AND state='running'", (day,))
        trending_state = db.execute("SELECT trending_state FROM scans WHERE day=?", (day,)).fetchone()[0]
    # 同日重试失败的榜单，不重复已完成的仓库审查。
    if trending_state in ("pending", "failed"):
        try:
            snapshot = trending_reader()
            with store.connect() as db:
                db.executemany("INSERT OR REPLACE INTO trending(day,position,slug,description) VALUES (?,?,?,?)",
                               ((day, index, repo_slug(slug), desc) for index, (slug, desc) in enumerate(snapshot)))
                # 扫描时固定当天最多十个名额；发送或用户取舍后不能补入第十一个。
                selected = db.execute(ELIGIBLE_TRENDING_SQL, (day,)).fetchall()
                db.executemany("INSERT INTO recommendation_items(day,slug) VALUES (?,?)",
                               ((day, row["slug"]) for row in selected))
                db.execute("UPDATE scans SET trending_state='completed', trending_error='' WHERE day=?", (day,))
        except Exception as exc:
            with store.connect() as db:
                db.execute("UPDATE scans SET trending_state='failed', trending_error=? WHERE day=?", (f"{type(exc).__name__}: {exc}", day))
    with store.connect() as db:
        pending = [row[0] for row in db.execute("SELECT slug FROM repo_runs WHERE day=? AND state='pending' ORDER BY slug", (day,))]
    for slug in pending:
        if deadline and now_cn() >= deadline:
            with store.connect() as db:
                db.execute("UPDATE repo_runs SET state='incomplete', error='当日审查窗口已结束；未开始' WHERE day=? AND state='pending'", (day,))
            break
        with store.connect() as db:
            db.execute("UPDATE repo_runs SET state='running', started_at=? WHERE day=? AND slug=?", (_timestamp(now_cn()), day, slug))
        try:
            outcome = reviewer(slug, day)
        except Exception as exc:
            outcome = ReviewOutcome(state="failed", error=f"{type(exc).__name__}: {exc}")
        state = outcome.state if outcome.state in ("completed", "failed", "incomplete") else "failed"
        if state == "completed" and (not outcome.report or not outcome.progress or not outcome.cutoff or len(outcome.candidates) > 4):
            state = "incomplete"
            outcome = ReviewOutcome(state, outcome.candidates, outcome.report, outcome.progress,
                                    outcome.cutoff, "报告、进度、截止时间或四项主推荐范围未满足完整审查要求")
        if state == "completed":
            try:
                for candidate in outcome.candidates:
                    opportunity_id(candidate.url, candidate.identity)
            except ValueError as exc:
                state = "incomplete"
                outcome = ReviewOutcome(state, outcome.candidates, outcome.report, outcome.progress,
                                        outcome.cutoff, f"机会标识或证据链接无效: {exc}")
        report_path, progress_path = store._save_report(day, slug, outcome)
        with store.connect() as db:
            db.execute("""UPDATE repo_runs SET state=?, finished_at=?, report_path=?, progress_path=?, cutoff=?, error=?
                          WHERE day=? AND slug=?""",
                       (state, _timestamp(now_cn()), report_path, progress_path, outcome.cutoff, outcome.error, day, slug))
            if state == "completed":
                for candidate in outcome.candidates:
                    item_id = opportunity_id(candidate.url, candidate.identity)
                    db.execute("""INSERT INTO opportunities(id,slug,title,url,reason,kind,first_seen,last_seen)
                                  VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                                  title=excluded.title, reason=excluded.reason, kind=excluded.kind,
                                  last_seen=excluded.last_seen, pending_recheck=0""",
                               (item_id, slug, candidate.title, candidate.url, candidate.reason,
                                candidate.kind, day, day))
    with store.connect() as db:
        failures = db.execute("SELECT COUNT(*) FROM repo_runs WHERE day=? AND state!='completed'", (day,)).fetchone()[0]
        trending_failed = db.execute("SELECT trending_state!='completed' FROM scans WHERE day=?", (day,)).fetchone()[0]
        db.execute("UPDATE scans SET state=?, finished_at=? WHERE day=?",
                   ("partial" if failures or trending_failed else "completed", _timestamp(now_cn()), day))
    return store.view(day)


def prepare_delivery(store: Store, day: str) -> tuple[str, str, str] | None:
    """Freeze one day's pending content before SMTP so retries use the same message."""
    with store.connect() as db:
        existing = db.execute("SELECT * FROM deliveries WHERE day=?", (day,)).fetchone()
        if existing:
            if existing["status"] in ("sent", "sending", "uncertain"):
                return None
            return (existing["subject"], existing["body"], existing["message_id"])
        scan = db.execute("SELECT state FROM scans WHERE day=?", (day,)).fetchone()
        if not scan or scan[0] not in ("completed", "partial"):
            return None
        repos = db.execute(PENDING_TRENDING_SQL, (day,)).fetchall()
        items = db.execute(PENDING_OPPORTUNITIES_SQL, (day,)).fetchall()
        if not repos and not items:
            return None
        lines = ["新仓库", ""]
        for row in repos:
            lines.extend((f"• {row['slug']}", row["description"] or "今日 GitHub Trending 入榜仓库",
                          f"https://github.com/{row['slug']}", ""))
        if not repos:
            lines.extend(("本日无新仓库。", ""))
        lines.extend(("新 PR 机会", ""))
        last_slug = ""
        for row in items:
            if row["slug"] != last_slug:
                lines.append(row["slug"])
                last_slug = row["slug"]
            lines.extend((f"• {row['title']}", row["reason"], row["url"], ""))
        if not items:
            lines.append("本日无新机会。")
        body = "\n".join(lines).strip() + "\n"
        subject = f"RepoScout 日报 · {day}"
        message_id = f"<reposcout.{day}.{uuid4().hex}@localhost>"
        db.execute("INSERT INTO deliveries(day,status,message_id,subject,body) VALUES (?,'pending',?,?,?)",
                   (day, message_id, subject, body))
        db.executemany("INSERT INTO delivery_items VALUES (?,'repo',?)", ((day, row["slug"]) for row in repos))
        db.executemany("INSERT INTO delivery_items VALUES (?,'opportunity',?)", ((day, row["id"]) for row in items))
        return subject, body, message_id


class DefinitiveMailError(Exception):
    """SMTP rejected before accepting the message; retry is safe."""


def deliver(store: Store, sender: MailSender, moment: datetime, scan_day: str | None = None) -> str:
    moment = moment.astimezone(ZONE)
    day = scan_day or moment.date().isoformat()
    if moment < datetime.combine(date.fromisoformat(day), time(18), tzinfo=ZONE):
        return "before_send_window"
    prepared = prepare_delivery(store, day)
    if not prepared:
        return "nothing_pending"
    subject, body, message_id = prepared
    with store.connect() as db:
        db.execute("UPDATE deliveries SET status='sending', error='' WHERE day=?", (day,))
    try:
        sender(subject, body, message_id)
    except DefinitiveMailError as exc:
        with store.connect() as db:
            db.execute("UPDATE deliveries SET status='failed', error=? WHERE day=?", (f"{type(exc).__name__}: {exc}", day))
        return "failed"
    except Exception as exc:
        with store.connect() as db:
            db.execute("UPDATE deliveries SET status='uncertain', error=? WHERE day=?", (f"{type(exc).__name__}: {exc}", day))
        return "uncertain"
    with store.connect() as db:
        db.execute("UPDATE deliveries SET status='sent', sent_at=? WHERE day=?", (_timestamp(now_cn()), day))
    return "sent"


def reconcile_delivery(store: Store, received: Callable[[str], bool], day: str) -> str:
    """Resolve an interrupted/ambiguous SMTP attempt without resending it."""
    with store.connect() as db:
        row = db.execute("SELECT status,message_id FROM deliveries WHERE day=?", (day,)).fetchone()
        if not row or row["status"] not in ("sending", "uncertain"):
            return "nothing_to_reconcile"
        message_id = row["message_id"]
    if not received(message_id):
        with store.connect() as db:
            db.execute("UPDATE deliveries SET status='uncertain', error='IMAP 未查到原邮件；仍需人工核对' WHERE day=?", (day,))
        return "not_found_still_uncertain"
    with store.connect() as db:
        db.execute("UPDATE deliveries SET status='sent', sent_at=?, error='' WHERE day=?",
                   (_timestamp(now_cn()), day))
    return "confirmed_sent"


def tick(store: Store, trending_reader: TrendingReader, reviewer: ReviewRunner,
         sender: MailSender, moment: datetime, catch_up: bool = False,
         finished_at: Callable[[], datetime] = now_cn,
         deadline: datetime | None = None) -> str:
    moment = moment.astimezone(ZONE)
    if moment.time() < time(13):
        return "before_scan_window"
    run_day(store, trending_reader, reviewer, moment, catch_up, deadline)
    completed_at = finished_at()
    # 邮件只发一封：若审查拖到 18:00 后，先重试失败的榜单，再冻结邮件内容。
    if moment.time() < time(18) and completed_at.date() == moment.date() and completed_at.time() >= time(18):
        with store.connect() as db:
            trending_failed = db.execute("SELECT trending_state='failed' FROM scans WHERE day=?", (moment.date().isoformat(),)).fetchone()[0]
        if trending_failed:
            run_day(store, trending_reader, reviewer, moment, catch_up, deadline)
    with store.connect() as db:
        failed_days = [row[0] for row in db.execute("SELECT day FROM deliveries WHERE day<? AND status='failed' ORDER BY day", (moment.date().isoformat(),))]
    retry_results = [deliver(store, sender, completed_at, day) for day in failed_days]
    current_result = deliver(store, sender, completed_at, moment.date().isoformat())
    if current_result != "nothing_pending":
        return current_result
    if "failed" in retry_results:
        return "previous_delivery_failed"
    if "sent" in retry_results:
        return "previous_delivery_retried"
    return current_result
