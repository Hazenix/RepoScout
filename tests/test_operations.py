import plistlib
import json
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from reposcout.adapters import CodexReviewer
from reposcout.cli import launchd_plists
from reposcout.core import Store, ZONE, restore_backup, tick, verify_backup


class OperationsTest(unittest.TestCase):
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
            self.assertIn('$pr-hint', command[-1])
            self.assertIn('全量 GitHub 审查', command[-1])
            self.assertIn('feat > fix > refactor/perf', command[-1])
            self.assertIn('最多 4', command[-1])

    def test_launchd_has_startup_board_and_two_daily_times(self):
        jobs = {name: plistlib.loads(data) for name, data in launchd_plists(Path('/usr/bin/python3'), Path('/tmp/reposcout')).items()}
        self.assertEqual(set(jobs), {'board', 'startup', 'daily'})
        self.assertTrue(jobs['startup']['RunAtLoad'])
        self.assertTrue(jobs['board']['KeepAlive'])
        self.assertEqual(jobs['daily']['StartCalendarInterval'],
                         [{'Hour': 13, 'Minute': 0}, {'Hour': 18, 'Minute': 0}])

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
