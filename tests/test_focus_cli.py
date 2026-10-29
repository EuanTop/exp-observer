"""Portable conversation leases and remote jobs retain facts across delivery failures."""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_capture as capture_fixtures
from tests import test_delivery_status as delivery_fixtures
cli = capture_fixtures.cli
working_directory = capture_fixtures.working_directory
from backend.recovery import Recovery


class ClientBodyLimitTests(unittest.TestCase):
    def test_oversized_encoded_bodies_fail_before_network_without_rewriting(self):
        client = cli.Client('http://127.0.0.1:4317')
        cases = [('/api/projects/study/batch', {'operations': [{'op': 'run.add', 'data': {'metrics': {'native': 'x' * (8 * 1024 * 1024)}}}]}),
                 ('/api/projects/study/artifacts', {'title': '研究' * (350 * 1024)}),
                 ('/api/import', {'original': 'x' * (2 * 1024 * 1024)}),
                 ('/api/projects/study/batch/other', {'original': 'x' * (2 * 1024 * 1024)})]
        for route, body in cases:
            with self.subTest(route=route), patch.object(cli, 'urlopen', side_effect=AssertionError('Oversized upload opened a connection')):
                frozen = copy.deepcopy(body)
                with self.assertRaises(cli.ClientError) as raised:
                    client.request(route, body)
                self.assertEqual(raised.exception.code, 'body_too_large')
                self.assertEqual(raised.exception.status, 413)
                self.assertEqual(body, frozen)


class FocusCliTests(unittest.TestCase):
    setUp = capture_fixtures.CaptureTests.setUp
    invoke = capture_fixtures.CaptureTests.invoke

    def test_three_mib_batch_passes_client_preflight_and_preserves_native_metrics(self):
        metrics = {'rawSummary': {'text': 'x' * (3 * 1024 * 1024)}}
        operations = [{'op': 'run.add', 'data': {'id': 'run-large-native', 'nodeId': 'a',
                       'status': 'completed', 'metrics': metrics}}]
        retained = self.client.apply('study', operations, request_id='large-native')
        self.assertEqual(retained['runs'][0]['metrics'], metrics)
        self.assertEqual(operations[0]['data']['metrics'], metrics)

    def focus_snapshot(self):
        return self.client.request('/api/projects/study/focus')

    def receipts(self):
        return [(path, cli.read_queue_task(path)) for path in
                (self.root / '.exp-observer-runs' / 'outbox').glob('*.json')]

    def test_multiple_conversations_and_multi_node_focus_end_independently(self):
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'b', 'title': 'Other question'}}]})
        revision = self.store.get_project('study')['revision']
        _, first = self.invoke('focus', '--project', 'study', '--owner', 'chat-one', '--node', 'a', '--node', 'b')
        _, second = self.invoke('focus', '--project', 'study', '--owner', 'chat-two', '--node', 'b')
        self.assertFalse(first['pending'])
        self.assertFalse(second['pending'])
        self.assertEqual([session['state'] for session in self.focus_snapshot()['sessions']], ['active', 'active'])
        self.invoke('unfocus', '--project', 'study', '--owner', 'chat-one')
        states = {session['ownerId']: session['state'] for session in self.focus_snapshot()['sessions']}
        self.assertEqual(states, {'chat-one': 'ended', 'chat-two': 'active'})
        self.assertEqual(self.store.get_project('study')['revision'], revision)
        _, fresh = self.invoke('focus', '--project', 'study', '--owner', 'chat-one', '--node', 'a')
        self.assertNotEqual(first['leaseId'], fresh['leaseId'])

    def test_offline_start_heartbeat_end_replay_preserves_timestamps(self):
        offline = cli.Client(self.url)
        offline.request = lambda *a, **kw: (_ for _ in ()).throw(cli.ClientError('offline', code='unavailable'))
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with patch.object(cli, 'next_focus_stamp', return_value=old):
            self.invoke('focus', '--project', 'study', '--owner', 'chat-old', '--node', 'a', client=offline)
        frozen = copy.deepcopy(next(task for _, task in self.receipts() if task.get('kind') == 'focus')['focus'])
        self.invoke('sync', '--project', 'study')
        session = self.focus_snapshot()['sessions'][0]
        self.assertEqual(session['state'], 'stale')
        self.assertEqual(session['lastSeenAt'], cli.datetime.fromisoformat(old).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
        self.assertEqual(next(task for _, task in self.receipts() if task.get('kind') == 'focus')['focus'], frozen)
        self.invoke('focus', '--project', 'study', '--owner', 'chat-old', '--node', 'a', client=offline)
        self.invoke('unfocus', '--project', 'study', '--owner', 'chat-old', client=offline)
        self.invoke('sync', '--project', 'study')
        self.assertEqual(self.focus_snapshot()['sessions'][0]['state'], 'ended')
        self.invoke('sync', '--project', 'study')
        self.assertEqual(self.focus_snapshot()['sessions'][0]['state'], 'ended')

    def test_writes_heartbeat_joined_conversation_without_moving_selected_nodes(self):
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'chat-retained'}):
            self.invoke('focus', '--project', 'study', '--node', 'a')
            original = self.focus_snapshot()['sessions'][0]
            association = next((self.root / '.exp-observer-runs' / 'focus').glob('*.json'))
            state = json.loads(association.read_text())
            state['observedAt'] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            cli.save_task(association, state)
            self.invoke('record', '--project', 'study', '--title', 'An incidental finding')
            refreshed = self.focus_snapshot()['sessions'][0]
            self.assertEqual(refreshed['nodeIds'], ['a'])
            self.assertGreater(refreshed['lastSeenAt'], original['lastSeenAt'])
            self.invoke('unfocus', '--project', 'study')
            receipt_count = len(self.receipts())
            self.invoke('record', '--project', 'study', '--title', 'Another independent finding')
            self.assertEqual(len(self.receipts()), receipt_count + 1)
            self.assertEqual(self.focus_snapshot()['sessions'][0]['state'], 'ended')

    def test_offline_focus_can_end_before_a_missing_node_arrives(self):
        offline = cli.Client(self.url)
        offline.request = lambda *a, **kw: (_ for _ in ()).throw(cli.ClientError('offline', code='unavailable'))
        self.invoke('focus', '--project', 'study', '--owner', 'chat-pending', '--node', 'node-missing', client=offline)
        _, ending = self.invoke('unfocus', '--project', 'study', '--owner', 'chat-pending', client=offline)
        _, repeated = self.invoke('unfocus', '--project', 'study', '--owner', 'chat-pending', client=offline)
        self.assertTrue(ending['pending'])
        self.assertTrue(repeated['pending'])
        self.invoke('sync', '--project', 'study')
        self.assertEqual(self.focus_snapshot()['sessions'][0]['state'], 'ended')
        self.assertTrue(all(task['state'] == 'synced' for _, task in self.receipts()))
        self.assertEqual([node['id'] for node in self.store.get_project('study')['nodes']], ['a'])

    def test_background_superseded_focus_never_opens_local_associations(self):
        self.invoke('focus', '--project', 'study', '--owner', 'chat-scoped', '--node', 'a')
        start_path, original = next((path, task) for path, task in self.receipts() if task['focus']['action'] == 'start')
        self.invoke('unfocus', '--project', 'study', '--owner', 'chat-scoped')
        original['state'] = 'ready'
        cli.save_task(start_path, original)
        scoped = cli.Client(self.url, queue_root=self.root)
        with patch.object(cli, 'focus_location', side_effect=AssertionError('Background touched an unscoped association')):
            result = cli.sync_focus(scoped, start_path, original)
        self.assertFalse(result['pending'])
        self.assertTrue(result['superseded'])

    def test_blocked_focus_does_not_hold_up_another_conversation(self):
        self.invoke('focus', '--project', 'study', '--owner', 'chat-blocked', '--node', 'node-missing')
        _, healthy = self.invoke('focus', '--project', 'study', '--owner', 'chat-healthy', '--node', 'a')
        self.assertFalse(healthy['pending'])
        self.assertEqual(self.focus_snapshot()['sessions'][0]['ownerId'], 'chat-healthy')

    def test_explicit_host_owner_environment_precedes_codex_marker(self):
        with patch.dict(os.environ, {'EXP_OBSERVER_OWNER_ID': 'host-conversation', 'CODEX_THREAD_ID': 'codex-conversation'}):
            _, joined = self.invoke('focus', '--project', 'study', '--node', 'a')
            self.assertEqual(joined['ownerId'], 'host-conversation')
            _, explicit = self.invoke('focus', '--project', 'study', '--owner', 'explicit-owner')
            self.assertEqual(explicit['ownerId'], 'explicit-owner')

    def test_ascii_exact_title_resolves_from_remote_without_local_context(self):
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'node-benchmark', 'title': 'Benchmark'}}]})
        _, result = self.invoke('focus', '--project', 'study', '--owner', 'chat-title', '--node', 'Benchmark')
        self.assertFalse(result['pending'])
        self.assertEqual(result['nodeIds'], ['node-benchmark'])

    def test_local_status_is_network_free_with_focus_receipts(self):
        self.invoke('focus', '--project', 'study', '--owner', 'chat-status', '--node', 'a')
        with patch.object(self.client, 'request', side_effect=AssertionError('status contacted server')):
            _, status = self.invoke('status', '--project', 'study')
        self.assertFalse(status['transportChecked'])
        self.assertEqual(status['pendingCount'], 0)

    def test_remote_task_retains_original_lifecycle_without_completing_question(self):
        _, started = self.invoke('task', 'start', '--project', 'study', '--node', 'a', '--title', 'Cloud training',
                                 '--task-ref', 'job-42', '--remote-identity', 'gpu-host',
                                 '--started-at', '2026-01-01T00:00:00Z', '--request-id', 'remote-job')
        self.assertFalse(started['pending'])
        _, done = self.invoke('task', 'update', '--project', 'study', '--run', started['runId'],
                              '--status', 'completed', '--finished-at', '2026-01-01T02:00:00Z', '--duration-ms', '7200000')
        self.assertFalse(done['pending'])
        project = self.store.get_project('study')
        self.assertEqual(project['nodes'][0]['status'], 'proposed')
        run = next(run for run in project['runs'] if run['id'] == started['runId'])
        self.assertEqual(run['durationMs'], 7200000)
        self.assertTrue(run['configuration']['externalTask'])
        with self.assertRaisesRegex(cli.ClientError, 'actual --finished-at'):
            self.invoke('task', 'update', '--project', 'study', '--run', started['runId'], '--status', 'failed')

    def test_remote_metrics_retry_keeps_original_file_values_and_actual_owner(self):
        _, started = self.invoke('task', 'start', '--project', 'study', '--node', 'a', '--title', 'Remote job',
                                 '--task-ref', 'job-frozen', '--remote-identity', 'gpu', '--started-at', '2026-01-01T00:00:00Z')
        metrics = self.root / 'metrics.json'
        metrics.write_text('{"loss":0.4}', encoding='utf-8')
        offline = cli.Client(self.url)
        offline.request = lambda *a, **kw: (_ for _ in ()).throw(cli.ClientError('offline', code='unavailable'))
        arguments = ('task', 'update', '--project', 'study', '--run', started['runId'], '--metrics-file', str(metrics), '--request-id', 'frozen-metrics')
        _, pending = self.invoke(*arguments, client=offline)
        self.assertEqual(pending['nodeId'], 'a')
        metrics.write_text('{"loss":999}', encoding='utf-8')
        self.invoke(*arguments)
        self.assertEqual(self.store.get_project('study')['runs'][0]['metrics'], {'loss': 0.4})

    def test_offline_remote_lifecycle_replays_start_before_terminal_update(self):
        offline = cli.Client(self.url)
        offline.request = lambda *a, **kw: (_ for _ in ()).throw(cli.ClientError('offline', code='unavailable'))
        _, started = self.invoke('task', 'start', '--project', 'study', '--node', 'a', '--title', 'Remote',
                                 '--task-ref', 'job-1', '--remote-identity', 'gpu', '--started-at', '2026-01-01T00:00:00Z', client=offline)
        self.invoke('task', 'update', '--project', 'study', '--run', started['runId'], '--status', 'completed',
                    '--finished-at', '2026-01-01T01:00:00Z', client=offline)
        self.invoke('sync', '--project', 'study')
        run = self.store.get_project('study')['runs'][0]
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['startedAt'], '2026-01-01T00:00:00Z')


class QueueDependencyTests(unittest.TestCase):
    setUp = delivery_fixtures.DeliveryStatusTests.setUp
    new_recovery = delivery_fixtures.DeliveryStatusTests.new_recovery
    capture = delivery_fixtures.DeliveryStatusTests.capture

    def test_retry_dependent_imports_exact_producer_first_without_mutating_payload(self):
        producer_path, producer = self.capture('record', '--project', 'study', '--title', 'Actual new diagnostic')
        dependent_path, dependent = self.capture('record', '--project', 'study', '--node', producer['nodeId'],
                                                   '--summary', 'A later correction')
        dependent_path = next(path for path in dependent_path.parent.glob('*.json')
                              if cli.read_queue_task(path).get('requestId') == dependent['requestId'])
        # Simulate old receipt failures: producer rejected, later update not_found.
        original = {path: copy.deepcopy(cli.read_queue_task(path)) for path in (producer_path, dependent_path)}
        task = cli.read_queue_task(dependent_path)
        task['delivery'] = {'attempts': 2500, 'lastError': {'code': 'not_found', 'message': 'Node not found'}}
        cli.save_task(dependent_path, task)
        status = self.recovery.delivery_status('study')
        item = next(item for item in status['items'] if item['requestId'] == dependent['requestId'])
        self.assertEqual(item['waitingFor'][0]['taskId'], original[producer_path]['taskId'])
        result = self.recovery.retry_delivery('study', task['taskId'])
        self.assertEqual(result['retriedCount'], 2)
        self.assertEqual(self.store.get_project('study')['nodes'][0]['summary'], 'A later correction')
        for path, frozen in original.items():
            healed = cli.read_queue_task(path)
            self.assertEqual(healed['operations'], frozen['operations'])
            self.assertEqual(healed['capturedAt'], frozen['capturedAt'])
            self.assertEqual(healed['requestId'], frozen['requestId'])
            self.assertEqual(healed['state'], 'synced')

    def test_not_found_background_retries_are_bounded(self):
        path, _ = self.capture('record', '--project', 'study', '--node', 'node-not-created', '--summary', 'Native correction')
        self.recovery.drain_once()
        first = cli.read_queue_task(path)
        self.assertEqual(first['delivery']['lastError']['code'], 'not_found')
        self.assertGreater(cli.local_timestamp(first['delivery']['nextAttemptAt']), __import__('time').time())
        for _ in range(4):
            self.recovery.drain_once()
        self.assertEqual(cli.read_queue_task(path)['delivery']['attempts'], first['delivery']['attempts'])


if __name__ == '__main__':
    unittest.main()
