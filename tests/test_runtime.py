"""Execution activity is a scoped lock observation, never a research disposition."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.recovery import Recovery, capture_lock_held
from backend.store import Store


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / 'research'
        self.workspace.mkdir()
        self.store = Store(self.root / 'store')
        self.store.create_project({'id': 'study', 'name': 'Study'})
        self.store.add_workspace({'path': str(self.workspace)})
        self.recovery = Recovery('http://127.0.0.1:4317', state_dir=self.root / 'registry', store=self.store)
        self.addCleanup(self.recovery.stop)
        self.recovery.host_usage = None
        self.path = self.workspace / '.exp-observer-runs' / 'outbox' / 'capture.json'
        self.path.parent.mkdir(parents=True)
        self.task = {'url': self.recovery.url, 'projectId': 'study', 'taskId': 'capture', 'nodeId': 'question',
                     'state': 'running', 'intent': {'command': 'execute'}, 'captureRoot': str(self.path.parent.parent),
                     'artifacts': []}
        self.path.write_text(json.dumps(self.task), encoding='utf-8')

    def discover(self):
        # Focus this check on discovery/liveness, without transport or usage imports.
        with patch.object(self.recovery, '_submit', return_value={'pending': True}):
            self.recovery.drain_once()

    def test_only_an_existing_held_executor_lock_is_live(self):
        before = set(self.root.rglob('*'))
        self.assertFalse(capture_lock_held(self.path.with_suffix('.lock')))
        self.assertEqual(before, set(self.root.rglob('*')))
        self.discover()
        self.assertEqual(self.recovery.runtime('study')['active'], [])
        with self.recovery.cli.task_lock(self.path):
            self.discover()
            first = self.recovery.runtime('study')
            self.assertEqual(first['active'], [{'id': 'capture', 'nodeId': 'question', 'source': 'local-executor'}])
            self.assertEqual(self.recovery.runtime('another-study')['active'], [])
            self.task['state'] = 'ready'
            self.path.write_text(json.dumps(self.task), encoding='utf-8')
            self.assertEqual(self.recovery.runtime('study')['active'], [])
            self.task['state'] = 'running'
            self.path.write_text(json.dumps(self.task), encoding='utf-8')
            self.assertEqual(len(self.recovery.runtime('study')['active']), 1)
        # Even a stale running record stops immediately after process lock release.
        self.assertEqual(self.recovery.runtime('study')['active'], [])
        self.assertEqual(self.store.get_project('study')['nodes'], [])

    def test_disconnect_expiry_and_wrong_origin_do_not_report_activity(self):
        with self.recovery.cli.task_lock(self.path):
            self.discover()
            self.assertEqual(len(self.recovery.runtime('study')['active']), 1)
            self.task['url'] = 'http://127.0.0.1:9999'
            self.path.write_text(json.dumps(self.task), encoding='utf-8')
            self.assertEqual(self.recovery.runtime('study')['active'], [])
            self.task['url'] = self.recovery.url
            self.path.write_text(json.dumps(self.task), encoding='utf-8')
            stamp, candidates = self.recovery.runtime_candidates
            self.recovery.runtime_candidates = (time.monotonic() - 11, candidates)
            self.assertEqual(self.recovery.runtime('study')['active'], [])
            self.recovery.runtime_candidates = (stamp, candidates)
            workspace = self.store.recovery_workspaces()['workspaces'][0]
            self.store.remove_workspace({'id': workspace['id']})
            self.assertEqual(self.recovery.runtime('study')['active'], [])

    def test_missing_or_symlink_lock_is_not_probed(self):
        with self.recovery.cli.task_lock(self.path):
            self.discover()
        lock = self.path.with_suffix('.lock')
        original = self.root / 'original.lock'
        lock.rename(original)
        try:
            lock.symlink_to(original)
        except OSError:
            self.skipTest('Symlinks unavailable on this host')
        with patch('backend.recovery.capture_lock_held', side_effect=AssertionError('Followed a symlink')):
            self.assertEqual(self.recovery.runtime('study')['active'], [])
