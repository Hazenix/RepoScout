import plistlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from reposcout.adapters import CodexReviewer, QQSender
from reposcout.cli import launchd_plists, wait_for_receipt
from reposcout.core import Store, ZONE, restore_backup, tick, verify_backup


class OperationsTest(unittest.TestCase):
    def test_mail_receipt_retries_temporary_imap_failure_within_deadline(self):
        moment = [0.0]
        attempts = []

        def received(message_id):
            attempts.append(message_id)
            if len(attempts) == 1:
                raise TimeoutError("temporary IMAP timeout")
            return len(attempts) == 3

        def sleep(seconds):
            moment[0] += seconds

        with patch('reposcout.cli.time_module.monotonic', side_effect=lambda: moment[0]), \
             patch('reposcout.cli.time_module.sleep', side_effect=sleep):
            self.assertTrue(wait_for_receipt(received, '<test@localhost>', timeout=12))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(moment[0], 10)

    def test_mail_receipt_stops_at_deadline(self):
        moment = [0.0]

        def sleep(seconds):
            moment[0] += seconds

        with patch('reposcout.cli.time_module.monotonic', side_effect=lambda: moment[0]), \
             patch('reposcout.cli.time_module.sleep', side_effect=sleep):
            self.assertFalse(wait_for_receipt(lambda _: False, '<test@localhost>', timeout=12))
        self.assertEqual(moment[0], 12)

    def test_mail_receipt_keeps_error_when_every_imap_query_fails(self):
        moment = [0.0]

        def fail(_):
            raise TimeoutError("IMAP connection timed out")

        def sleep(seconds):
            moment[0] += seconds

        with patch('reposcout.cli.time_module.monotonic', side_effect=lambda: moment[0]), \
             patch('reposcout.cli.time_module.sleep', side_effect=sleep):
            with self.assertRaisesRegex(RuntimeError, 'TimeoutError: IMAP connection timed out'):
                wait_for_receipt(fail, '<test@localhost>', timeout=6)
        self.assertEqual(moment[0], 6)

    def test_qq_receipt_uses_preserved_correlation_header(self):
        sent = []
        searches = []
        class SMTP:
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def login(self, *_): return None
            def send_message(self, message): sent.append(message)
        class IMAP:
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def login(self, *_): return None
            def select(self, *_ , **__): return 'OK', [b'1']
            def search(self, *args):
                searches.append(args)
                return 'OK', [b'42' if args == (None, 'HEADER', 'X-RepoScout-ID', '"reposcout.test.123@localhost"') else b'']
        sender = QQSender('example@qq.com')
        with patch.object(sender, '_authorization_code', return_value='placeholder'), \
             patch('reposcout.adapters.smtplib.SMTP_SSL', return_value=SMTP()), \
             patch('reposcout.adapters.imaplib.IMAP4_SSL', return_value=IMAP()):
            sender('测试', '正文', '<reposcout.test.123@localhost>')
            self.assertTrue(sender.received('<reposcout.test.123@localhost>'))
        self.assertEqual(sent[0]['X-RepoScout-ID'], 'reposcout.test.123@localhost')
        self.assertEqual(searches[-1][2], 'X-RepoScout-ID')

    def test_codex_adapter_invokes_pr_hint_with_fixed_scope_and_only_completed_output(self):
        with tempfile.TemporaryDirectory() as root:
            commands = []
            def fake_run(command, **kwargs):
                commands.append(command)
                if command[:3] == ['gh', 'auth', 'status']:
                    return subprocess.CompletedProcess(command, 0, '', '')
                folder = Path(command[command.index('-C') + 1])
                (folder / 'PR_HINT_REPORT_earendil-works-pi.md').write_text('完整报告', encoding='utf-8')
                (folder / 'PR_HINT_PROGRESS_earendil-works-pi.md').write_text('完整进度', encoding='utf-8')
                Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps({
                    'state':'completed', 'candidates':[], 'cutoff':'2026-11-06 18:00 CST', 'error':''
                }), encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, '', '')
            with patch('reposcout.adapters.subprocess.run', side_effect=fake_run):
                outcome = CodexReviewer(Path(root))('earendil-works/pi', '2026-11-06')
            self.assertEqual(outcome.state, 'completed')
            command = commands[1]
            self.assertEqual(command[command.index('-s') + 1], 'workspace-write')
            self.assertEqual(command[command.index('-c') + 1], 'sandbox_workspace_write.network_access=true')
            self.assertIn('$pr-hint', command[-1])
            self.assertIn('全量 GitHub 审查', command[-1])
            self.assertIn('feat > fix > refactor/perf', command[-1])
            self.assertIn('最多 4', command[-1])

    def test_launchd_has_startup_board_and_two_daily_times(self):
        searches = []
        def locate(name, path=None):
            searches.append(path)
            return {
                'codex': '/Applications/ChatGPT.app/Contents/MacOS/codex',
                'gh': '/opt/homebrew/bin/gh',
            }[name]
        with patch.dict(os.environ, {'PATH': '/tmp/codex-session:/usr/bin'}), \
             patch('reposcout.cli.shutil.which', side_effect=locate):
            jobs = {name: plistlib.loads(data) for name, data in launchd_plists(Path('/usr/bin/python3'), Path('/tmp/reposcout')).items()}
        self.assertEqual(set(jobs), {'board', 'startup', 'daily'})
        self.assertTrue(jobs['startup']['RunAtLoad'])
        self.assertTrue(jobs['board']['KeepAlive'])
        self.assertEqual(jobs['daily']['StartCalendarInterval'],
                         [{'Hour': 13, 'Minute': 0}, {'Hour': 18, 'Minute': 0}])
        launchd_path = jobs['daily']['EnvironmentVariables']['PATH']
        self.assertIn('/Applications/ChatGPT.app/Contents/MacOS', launchd_path)
        self.assertIn('/opt/homebrew/bin', launchd_path)
        self.assertNotIn('/tmp/codex-session', launchd_path)
        self.assertTrue(all(path and '/tmp/codex-session' not in path for path in searches))

    def test_launchd_keeps_symlink_entry_directory_for_upgrades(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            root = Path(root)
            stable = root / 'stable'
            version = root / 'version'
            stable.mkdir()
            version.mkdir()
            (version / 'gh').write_text('binary', encoding='utf-8')
            (stable / 'gh').symlink_to(version / 'gh')
            with patch('reposcout.cli.shutil.which', side_effect=lambda name, path=None: {
                'codex': '/Applications/ChatGPT.app/Contents/MacOS/codex',
                'gh': str(stable / 'gh'),
            }[name]):
                jobs = launchd_plists(Path('/usr/bin/python3'), root)
            path = plistlib.loads(jobs['daily'])['EnvironmentVariables']['PATH'].split(os.pathsep)
            self.assertIn(str(stable), path)
            self.assertNotIn(str(version), path)

    def test_before_thirteen_does_not_scan(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'data')
            result = tick(store, lambda: self.fail('trending too early'),
                          lambda slug, day: self.fail('review too early'),
                          lambda *args: self.fail('mail too early'),
                          datetime(2026, 11, 6, 12, 59, tzinfo=ZONE))
            self.assertEqual(result, 'before_scan_window')
            self.assertIsNone(store.view()['scan'])

    def test_backup_rejects_tampering_and_preserves_existing_target(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'data')
            backup = store.backup(Path(root) / 'backup')
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
            verify_backup(backup)
            existing = Path(root) / 'existing'
            existing.mkdir()
            marker = existing / 'user.txt'
            marker.write_text('keep', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                restore_backup(backup, existing)
            self.assertEqual(marker.read_text(encoding='utf-8'), 'keep')
            (backup / 'reposcout.db').write_bytes(b'broken')
            with self.assertRaises(ValueError):
                verify_backup(backup)


if __name__ == '__main__':
    unittest.main()
