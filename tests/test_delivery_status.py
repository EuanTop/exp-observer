"""Delivery visibility follows durable scoped receipts, not page-save state."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from backend.recovery import Recovery
from backend.server import Server
from backend.store import Store, StoreError
from tests.test_capture import cli, working_directory
from tests.test_recovery import held_project_lock


class DeliveryStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='delivery receipts ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.state = self.root / 'state'
        environment = patch.dict(os.environ, {'EXP_OBSERVER_STATE_DIR': str(self.state)})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Readable study'})
        self.store.add_workspace({'path': str(self.workspace)})
        self.server = Server(('127.0.0.1', 0), self.store)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = cli.Client(self.url, timeout=2)
        self.recovery = self.new_recovery()

    def new_recovery(self, **kwargs):
        recovery = Recovery(self.url, self.state, store=self.store, **kwargs)
        self.addCleanup(recovery.stop)
        self.server.recovery = recovery
        return recovery

    def capture(self, *arguments, cwd=None, url=None):
        client = cli.Client(url or self.url, timeout=0.01)
        client.request = lambda *args, **kwargs: (_ for _ in ()).throw(cli.ClientError('Offline', code='unavailable'))
        args = cli.parser().parse_args(['--url', client.url, *arguments])
        emitted = []
        directory = cwd or self.workspace
        with working_directory(directory), patch.object(cli, 'emit', side_effect=emitted.append):
            getattr(cli, args.command)(client, args)
        receipt = emitted[-1]
        path = next(path for path in (directory / '.exp-observer-runs' / 'outbox').glob('*.json')
                    if cli.read_queue_task(path).get('nodeId') == receipt['nodeId'])
        return path, receipt

    def blocked_record(self):
        path, receipt = self.capture('record', '--project', 'study', '--title', 'A real finding')
        task = cli.read_queue_task(path)
        task['delivery'] = {'attempts': 3, 'lastAttemptAt': '2026-10-26T02:00:00Z',
                            'lastError': {'code': 'not_found', 'message': 'Evidence reference was not found.'}}
        cli.save_task(path, task)
        return path, receipt

    def test_persisted_failures_survive_restart_and_get_does_not_mutate_receipts(self):
        path, receipt = self.blocked_record()
        before = {p: p.read_bytes() for p in path.parent.glob('*.json')}
        recovery = self.new_recovery()
        status = self.client.request('/api/projects/study/delivery-status')
        self.assertEqual(status['state'], 'blocked')
        item = next(item for item in status['items'] if item['nodeId'] == receipt['nodeId'])
        self.assertEqual(item['attempts'], 3)
        self.assertEqual(item['lastError']['code'], 'not_found')
        self.assertEqual(item['title'], 'A real finding')
        self.assertEqual(before, {p: p.read_bytes() for p in path.parent.glob('*.json')})
        self.assertEqual(recovery.delivery_status('study')['blockedCount'], 1)

    def test_unknown_is_not_synced_without_receipts_or_complete_discovery(self):
        self.assertEqual(self.recovery.delivery_status('study')['state'], 'unknown')
        path, _ = self.blocked_record()
        task = cli.read_queue_task(path)
        task['state'] = 'synced'
        cli.save_task(path, task)
        for plan in path.parent.glob('project-*.json'):
            task = cli.read_queue_task(plan)
            task['state'] = 'synced'
            cli.save_task(plan, task)
        incomplete = self.new_recovery(discovery_budget=0)
        status = incomplete.delivery_status('study')
        self.assertFalse(status['discoveryComplete'])
        self.assertEqual(status['state'], 'unknown')
        self.assertEqual(status['blockedCount'], 0)  # Old errors on acknowledged receipts are irrelevant.
        self.server.recovery = None
        unavailable = self.client.request('/api/projects/study/delivery-status')
        self.assertFalse(unavailable['available'])
        self.assertEqual(unavailable['state'], 'unknown')

    def test_retry_delivers_original_command_once_and_clears_blocked_state(self):
        count = self.workspace / 'count.txt'
        script = "from pathlib import Path; p=Path('count.txt'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); print('retained output')"
        path, receipt = self.capture('execute', '--project', 'study', '--title', 'Captured execution',
            '--request-id', 'only-once', '--', sys.executable, '-c', script)
        task = cli.read_queue_task(path)
        task['delivery'] = {'attempts': 1, 'lastAttemptAt': cli.stamp(),
                            'lastError': {'code': 'unavailable', 'message': 'Offline'}}
        cli.save_task(path, task)
        with patch('subprocess.Popen', side_effect=AssertionError('A delivery retry reran research')):
            result = self.client.request('/api/projects/study/delivery/retry', {'taskId': task['taskId']})
        self.assertEqual(result['retriedCount'], 1)
        self.assertEqual(result['deliveryStatus']['state'], 'synced')
        self.assertEqual(count.read_text(), '1')
        self.assertEqual(cli.read_queue_task(path)['state'], 'synced')
        self.assertIsNone(cli.read_queue_task(path)['delivery']['lastError'])
        project = self.store.get_project('study')
        self.assertEqual(len(project['runs']), 1)
        self.assertEqual(project['runs'][0]['nodeId'], receipt['nodeId'])
        self.assertEqual(len(project['artifacts']), 2)

    def test_missing_reference_backs_off_in_background_but_explicit_retry_is_immediate(self):
        path, _ = self.capture('event', '--project', 'study', '--question', 'Actual question?',
                               '--finding', 'Retained finding', '--evidence', 'node-upstream')
        self.recovery.drain_once()
        failed = cli.read_queue_task(path)
        self.assertEqual(failed['delivery']['lastError']['code'], 'invalid_reference')
        self.assertGreater(cli.local_timestamp(failed['delivery']['nextAttemptAt']), __import__('time').time())
        self.recovery.drain_once()
        self.assertEqual(cli.read_queue_task(path)['delivery']['attempts'], failed['delivery']['attempts'])
        self.assertEqual(self.recovery.delivery_status('study')['blockedCount'], 1)
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {
            'id': 'node-upstream', 'title': 'A genuine prerequisite'}}]})
        result = self.recovery.retry_delivery('study', failed['taskId'])
        self.assertEqual(result['retriedCount'], 1)
        healed = cli.read_queue_task(path)
        self.assertEqual(healed['state'], 'synced')
        self.assertEqual(healed['operations'], failed['operations'])
        self.assertIsNone(healed['delivery']['lastError'])
        self.assertIsNone(healed['delivery']['nextAttemptAt'])

    def test_interrupted_capture_is_visible_but_never_retried_and_live_lock_is_pending(self):
        path, _ = self.blocked_record()
        task = cli.read_queue_task(path)
        task['state'] = 'running'
        cli.save_task(path, task)
        self.assertEqual(self.recovery.delivery_status('study')['interruptedCount'], 1)
        with held_project_lock(path):
            status = self.recovery.delivery_status('study')
            item = next(item for item in status['items'] if item['taskId'] == task['taskId'])
            self.assertEqual(item['state'], 'pending')
        with patch.object(self.recovery, '_submit', side_effect=AssertionError('Interrupted task was submitted')):
            self.assertEqual(self.recovery.retry_delivery('study', task['taskId'])['retriedCount'], 0)

    def test_retry_cannot_name_paths_or_other_project_or_origin(self):
        path, _ = self.blocked_record()
        self.capture('record', '--project', 'other-study', '--title', 'Other project')
        self.capture('record', '--project', 'study', '--title', 'Other origin', url='http://127.0.0.1:1')
        status = self.recovery.delivery_status('study')
        self.assertEqual([item['title'] for item in status['items'] if item['nodeId']], ['A real finding'])
        with self.assertRaises(cli.ClientError) as error:
            self.client.request('/api/projects/study/delivery/retry', {'path': str(path)})
        self.assertEqual(error.exception.code, 'invalid_body')
        with self.assertRaises(StoreError) as error:
            self.recovery.retry_delivery('study', '../../outside.json')
        self.assertEqual(error.exception.code, 'not_found')
        with self.recovery.delivery_lock:
            with self.assertRaises(StoreError) as error:
                self.recovery.retry_delivery('study')
            self.assertEqual(error.exception.code, 'recovery_busy')

    def test_unenrolled_and_symlinked_receipts_are_not_visible_and_disabled_root_is_honored(self):
        path, _ = self.blocked_record()
        outside = self.root / 'outside'
        outside.mkdir()
        hidden, _ = self.capture('record', '--project', 'study', '--title', 'Outside workspace', cwd=outside)
        # A foreign queue is neither enrolled nor registered for this service.
        self.assertFalse(list((self.state / 'outboxes').glob('*.json')))
        (path.parent / 'linked.json').symlink_to(hidden)
        status = self.recovery.delivery_status('study')
        self.assertEqual([item['title'] for item in status['items'] if item['nodeId']], ['A real finding'])
        cli.register_outbox(path.parent, self.url)
        workspace = self.store.list_workspaces()[0]
        self.store.remove_workspace({'id': workspace['id']})
        status = self.recovery.delivery_status('study')
        self.assertFalse(status['available'])
        self.assertEqual(status['state'], 'unknown')

    def test_registered_queue_is_visible_after_restart_without_workspace_enrollment(self):
        outside = self.root / 'registered'
        outside.mkdir()
        path, receipt = self.capture('record', '--project', 'study', '--title', 'Registered receipt', cwd=outside)
        cli.register_outbox(path.parent, self.url)
        recovery = self.new_recovery()
        status = recovery.delivery_status('study')
        self.assertTrue(status['available'])
        self.assertIn(receipt['nodeId'], [item['nodeId'] for item in status['items']])
        # Registration itself never grants access through a symlinked outbox.
        alias = self.root / 'alias'
        alias.symlink_to(outside, target_is_directory=True)
        registration = next((self.state / 'outboxes').glob('*.json'))
        entry = json.loads(registration.read_text())
        entry['outbox'] = str(alias / '.exp-observer-runs' / 'outbox')
        registration.write_text(json.dumps(entry))
        self.assertEqual(self.new_recovery().delivery_status('study')['items'], [])

    def test_preflight_failure_is_persisted_on_scoped_receipt_without_touching_evidence(self):
        path, _ = self.blocked_record()
        task = cli.read_queue_task(path)
        outside = self.root / 'outside.txt'
        outside.write_text('must remain unchanged')
        task['artifacts'] = [{'path': str(outside)}]
        task['delivery'] = {'attempts': 0, 'lastError': None}
        cli.save_task(path, task)
        with patch('subprocess.Popen', side_effect=AssertionError('Preflight reran research')):
            result = self.recovery.retry_delivery('study', task['taskId'])
        self.assertEqual(result['deliveryStatus']['blockedCount'], 1)
        retained = cli.read_queue_task(path)
        self.assertEqual(retained['delivery']['attempts'], 1)
        self.assertIn('workspace scope', retained['delivery']['lastError']['message'])
        self.assertEqual(outside.read_text(), 'must remain unchanged')
        self.assertEqual(self.new_recovery().delivery_status('study')['blockedCount'], 1)
        before = path.read_bytes()
        with held_project_lock(path):
            self.recovery.retry_delivery('study', task['taskId'])
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
