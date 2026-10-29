"""Offline onboarding and application recovery use isolated user state and research data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend.recovery import Recovery
from backend.codex_usage import CodexSessionAdapter
from backend.host_usage import HostUsageImporter
from backend.server import Server
from backend.store import Store, StoreError
from tests.test_capture import cli, working_directory


@contextmanager
def held_project_lock(path):
    held, release = threading.Event(), threading.Event()
    def hold():
        with cli.task_lock(path):
            held.set()
            release.wait(5)
    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    try:
        if not held.wait(2):
            raise AssertionError('The competing project lock was not acquired')
        yield
    finally:
        release.set()
        thread.join(timeout=2)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='exp recovery 研究 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state = self.root / 'state'
        environment = patch.dict(os.environ, {'EXP_OBSERVER_STATE_DIR': str(self.state)})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = Store(self.root / 'data')
        self.store.add_workspace({'path': str(self.root)})
        self.server = Server(('127.0.0.1', 0), self.store, recovery=True, recovery_interval=0.08)
        self.addCleanup(self.server.server_close)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = cli.Client(self.url, timeout=0.5)

    def offline(self, url=None):
        client = cli.Client(url or self.url, timeout=0.1)
        def fail(*args, **kwargs):
            raise cli.ClientError('Service offline', code='unavailable')
        client.request = fail
        return client

    def invoke(self, *arguments, client=None, cwd=None):
        client = client or self.client
        args = cli.parser().parse_args(['--url', client.url, *arguments])
        results = []
        with working_directory(cwd or self.root), patch.object(cli, 'emit', side_effect=results.append):
            code = getattr(cli, args.command)(client, args)
        return code, results[-1]

    def start(self, automatic=True):
        self.server.recovery_enabled = automatic
        thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except StoreError as exc:
                if exc.code != 'not_found':
                    raise
            threading.Event().wait(0.02)
        self.fail('Automatic recovery did not reach the expected state')

    def task_paths(self, cwd=None):
        return list(((cwd or self.root) / '.exp-observer-runs' / 'outbox').glob('*.json'))

    def read_tasks(self, cwd=None):
        return [json.loads(path.read_text(encoding='utf-8')) for path in self.task_paths(cwd)]

    def test_old_windows_session_imports_through_recovery_and_http_without_double_counting(self):
        self.start(automatic=False)
        _, receipt = self.invoke('record', '--project', 'windows-study', '--title', 'Measured finding')
        path = next(p for p in self.task_paths() if not p.name.startswith('project-'))
        task = cli.read_queue_task(path)
        sid = '11111111-2222-3333-4444-555555555555'
        task['hostUsage'] = {'host': 'codex', 'threadId': sid}
        cli.save_task(path, task)
        at = datetime.fromisoformat(task['capturedAt'].replace('Z', '+00:00'))
        old = self.root / 'codex' / 'sessions' / '2026' / '01' / '01'
        old.mkdir(parents=True)
        events = []
        def emit(kind, payload, offset=0):
            events.append({'type': kind, 'timestamp': (at + timedelta(seconds=offset)).isoformat(), 'payload': payload})
        emit('session_meta', {'id': sid, 'model_provider': 'openai'}, -2)
        emit('turn_context', {'model': 'measured-model'}, -2)
        emit('event_msg', {'type': 'task_started'}, -2)
        emit('token_usage_record', {'response_id': 'native-response', 'usage': {
            'input_tokens': 100, 'output_tokens': 7, 'cached_input_tokens': 80}}, -1)
        command = ('& "C:\\Program Files\\Python\\python.exe" -X utf8 -B '
                   '"C:\\Agent Skills\\exp_observer.py" --url ' + self.url + ' record --project windows-study')
        emit('response_item', {'type': 'function_call', 'name': 'exec_command', 'call_id': 'record',
                              'arguments': json.dumps({'cmd': command})})
        emit('response_item', {'type': 'function_call_output', 'call_id': 'record', 'output': json.dumps(receipt)})
        emit('event_msg', {'type': 'task_complete'}, 1)
        (old / ('rollout-test-' + sid + '.jsonl')).write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
        recovery = Recovery(self.url, self.state, store=self.store)
        adapter = CodexSessionAdapter([self.root / 'codex'], url=self.url)
        recovery.host_usage = HostUsageImporter(self.store, [adapter], interval=0, url=self.url)
        self.server.recovery = recovery
        for _ in range(2):
            recovery.drain_once()
        project = self.client.project('windows-study')
        self.assertEqual(len(project['usageRecords']), 1)
        row = project['usageRecords'][0]
        self.assertEqual((row['inputTokens'], row['outputTokens'], row['cacheReadTokens']), (100, 7, 80))
        self.assertEqual(row['nodeId'], receipt['nodeId'])
        self.assertEqual(project['runs'], [])
        status = self.client.request('/api/projects/windows-study/usage-status')['adapters'][0]
        self.assertEqual((status['state'], status['matchedReceipts'], status['collectedRecords']), ('collected', 1, 1))

    def test_background_acknowledgement_replaces_stale_pending_without_http(self):
        _, original = self.invoke('record', '--project', 'authoritative', '--title', 'Actual finding',
                                  '--request-id', 'authoritative', client=self.offline())
        path = next(path for path in self.task_paths() if not path.name.startswith('project-'))
        stale = cli.read_queue_task(path)
        self.assertEqual(stale['state'], 'ready')
        self.start(automatic=False)
        Recovery(self.url, self.state, store=self.store).drain_once()
        authoritative = cli.read_queue_task(path)
        self.assertEqual(authoritative['state'], 'synced')
        authoritative['recordingWarnings'].append('Historical HTTP permission error before background reception')
        cli.save_task(path, authoritative)
        before = path.read_bytes()
        with patch.object(cli.Client, 'request', side_effect=AssertionError('Acknowledged task attempted HTTP')), \
             patch.object(cli, 'save_task', side_effect=AssertionError('Acknowledged task was rewritten')):
            receipt = cli.sync_task(self.client, path, stale)
            _, result = self.invoke('status', '--project', 'authoritative', client=self.client)
        self.assertTrue(original['pending'])
        self.assertEqual(receipt, cli.task_result(authoritative))
        self.assertFalse(receipt['pending'])
        self.assertEqual((result['syncedCount'], result['pendingCount']), (1, 0))
        self.assertEqual(result['deliveryState'], 'synced')
        self.assertFalse(result['transportChecked'])
        self.assertIn('Historical HTTP permission error', result['records'][0]['recordingWarnings'][0])
        self.assertEqual(path.read_bytes(), before)

    def test_stale_queue_identity_conflict_never_submits_or_overwrites(self):
        self.invoke('record', '--project', 'identity', '--title', 'Original question', client=self.offline())
        path = next(path for path in self.task_paths() if not path.name.startswith('project-'))
        stale = cli.read_queue_task(path)
        current = cli.read_queue_task(path)
        current['requestId'] = 'different-identity'
        current['state'] = 'synced'
        cli.save_task(path, current)
        before = path.read_bytes()
        with patch.object(cli.Client, 'request', side_effect=AssertionError('Identity conflict attempted HTTP')):
            with self.assertRaises(cli.ClientError) as raised:
                cli.sync_task(self.client, path, stale)
        self.assertEqual(raised.exception.code, 'queue_identity_conflict')
        self.assertEqual(path.read_bytes(), before)

    def test_init_offline_freezes_metadata_and_keeps_existing_remote_project(self):
        arguments = ('init', '--name', 'Original project', '--description', 'Original description', '--source-root', 'results')
        code, first = self.invoke(*arguments, client=self.offline())
        self.assertEqual(code, 0)
        self.assertTrue(first['pending'])
        self.assertEqual(first['availability'], 'unavailable')
        _, repeated = self.invoke(*arguments, client=self.offline())
        self.assertEqual((first['id'], first['preparedAt']), (repeated['id'], repeated['preparedAt']))
        _, changed = self.invoke('init', '--name', 'Original project', '--description', 'Changed', client=self.offline())
        self.assertEqual(changed['description'], 'Original description')
        self.assertIn('original plan', changed['recordingWarnings'][-1])
        other = self.root / 'other workspace'
        other.mkdir()
        _, different_workspace = self.invoke(*arguments, cwd=other, client=self.offline())
        self.assertNotEqual(first['id'], different_workspace['id'])
        # Repeated offline retries now retain bounded delivery backoff. Advance
        # only that mutable retry clock, without sleeping or editing frozen work.
        for path in self.root.rglob('project-*.json'):
            plan = cli.read_queue_task(path)
            if plan.get('delivery', {}).get('nextAttemptAt'):
                plan['delivery']['nextAttemptAt'] = '2000-01-01T00:00:00Z'
                cli.save_task(path, plan)
        self.start()
        self.wait_for(lambda: len(self.store.list_projects()) == 2)
        self.server.recovery.stop()
        project = self.store.get_project(first['id'])
        self.assertEqual(project['description'], 'Original description')
        self.assertEqual(project['sourceRoots'], [str(self.root / 'results')])
        self.store.batch(first['id'], {'operations': [{'op': 'project.update', 'data': {'name': 'Remote name', 'description': 'Remote edit'}}]})
        before = self.store.get_project(first['id'])
        _, online = self.invoke(*arguments)
        self.assertEqual(online['id'], first['id'])
        self.assertEqual(online['name'], 'Remote name')
        self.assertFalse(online['pending'])
        self.assertEqual(self.store.get_project(first['id']), before)

    def test_lost_project_creation_response_is_recovered_without_duplicate_or_overwrite(self):
        self.start(automatic=False)
        client = cli.Client(self.url, timeout=0.5)
        request = client.request
        def lose_creation_response(route, body=None, raw=False):
            result = request(route, body, raw)
            if route == '/api/projects' and body is not None:
                raise cli.ClientError('Creation response lost', code='unavailable')
            return result
        client.request = lose_creation_response
        code, result = self.invoke('init', '--id', 'lost-create', '--name', 'Frozen', client=client)
        self.assertEqual(code, 0)
        self.assertTrue(result['pending'])
        self.assertEqual(len(self.store.list_projects()), 1)
        self.store.batch('lost-create', {'operations': [{'op': 'project.update', 'data': {'description': 'Changed remotely'}}]})
        before = self.store.get_project('lost-create')
        recovery = Recovery(self.url, self.state, store=self.store)
        self.assertTrue(recovery.drain_once())
        self.assertEqual(self.store.get_project('lost-create'), before)
        self.assertEqual(recovery.drain_once(), [])
        self.assertEqual(self.read_tasks()[0]['state'], 'synced')

    def test_record_without_init_recovers_snapshots_and_causal_links_but_never_fakes_references(self):
        metrics = {'nested': {'scores': [1, 2, None], 'ok': True}}
        (self.root / 'metrics.json').write_text(json.dumps(metrics), encoding='utf-8')
        source = self.root / 'evidence.txt'
        source.write_text('frozen evidence', encoding='utf-8')
        _, first = self.invoke('record', '--project', 'no-init', '--title', 'First finding', '--metrics-file', 'metrics.json',
            '--artifact', 'evidence.txt', '--request-id', 'first', client=self.offline())
        _, second = self.invoke('record', '--project', 'no-init', '--title', 'Next finding', '--after', first['nodeId'],
            '--request-id', 'second', client=self.offline())
        _, invalid = self.invoke('record', '--project', 'no-init', '--title', 'Unknown predecessor', '--after', 'foreign-node',
            '--request-id', 'invalid', client=self.offline())
        self.assertTrue(first['pending'])
        source.unlink()
        (self.root / 'metrics.json').write_text('{"changed":true}', encoding='utf-8')
        self.start()
        self.wait_for(lambda: len(self.store.get_project('no-init')['nodes']) == 2
                      and len(self.store.get_project('no-init')['artifacts']) == 1)
        self.server.recovery.stop()
        project = self.store.get_project('no-init')
        self.assertEqual(project['runs'][0]['metrics'], metrics)
        self.assertIsNone(project['runs'][0]['startedAt'])
        self.assertEqual(project['runs'][0]['capturedAt'], first['capturedAt'])
        self.assertEqual(self.store.artifact_content('no-init', project['artifacts'][0]['id'])[0], b'frozen evidence')
        self.assertEqual([(e['source'], e['target']) for e in project['edges']], [(first['nodeId'], second['nodeId'])])
        self.assertNotIn(invalid['nodeId'], [node['id'] for node in project['nodes']])
        pending = next(task for task in self.read_tasks() if task.get('nodeId') == invalid['nodeId'])
        self.assertEqual(pending['state'], 'ready')

    def test_background_recovery_never_reruns_execute_and_keeps_original_execution_times(self):
        script = "from pathlib import Path; p=Path('count.txt'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); print('actual output')"
        arguments = ('execute', '--project', 'execution', '--title', 'Fresh experiment',
                     '--request-id', 'execute-once', '--', sys.executable, '-c', script)
        code, original = self.invoke(*arguments, client=self.offline())
        self.assertEqual(code, 0)
        self.assertTrue(original['pending'])
        with patch('subprocess.Popen', side_effect=AssertionError('Recovery attempted to execute an experiment')):
            self.start()
            self.wait_for(lambda: len(self.store.get_project('execution')['artifacts']) == 2)
            # HTTP persistence can precede the worker's local receipt and unlock.
            # Finish that recovery before testing a subsequent command retry.
            self.server.recovery.stop()
            code, repeated = self.invoke(*arguments)
        self.assertEqual(code, 0)
        self.assertFalse(repeated['pending'])
        self.assertEqual((self.root / 'count.txt').read_text(), '1')
        run = self.store.get_project('execution')['runs'][0]
        self.assertEqual(run['nodeId'], original['nodeId'])
        self.assertEqual(len(self.store.get_project('execution')['nodes']), 1)
        self.assertEqual((run['startedAt'], run['finishedAt']), (original['startedAt'], original['finishedAt']))
        self.assertEqual(run['metrics']['wallTimeMs'], original['wallTimeMs'])

    def test_only_registered_matching_loopback_outboxes_are_recovered(self):
        _, included = self.invoke('record', '--project', 'included', '--title', 'Included', client=self.offline())
        unregistered = self.root / 'unregistered'
        unregistered.mkdir()
        self.invoke('record', '--project', 'not-registered', '--title', 'Unregistered', cwd=unregistered, client=self.offline())
        for path in (self.state / 'outboxes').glob('*.json'):
            entry = json.loads(path.read_text(encoding='utf-8'))
            if Path(entry['outbox']).is_relative_to(unregistered):
                path.unlink()
        other_url = f'http://127.0.0.1:{1 if self.server.server_port != 1 else 2}'
        self.invoke('record', '--project', 'other-server', '--title', 'Other server', client=self.offline(other_url))
        _, remote = self.invoke('record', '--project', 'remote', '--title', 'Manual only',
                                client=self.offline('https://example.invalid'))
        self.assertTrue(remote['pending'])
        self.assertIn('loopback HTTP', cli.register_outbox(self.root / '.exp-observer-runs' / 'outbox', 'https://example.invalid'))
        cli.register_outbox(self.root / '.exp-observer-runs' / 'outbox', self.url)
        self.start(automatic=False)
        Recovery(self.url, self.state).drain_once()
        self.assertEqual([project['id'] for project in self.store.list_projects()], ['included'])
        self.assertTrue(all(task['state'] != 'synced' for task in self.read_tasks(unregistered)))
        self.assertEqual(self.store.get_project('included')['nodes'][0]['id'], included['nodeId'])

    def test_localhost_queue_recovers_through_the_bound_service_without_dns(self):
        localhost_url = f'http://localhost:{self.server.server_port}'
        _, result = self.invoke('record', '--project', 'alias', '--title', 'Localhost record', client=self.offline(localhost_url))
        self.assertTrue(result['pending'])
        self.start()
        self.wait_for(lambda: len(self.store.get_project('alias')['nodes']) == 1)
        self.assertEqual(self.store.get_project('alias')['nodes'][0]['id'], result['nodeId'])

    def test_automatic_recovery_never_follows_redirects_to_another_origin(self):
        redirected_requests = []
        class Target(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                redirected_requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')
        target = ThreadingHTTPServer(('127.0.0.1', 0), Target)
        self.addCleanup(target.server_close)
        target_thread = threading.Thread(target=target.serve_forever, daemon=True)
        target_thread.start()
        self.addCleanup(target_thread.join)
        self.addCleanup(target.shutdown)
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{target.server_port}/redirected')
                self.end_headers()
        redirect = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        self.addCleanup(redirect.server_close)
        redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
        redirect_thread.start()
        self.addCleanup(redirect_thread.join)
        self.addCleanup(redirect.shutdown)
        url = f'http://127.0.0.1:{redirect.server_port}'
        self.invoke('record', '--project', 'redirect', '--title', 'Keep local', client=self.offline(url))
        recovery = Recovery(url, self.state, store=self.store)
        results = recovery.drain_once()
        self.assertTrue(results)
        self.assertTrue(all(result['pending'] for result in results))
        self.assertTrue(any('does not follow HTTP redirects' in warning for result in results for warning in result.get('recordingWarnings', [])))
        self.assertEqual(redirected_requests, [])

    def test_concurrent_registry_entries_and_drains_do_not_lose_or_duplicate_records(self):
        directories = [self.root / f'workspace-{index}' for index in range(8)]
        with ThreadPoolExecutor(8) as pool:
            warnings = list(pool.map(lambda path: cli.register_outbox(path, self.url), directories))
        self.assertEqual(warnings, [None] * 8)
        entries = [json.loads(path.read_text(encoding='utf-8')) for path in (self.state / 'outboxes').glob('*.json')]
        self.assertCountEqual([entry['outbox'] for entry in entries], [str(path) for path in directories])
        for index in range(2):
            self.invoke('record', '--project', 'concurrent', '--title', f'Finding {index}', '--request-id', str(index), client=self.offline())
        self.start(automatic=False)
        workers = [Recovery(self.url, self.state, store=self.store), Recovery(self.url, self.state, store=self.store)]
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda worker: worker.drain_once(), workers))
        workers[0].drain_once()
        self.assertEqual(len(self.store.get_project('concurrent')['nodes']), 2)
        self.assertEqual(len(self.store.list_projects()), 1)
        self.assertTrue(all(task['state'] == 'synced' for task in self.read_tasks()))

    def test_offline_context_marks_cache_and_summarizes_large_local_results(self):
        self.store.create_project({'id': 'context', 'name': 'Context'})
        self.store.batch('context', {'operations': [{'op': 'node.add', 'data': {'id': 'a', 'title': 'Previously observed'}}]})
        self.start(automatic=False)
        code, fresh = self.invoke('context', '--project', 'context')
        self.assertEqual(code, 0)
        self.assertEqual(fresh['availability'], 'available')
        (self.root / 'large.json').write_text(json.dumps({'samples': list(range(60000))}), encoding='utf-8')
        summary = 'Finding that changes the next research step. ' + 'details ' * 100
        self.invoke('record', '--project', 'context', '--title', 'Pending result', '--summary', summary,
                    '--metrics-file', 'large.json', client=self.offline())
        code, offline = self.invoke('context', '--project', 'context', client=self.offline())
        self.assertEqual(code, 0)
        self.assertEqual(offline['availability'], 'unavailable')
        self.assertTrue(offline['pending'])
        self.assertNotIn('nodes', offline)
        self.assertEqual(offline['cachedRemote']['cachedAt'], fresh['fetchedAt'])
        self.assertEqual(offline['cachedRemote']['context']['nodes'][0]['title'], 'Previously observed')
        self.assertEqual(offline['localPendingCount'], 1)
        pending_node = offline['localPending'][0]['operations'][0]
        self.assertEqual(pending_node['summary'], summary[:512])
        self.assertTrue(pending_node['summaryTruncated'])
        self.assertLess(len(json.dumps(offline['localPending'])), 2000)
        self.assertNotIn('metrics', json.dumps(offline['localPending']))
        code, rejected = self.invoke('context', '--project', 'context', '--node', 'missing')
        self.assertEqual(code, 1)
        self.assertEqual((rejected['availability'], rejected['remoteError']['status']), ('error', 404))
        code, unknown = self.invoke('context', '--project', 'unknown', client=self.offline())
        self.assertEqual(code, 0)
        self.assertIsNone(unknown['cachedRemote'])
        self.assertIsNone(unknown['localProject'])
        self.assertFalse(unknown['pending'])
        self.invoke('init', '--id', 'pending-project', '--name', 'Prepared', client=self.offline())
        code, pending = self.invoke('context', '--project', 'pending-project')
        self.assertEqual(code, 0)
        self.assertEqual((pending['availability'], pending['remoteError']['code']), ('pending', 'not_found'))

    def test_native_notes_are_compact_by_default_and_complete_in_scoped_local_context(self):
        notes = '完整分析与边界条件。\r\n' * 1000
        conclusion = '在本次条件下有效，但不能外推。' * 100
        _, root = self.invoke('record', '--project', 'native-context', '--title', '主研究问题',
            '--kind', 'question', '--notes', notes, '--conclusion', conclusion, client=self.offline())
        _, child = self.invoke('record', '--project', 'native-context', '--title', '子问题',
            '--parent', root['nodeId'], '--notes', '子问题完整分析', client=self.offline())
        _, other = self.invoke('record', '--project', 'native-context', '--title', '另一个方向',
            '--independent', '--notes', '其他方向的完整分析', client=self.offline())
        root_task = next(task for task in self.read_tasks() if task.get('nodeId') == root['nodeId'])
        # Keep enough later summary-only updates to push the original notes out
        # of the 20-receipt window. These are local fixture snapshots only.
        for index in range(21):
            revision = deepcopy(root_task)
            revision.update({'taskId': f'revision-{index}', 'requestId': f'revision-{index}',
                             'capturedAt': f'9999-01-01T00:00:00.{index:03d}Z'})
            revision['operations'] = [{'op': 'node.update', 'data': {
                'id': root['nodeId'], 'summary': f'同一问题的补充证据 {index}'}}]
            cli.save_task(self.root / '.exp-observer-runs' / 'outbox' / f'revision-{index}.json', revision)
        _, compact = self.invoke('context', '--project', 'native-context', client=self.offline())
        compact_root = next(node for node in compact['localNodes'] if node['id'] == root['nodeId'])
        self.assertTrue(compact_root['hasNotes'])
        self.assertNotIn('notes', compact_root)
        self.assertEqual(compact_root['kind'], 'question')
        self.assertEqual(compact_root['conclusion'], conclusion[:512])
        self.assertTrue(compact_root['conclusionTruncated'])
        self.assertNotIn(notes, json.dumps(compact, ensure_ascii=False))
        self.assertEqual(len(compact['localRecords']), 20)
        _, scoped = self.invoke('context', '--project', 'native-context', '--node', root['nodeId'], client=self.offline())
        scoped_nodes = {node['id']: node for node in scoped['localNodes']}
        self.assertEqual(set(scoped_nodes), {root['nodeId'], child['nodeId']})
        self.assertEqual(scoped_nodes[root['nodeId']]['notes'], notes)
        self.assertEqual(scoped_nodes[child['nodeId']]['notes'], '子问题完整分析')
        self.assertNotIn('其他方向的完整分析', json.dumps(scoped, ensure_ascii=False))
        self.assertNotIn(other['nodeId'], scoped_nodes)
        # Available remote context must expose the same native pending view.
        with patch.object(self.client, 'request', return_value={'projectId': 'native-context', 'nodes': []}):
            _, online = self.invoke('context', '--project', 'native-context', '--node', root['nodeId'])
        self.assertEqual(online['availability'], 'available')
        pending_nodes = {node['id']: node for node in online['localPendingNodes']}
        self.assertEqual(pending_nodes[root['nodeId']]['notes'], notes)

    def test_worker_does_not_reparse_acknowledged_large_tasks_until_the_file_changes(self):
        (self.root / 'large.json').write_text(json.dumps({'samples': list(range(60000))}), encoding='utf-8')
        self.invoke('record', '--project', 'cached', '--title', 'Large result', '--metrics-file', 'large.json', client=self.offline())
        self.start(automatic=False)
        recovery = Recovery(self.url, self.state, store=self.store)
        recovery.drain_once()
        capture_path = next(path for path in self.task_paths() if not path.name.startswith('project-'))
        loads = json.loads
        with patch.object(recovery.cli.json, 'loads', wraps=loads) as decode:
            self.assertEqual(recovery.drain_once(), [])
            self.assertFalse(any(len(call.args[0]) > 50000 for call in decode.call_args_list))
            task = loads(capture_path.read_text(encoding='utf-8'))
            task['recordingWarnings'].append('Local receipt changed')
            cli.save_task(capture_path, task)
            recovery.drain_once()
            self.assertTrue(any(len(call.args[0]) > 50000 for call in decode.call_args_list))

    def test_inaccessible_registry_does_not_affect_local_capture_or_enrolled_recovery(self):
        blocked_state = self.root / 'blocked-state'
        blocked_state.write_text('A file prevents creation of the registry directory')
        with patch.dict(os.environ, {'EXP_OBSERVER_STATE_DIR': str(blocked_state)}), \
                patch.object(cli, 'register_outbox', side_effect=AssertionError('Capture tried to write outside its workspace')):
            code, initialized = self.invoke('init', '--id', 'retained', '--name', 'Retained', client=self.offline())
            self.assertEqual(code, 0)
            self.assertTrue(initialized['pending'])
            _, captured = self.invoke('record', '--project', 'retained', '--title', 'Durable finding', client=self.offline())
            self.assertTrue(captured['pending'])
            self.assertEqual(len(self.read_tasks()), 2)
            self.start()
            self.wait_for(lambda: len(self.store.get_project('retained')['nodes']) == 1)
        self.assertEqual(self.store.get_project('retained')['nodes'][0]['title'], 'Durable finding')

    def test_malformed_queue_entry_does_not_block_context_or_other_records(self):
        self.invoke('record', '--project', 'healthy', '--title', 'Healthy record', client=self.offline())
        outbox = self.root / '.exp-observer-runs' / 'outbox'
        (outbox / 'malformed.json').write_text('[]', encoding='utf-8')
        cli.register_outbox(outbox, self.url)
        (self.state / 'outboxes' / '000-malformed.json').write_text('[]', encoding='utf-8')
        code, context = self.invoke('context', '--project', 'healthy', client=self.offline())
        self.assertEqual(code, 0)
        self.assertEqual(context['localPendingCount'], 1)
        self.start(automatic=False)
        results = Recovery(self.url, self.state, store=self.store).drain_once()
        self.assertEqual(self.store.get_project('healthy')['nodes'][0]['title'], 'Healthy record')
        malformed = next(result for result in results if result.get('task') == 'malformed.json')
        self.assertTrue(malformed['pending'])
        self.assertIn('require an object', malformed['recordingWarnings'][0])
        registration = next(result for result in results if result.get('registryEntry') == '000-malformed.json')
        self.assertIn('must be an object', registration['recordingWarnings'][0])

    def test_automatic_recovery_origin_rejects_invalid_ports_and_nonlocal_urls(self):
        for url in ('http://127.0.0.1:0', 'http://localhost:65536', 'https://localhost:4317',
                    'http://example.invalid:4317', 'http://user@localhost:4317', 'http://localhost:4317/path'):
            with self.subTest(url=url):
                self.assertIsNone(cli.loopback_origin(url))
        self.assertEqual(cli.loopback_origin('http://localhost:4317'), cli.loopback_origin('http://127.0.0.1:4317'))
        self.assertNotEqual(cli.loopback_origin('http://[::1]:4317'), cli.loopback_origin('http://127.0.0.1:4317'))

    def test_interrupted_execute_creates_paused_node_and_preserves_cancelled_run(self):
        self.start(automatic=False)
        cancelled = {'exitCode': 130, 'wallTimeMs': 12.5, 'status': 'cancelled'}
        with patch.object(cli, 'run_command', return_value=(cancelled, None)):
            code, result = self.invoke('execute', '--project', 'interrupted', '--title', 'Interrupted command',
                                       '--', sys.executable, '-c', 'pass')
        self.assertEqual(code, 130)
        self.assertEqual(result['status'], 'cancelled')
        project = self.store.get_project('interrupted')
        self.assertEqual((project['nodes'][0]['status'], project['nodes'][0]['pauseReason']), ('paused', 'Command interrupted'))
        self.assertEqual((project['runs'][0]['status'], project['runs'][0]['metrics']['exitCode']), ('cancelled', 130))

    def test_init_reacquire_busy_returns_frozen_pending_without_more_io(self):
        outbox = self.root / '.exp-observer-runs' / 'outbox'
        metadata = {'id': 'busy-gap', 'name': 'Frozen name', 'description': 'Frozen description', 'sourceRoots': []}
        path, plan = cli.prepare_project(outbox, self.url, metadata)
        original_bytes = path.read_bytes()
        prepare, read_text = cli.prepare_project, Path.read_text
        gap_started = False
        with ExitStack() as held:
            def compete_after_preparation(*args, **kwargs):
                nonlocal gap_started
                result = prepare(*args, **kwargs)
                held.enter_context(held_project_lock(result[0]))
                gap_started = True
                return result
            def reject_gap_read(file, *args, **kwargs):
                if gap_started:
                    raise AssertionError('Init reread a file after recovery acquired the plan lock')
                return read_text(file, *args, **kwargs)
            with patch.object(cli, 'prepare_project', side_effect=compete_after_preparation), \
                    patch.object(Path, 'read_text', reject_gap_read), \
                    patch.object(cli, 'save_task') as write, \
                    patch.object(self.client, 'request') as request:
                code, result = self.invoke('init', '--id', 'busy-gap', '--name', 'New proposal', '--description', 'New description')
                write.assert_not_called()
                request.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual((result['pending'], result['availability']), (True, 'pending'))
        self.assertEqual((result['name'], result['description'], result['preparedAt']),
                         ('Frozen name', 'Frozen description', plan['preparedAt']))
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_init_prepare_busy_preserves_readable_frozen_metadata(self):
        outbox = self.root / '.exp-observer-runs' / 'outbox'
        metadata = {'id': 'busy-prepare', 'name': 'Frozen', 'description': 'Original', 'sourceRoots': []}
        path, plan = cli.prepare_project(outbox, self.url, metadata)
        original_bytes = path.read_bytes()
        with held_project_lock(path), patch.object(cli, 'save_task') as write, patch.object(self.client, 'request') as request:
            code, result = self.invoke('init', '--id', 'busy-prepare', '--name', 'Changed')
            write.assert_not_called()
            request.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual((result['id'], result['pending'], result['availability']), ('busy-prepare', True, 'pending'))
        self.assertEqual((result['name'], result['description'], result['preparedAt']), ('Frozen', 'Original', plan['preparedAt']))
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_init_prepare_busy_windows_read_denied_does_not_claim_unconfirmed_queue(self):
        outbox = self.root / '.exp-observer-runs' / 'outbox'
        path, _ = cli.prepare_project(outbox, self.url,
            {'id': 'busy-windows', 'name': 'Frozen', 'description': 'Original', 'sourceRoots': []})
        original_bytes, read_text = path.read_bytes(), Path.read_text
        def denied_read(file, *args, **kwargs):
            if file == path:
                raise PermissionError('Windows replacement is in progress')
            return read_text(file, *args, **kwargs)
        with held_project_lock(path), patch.object(Path, 'read_text', denied_read), \
                patch.object(cli, 'save_task') as write, patch.object(self.client, 'request') as request:
            code, result = self.invoke('init', '--id', 'busy-windows', '--name', 'Unconfirmed proposal')
            write.assert_not_called()
            request.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual((result['id'], result['pending'], result['availability']), ('busy-windows', False, 'unavailable'))
        for unknown in ('name', 'description', 'preparedAt'):
            self.assertNotIn(unknown, result)
        self.assertIn('could not be confirmed', result['recordingWarnings'][0])
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_init_prepare_busy_without_valid_plan_does_not_claim_durable_queue(self):
        outbox = self.root / '.exp-observer-runs' / 'outbox'
        path = cli.project_plan_path(outbox, self.url, 'not-prepared')
        for content in (None, '[]'):
            with self.subTest(content=content), held_project_lock(path):
                if content is not None:
                    path.write_text(content, encoding='utf-8')
                with patch.object(cli, 'save_task') as write, patch.object(self.client, 'request') as request:
                    code, result = self.invoke('init', '--id', 'not-prepared', '--name', 'Not yet frozen')
                    write.assert_not_called()
                    request.assert_not_called()
                self.assertEqual(code, 0)
                self.assertEqual((result['pending'], result['availability']), (False, 'unavailable'))
                self.assertNotIn('preparedAt', result)
                self.assertNotIn('name', result)


if __name__ == '__main__':
    unittest.main()
