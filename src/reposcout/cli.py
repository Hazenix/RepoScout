"""Local command entry point."""
from __future__ import annotations

import argparse
import fcntl
import os
import plistlib
import sys
import time as time_module
from contextlib import contextmanager
from datetime import time, timedelta
from pathlib import Path

from .adapters import CodexReviewer, QQSender, configure_keychain
from .core import Store, fetch_trending, now_cn, reconcile_delivery, restore_backup, tick, verify_backup
from .server import serve


def default_data_dir() -> Path:
    return Path(os.environ.get("REPOSCOUT_HOME", "~/Library/Application Support/RepoScout")).expanduser()


@contextmanager
def task_lock(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (data_dir / "task.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def launchd_plists(python: Path, data_dir: Path) -> dict[str, bytes]:
    common: dict[str, object] = {"EnvironmentVariables": {"PATH": os.environ.get("PATH", "/opt/homebrew/bin:/usr/bin:/bin")},
              "StandardOutPath": str(data_dir / "launchd.log"),
              "StandardErrorPath": str(data_dir / "launchd-error.log")}
    prefix = [str(python), "-m", "reposcout.cli", "--data-dir", str(data_dir)]
    jobs: dict[str, dict[str, object]] = {
        "board": {"Label": "dev.hazenix.reposcout.board", "ProgramArguments": prefix + ["serve"],
                  "RunAtLoad": True, "KeepAlive": True},
        "startup": {"Label": "dev.hazenix.reposcout.startup", "ProgramArguments": prefix + ["tick", "--startup"],
                    "RunAtLoad": True},
        "daily": {"Label": "dev.hazenix.reposcout.daily", "ProgramArguments": prefix + ["tick"],
                  "StartCalendarInterval": [{"Hour": 13, "Minute": 0}, {"Hour": 18, "Minute": 0}]},
    }
    return {name: plistlib.dumps(common | job) for name, job in jobs.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="RepoScout 本机看板")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    commands = parser.add_subparsers(dest="command", required=True)
    web = commands.add_parser("serve", help="启动本机看板")
    web.add_argument("--port", type=int, default=8765)
    task = commands.add_parser("tick", help="执行当天应做的扫描与投递")
    task.add_argument("--startup", action="store_true", help="标记开机补跑")
    imported = commands.add_parser("import-history", help="导入四个历史 pr-hint 报告")
    imported.add_argument("source", type=Path)
    mail = commands.add_parser("configure-mail", help="配置 QQ 邮箱和钥匙串")
    mail.add_argument("address")
    commands.add_parser("test-mail", help="发一封测试邮件并用 IMAP 核对收件")
    reconcile = commands.add_parser("reconcile-mail", help="核对中断的 SMTP 投递，不重复发信")
    reconcile.add_argument("day", help="日报日期 YYYY-MM-DD")
    backup = commands.add_parser("backup", help="生成并校验本机备份")
    backup.add_argument("target", type=Path)
    restore = commands.add_parser("restore", help="恢复到空目录")
    restore.add_argument("source", type=Path)
    restore.add_argument("target", type=Path)
    verify = commands.add_parser("verify-backup", help="校验备份")
    verify.add_argument("source", type=Path)
    plist = commands.add_parser("write-launchd", help="生成三个 launchd 配置，不安装")
    plist.add_argument("target", type=Path)
    args = parser.parse_args()
    if args.command == "restore":
        restore_backup(args.source, args.target)
        print(f"已恢复到 {args.target}")
        return
    if args.command == "verify-backup":
        verify_backup(args.source)
        print("备份校验通过")
        return
    store = Store(args.data_dir)
    if args.command == "serve":
        serve(store, args.port)
    elif args.command == "tick":
        with task_lock(store.root):
            moment = now_cn()
            today = store.view()["scan"]
            catch_up = bool(not today and moment.time() >= time(13) and
                            (args.startup or moment.time() > time(13, 1)))
            result = tick(store, fetch_trending, CodexReviewer(store.root),
                          QQSender(store.get_setting("mail_address")), moment, catch_up,
                          deadline=moment.replace(hour=13, minute=0, second=0, microsecond=0) + timedelta(days=1))
            print(result)
    elif args.command == "import-history":
        with task_lock(store.root):
            print(f"导入 {store.import_history(args.source)} 个历史机会")
    elif args.command == "configure-mail":
        configure_keychain(args.address)
        store.set_setting("mail_address", args.address)
        print("邮箱地址与钥匙串已配置")
    elif args.command == "test-mail":
        sender = QQSender(store.get_setting("mail_address"))
        message_id = f"<reposcout.test.{int(time_module.time())}@localhost>"
        sender("RepoScout 测试邮件", "这是一封本机集成检查邮件。\n", message_id)
        for _ in range(6):
            if sender.received(message_id):
                print("SMTP 已接受，IMAP 已核对收件")
                break
            time_module.sleep(5)
        else:
            raise RuntimeError("SMTP 已接受，但 30 秒内 IMAP 未查到测试邮件；收件未验证")
    elif args.command == "reconcile-mail":
        sender = QQSender(store.get_setting("mail_address"))
        print(reconcile_delivery(store, sender.received, args.day))
    elif args.command == "backup":
        with task_lock(store.root):
            print(store.backup(args.target))
    elif args.command == "write-launchd":
        if args.target.exists():
            raise FileExistsError(args.target)
        args.target.mkdir(parents=True)
        for name, content in launchd_plists(Path(sys.executable), store.root).items():
            (args.target / f"dev.hazenix.reposcout.{name}.plist").write_bytes(content)
        print(args.target)


if __name__ == "__main__":
    main()
