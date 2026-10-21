"""Capture must not steer experiments; recovery must never rerun or reread them."""
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from backend.server import Server
from backend.store import Store

ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / 'skills' / 'exp-observer' / 'scripts' / 'exp_observer.py'
spec = importlib.util.spec_from_file_location('capture_cli', CLI_PATH)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


@contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='exp capture 研究 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {'EXP_OBSERVER_STATE_DIR': str(self.root / 'state')})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Study'})
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'a'}}]})
        self.server = Server(('127.0.0.1', 0), self.store)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = cli.Client(self.url, timeout=2)

    def invoke(self, *arguments, client=None):
        args = cli.parser().parse_args(['--url', self.url, *arguments])
        results = []
        with working_directory(self.root), patch.object(cli, 'emit', side_effect=results.append):
            code = getattr(cli, args.command)(client or self.client, args)
        return code, results[-1]

    def tasks(self):
        return [json.loads(path.read_text(encoding='utf-8'))
                for path in (self.root / '.exp-observer-runs' / 'outbox').glob('*.json')
                if not path.name.startswith('project-')]

    def offline(self):
        client = cli.Client(self.url, timeout=2)
        client.request = lambda *a, **kw: (_ for _ in ()).throw(cli.ClientError('offline'))
        return client

    def test_record_generates_references_and_preserves_nested_metrics(self):
        metrics = {'quality': {'means': [1, 2.5, None], 'ok': True}, '标签': ['实测']}
        (self.root / 'metrics.json').write_text(json.dumps(metrics), encoding='utf-8-sig')
        (self.root / '结果 file.txt').write_text('original evidence', encoding='utf-8')
        arguments = ('record', '--project', 'study', '--title', 'Measured work', '--summary', 'Done',
                     '--after', 'a', '--parent', 'a', '--metrics-file', 'metrics.json',
                     '--artifact', '结果 file.txt', '--request-id', 'stable-record')
        code, result = self.invoke(*arguments)
        self.assertEqual(code, 0)
        self.assertFalse(result['pending'], result)
        project = self.store.get_project('study')
        node = next(n for n in project['nodes'] if n['id'] == result['nodeId'])
        self.assertEqual((node['parentId'], node['status'], node['summary']), ('a', 'active', 'Done'))
        self.assertEqual(project['edges'][0]['source'], 'a')
        self.assertEqual(project['edges'][0]['target'], node['id'])
        self.assertEqual(project['runs'][0]['metrics'], metrics)
        self.assertIsNone(project['runs'][0]['startedAt'])
        self.assertIsNone(project['runs'][0]['finishedAt'])
        self.assertEqual(project['runs'][0]['capturedAt'], result['capturedAt'])
        self.assertTrue(project['runs'][0]['configuration']['capturedExternalResult'])
        self.assertEqual(project['artifacts'][0]['runId'], result['runId'])
        revision = project['revision']
        self.assertEqual(self.invoke(*arguments)[1], result)
        self.assertEqual(self.store.get_project('study')['revision'], revision)
        with self.assertRaisesRegex(cli.ClientError, 'different work'):
            self.invoke('record', '--project', 'study', '--title', 'Changed', '--request-id', 'stable-record')

    def test_frozen_capture_retries_after_its_node_is_merged(self):
        (self.root / 'evidence.txt').write_bytes(b'original bytes')
        arguments = ('record', '--project', 'study', '--title', 'Captured result',
                     '--artifact', 'evidence.txt', '--request-id', 'merged-retry')
        _, first = self.invoke(*arguments)
        self.assertFalse(first['pending'])
        self.store.batch('study', {'operations': [
            {'op': 'node.merge', 'data': {'id': first['nodeId'], 'target': 'a'}},
        ]})
        revision = self.store.get_project('study')['revision']
        (self.root / 'evidence.txt').write_bytes(b'later change')
        _, retry = self.invoke(*arguments)
        self.assertFalse(retry['pending'], retry)
        project = self.store.get_project('study')
        self.assertEqual(project['revision'], revision)
        self.assertEqual(project['artifacts'][0]['nodeId'], 'a')
        content, _ = self.store.artifact_content('study', project['artifacts'][0]['id'])
        self.assertEqual(content, b'original bytes')

    def test_missing_relationship_title_does_not_block_the_finding(self):
        _, result = self.invoke('record', '--project', 'study', '--title', 'Measured finding',
                                '--after', '尚未记录的发现', '--relation', 'supports')
        self.assertFalse(result['pending'], result)
        self.assertTrue(any('not found locally' in warning for warning in result['recordingWarnings']))
        project = self.store.get_project('study')
        self.assertEqual(project['nodes'][-1]['conclusion'], 'Measured finding')
        self.assertEqual(project['edges'], [])

    def test_record_updates_existing_node_without_hand_authored_batch(self):
        code, result = self.invoke('record', '--project', 'study', '--node', 'a', '--title', 'Updated',
                                   '--summary', 'Finding', '--status', 'completed')
        self.assertEqual(code, 0)
        self.assertFalse(result['pending'], result)
        project = self.store.get_project('study')
        self.assertEqual(len(project['nodes']), 1)
        self.assertEqual((project['nodes'][0]['title'], project['nodes'][0]['status']), ('Updated', 'completed'))
        self.assertEqual(project['runs'], [])
        self.assertIsNone(result['runId'])

    def test_record_order_is_automatic_and_distinct_from_scientific_relationships(self):
        _, first = self.invoke('record', '--project', 'study', '--title', 'A measured finding', '--summary', 'Original measurements')
        _, command = self.invoke('execute', '--project', 'study', '--title', 'Inspect the counterexample',
                                 '--', sys.executable, '-c', 'print("observed")')
        arguments = ('record', '--project', 'study', '--title', 'Tolerance reduces observed changes',
                     '--conclusion', 'Observed changes fell from 24% to 3% in this sample', '--request-id', 'result')
        _, finding = self.invoke(*arguments)
        project = self.store.get_project('study')
        self.assertEqual([(edge['source'], edge['target'], edge['relation']) for edge in project['edges']],
                         [(first['nodeId'], command['nodeId'], 'recorded_after'),
                          (command['nodeId'], finding['nodeId'], 'recorded_after')])
        self.assertTrue(all(edge['label'] == '记录顺序' for edge in project['edges']))
        node = next(node for node in project['nodes'] if node['id'] == finding['nodeId'])
        self.assertEqual((node['kind'], node['conclusion']), ('finding', 'Observed changes fell from 24% to 3% in this sample'))
        self.invoke(*arguments)
        self.assertEqual(self.store.get_project('study')['revision'], project['revision'])
        _, independent = self.invoke('record', '--project', 'study', '--title', 'An unrelated observation', '--independent')
        self.assertEqual(len(self.store.get_project('study')['edges']), 2)
        _, counterexample = self.invoke('record', '--project', 'study', '--title', 'A boundary remains',
                                        '--after', 'Tolerance reduces observed changes', '--relation', 'qualifies')
        edge = self.store.get_project('study')['edges'][-1]
        self.assertEqual((edge['source'], edge['target'], edge['relation']),
                         (finding['nodeId'], counterexample['nodeId'], 'qualifies'))

    def test_capture_and_manual_sync_never_require_a_global_registry_write(self):
        with patch.object(cli, 'state_directory', side_effect=AssertionError('Research client accessed global state')):
            self.invoke('init', '--id', 'local-only', '--name', 'Local-only experiment', client=self.offline())
            self.invoke('record', '--project', 'local-only', '--title', 'Existing evidence', client=self.offline())
            self.invoke('execute', '--project', 'local-only', '--title', 'Local command',
                        '--', sys.executable, '-c', 'print("actual command")', client=self.offline())
            code, result = self.invoke('sync', '--project', 'local-only')
        self.assertEqual((code, result['pending']), (0, 0))
        self.assertEqual(len(self.store.get_project('local-only')['nodes']), 2)

    def test_child_capture_keeps_the_ancestor_experiment_identity_and_metadata(self):
        self.invoke('init', '--id', 'nested', '--name', 'Original research name', '--description', 'Original scope', client=self.offline())
        child = self.root / 'new experiment'
        child.mkdir()
        args = cli.parser().parse_args(['--url', self.url, 'record', '--project', 'nested', '--title', 'Actual result'])
        with working_directory(child), patch.object(cli, 'emit'):
            self.assertEqual(cli.record(self.offline(), args), 0)
            sync_args = cli.parser().parse_args(['--url', self.url, 'sync', '--project', 'nested'])
            self.assertEqual(cli.sync(self.client, sync_args), 0)
        project = self.store.get_project('nested')
        self.assertEqual((project['name'], project['description']), ('Original research name', 'Original scope'))

    def test_legacy_capture_retry_keeps_its_frozen_operations_and_never_reruns(self):
        script = "from pathlib import Path; p=Path('once.txt'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"
        arguments = ('execute', '--project', 'study', '--title', 'Original command', '--request-id', 'legacy',
                     '--', sys.executable, '-c', script)
        self.invoke(*arguments)
        path = next(path for path in (self.root / '.exp-observer-runs/outbox').glob('*.json')
                    if not path.name.startswith('project-'))
        task = json.loads(path.read_text(encoding='utf-8'))
        for key in ('after', 'relation', 'independent'):
            task['intent'].pop(key)
        cli.save_task(path, task)
        before = self.store.get_project('study')
        self.invoke(*arguments)
        self.assertEqual((self.root / 'once.txt').read_text(), '1')
        self.assertEqual(self.store.get_project('study'), before)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['operations'], task['operations'])

    def test_record_wraps_json_root_values_without_rewriting_result_files(self):
        metrics_path = self.root / 'metrics.json'
        for value in ([{'score': 1}, {'score': 2}], None, 3.5, True, 'result'):
            with self.subTest(value=value):
                original = json.dumps(value).encode('utf-8-sig')
                metrics_path.write_bytes(original)
                code, result = self.invoke('record', '--project', 'study', '--title', 'JSON result',
                                           '--metrics-file', str(metrics_path))
                self.assertEqual(code, 0)
                self.assertFalse(result['pending'], result)
                run = next(r for r in self.store.get_project('study')['runs'] if r['id'] == result['runId'])
                self.assertEqual(run['metrics'], {'result': value})
                self.assertEqual(metrics_path.read_bytes(), original)

    def test_nonstandard_result_files_are_retained_without_reformatting_or_interrupting_work(self):
        source = self.root / 'result.json'
        for content in (b'{"metric": NaN}', b'not JSON output'):
            with self.subTest(content=content):
                source.write_bytes(content)
                code, result = self.invoke('record', '--project', 'study', '--title', 'Existing result',
                                           '--metrics-file', str(source))
                self.assertEqual(code, 0)
                self.assertFalse(result['pending'], result)
                self.assertIsNone(result['runId'])
                self.assertIn('Metrics could not be decoded', result['recordingWarnings'][0])
                retained = result['artifactIds'][0]
                self.assertEqual(self.store.artifact_content('study', retained)[0], content)
                self.assertEqual(source.read_bytes(), content)
        self.assertEqual(self.invoke('sync')[1], {'records': [], 'pending': 0})

    def test_offline_execution_runs_first_sync_uses_frozen_bytes_and_timestamps(self):
        marker = self.root / 'count.txt'
        script = ("from pathlib import Path; p=Path('count.txt'); "
                  "p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); "
                  "Path('结果.txt').write_text('original', encoding='utf-8'); print('observed')")
        offline = self.offline()
        def fail_after_execution(*args, **kwargs):
            self.assertEqual(marker.read_text(), '1', 'Observer accessed network before the experiment')
            raise cli.ClientError('offline')
        offline.request = fail_after_execution
        arguments = ('execute', '--project', 'study', '--node', 'a', '--title', 'Actual experiment',
                     '--artifact', '结果.txt', '--request-id', 'once', '--', sys.executable, '-c', script)
        code, result = self.invoke(*arguments, client=offline)
        self.assertEqual(code, 0)
        self.assertEqual(result['exitCode'], 0)
        self.assertTrue(result['pending'])
        self.assertIn('offline', result['recordingWarnings'])
        self.assertEqual(Path(result['stdoutPath']).read_text().strip(), 'observed')
        before = self.tasks()[0]
        self.assertEqual(self.invoke(*arguments, client=offline)[0], 0)
        self.assertEqual(marker.read_text(), '1')
        with self.assertRaisesRegex(cli.ClientError, 'different work'):
            self.invoke('execute', '--project', 'study', '--node', 'a', '--title', 'Different command',
                        '--request-id', 'once', '--', sys.executable, '-c', 'pass')
        (self.root / '结果.txt').write_text('changed after experiment', encoding='utf-8')
        code, synced = self.invoke('sync', '--project', 'study')
        self.assertEqual(code, 0, synced)
        project = self.store.get_project('study')
        run = project['runs'][0]
        self.assertEqual((run['startedAt'], run['finishedAt']), (before['startedAt'], before['finishedAt']))
        artifact = next(a for a in project['artifacts'] if a['title'] == '结果.txt')
        self.assertEqual(self.store.artifact_content('study', artifact['id'])[0], b'original')
        self.assertEqual(artifact['capturedAt'], next(a['capturedAt'] for a in before['artifacts'] if a['title'] == '结果.txt'))
        revision = project['revision']
        self.assertEqual(self.invoke('sync')[0], 0)
        self.assertEqual(self.invoke(*arguments)[0], 0)
        self.assertEqual(marker.read_text(), '1')
        self.assertEqual(self.store.get_project('study')['revision'], revision)

    def test_missing_evidence_and_offline_errors_do_not_change_command_exit_codes(self):
        for exit_code, client in ((0, self.client), (7, self.offline()), (137, self.offline())):
            with self.subTest(exit_code=exit_code):
                code, result = self.invoke('execute', '--project', 'study', '--node', 'a', '--title', 'Exit',
                    '--artifact', 'missing.txt', '--', sys.executable, '-c', f'import sys; sys.exit({exit_code})', client=client)
                self.assertEqual(code, exit_code)
                self.assertEqual(result['exitCode'], exit_code)
                self.assertTrue(result['recordingWarnings'])
                self.assertEqual(result['status'], 'completed' if exit_code == 0 else 'failed')

    def test_local_recording_failure_still_executes_once(self):
        with patch.object(cli, 'save_task', side_effect=OSError('disk unavailable')):
            code, result = self.invoke('execute', '--project', 'study', '--node', 'a', '--title', 'Local failure',
                '--', sys.executable, '-c', "from pathlib import Path; Path('executed.txt').write_text('once')")
        self.assertEqual(code, 0)
        self.assertEqual((self.root / 'executed.txt').read_text(), 'once')
        self.assertIn('No durable record is available for sync.', result['recordingWarnings'])

    def test_missing_node_does_not_prevent_experiment(self):
        code, result = self.invoke('execute', '--project', 'study', '--node', 'missing', '--title', 'Bad reference',
            '--', sys.executable, '-c', "from pathlib import Path; Path('executed.txt').write_text('once')")
        self.assertEqual(code, 0)
        self.assertEqual((self.root / 'executed.txt').read_text(), 'once')
        self.assertTrue(result['pending'])
        self.assertIn('invalid_reference', result['recordingWarnings'][0])
        self.assertEqual(self.store.get_project('study')['runs'], [])

    def test_lost_batch_response_and_artifact_response_are_idempotent(self):
        for route_suffix in ('/batch', '/artifacts'):
            with self.subTest(route=route_suffix):
                client = cli.Client(self.url, timeout=2)
                original = client.request
                lost = []
                def lose_response(route, body=None, raw=False):
                    response = original(route, body, raw)
                    if body is not None and route.endswith(route_suffix) and not lost:
                        lost.append(True)
                        raise cli.ClientError('Response lost after commit')
                    return response
                client.request = lose_response
                code, result = self.invoke('execute', '--project', 'study', '--node', 'a', '--title', 'Response loss',
                    '--', sys.executable, '-c', "print('one execution')", client=client)
                self.assertEqual(code, 0)
                self.assertTrue(result['pending'])
                self.assertEqual(self.invoke('sync')[0], 0)
                project = self.store.get_project('study')
                self.assertEqual(len([r for r in project['runs'] if r['id'] == result['runId']]), 1)
                self.assertEqual(len([a for a in project['artifacts'] if a['runId'] == result['runId']]), 2)

    def test_sync_refuses_changed_staged_evidence_instead_of_rereading_source(self):
        source = self.root / 'source.txt'
        source.write_text('original')
        _, result = self.invoke('record', '--project', 'study', '--title', 'Snapshot',
                                '--artifact', str(source), client=self.offline())
        self.assertTrue(result['pending'])
        task = self.tasks()[0]
        Path(task['artifacts'][0]['path']).write_text('tampered snapshot')
        source.write_text('new source')
        code, synced = self.invoke('sync')
        self.assertEqual(code, 1)
        captured = next(record for record in synced['records'] if record.get('nodeId') == result['nodeId'])
        self.assertIn('Staged evidence changed', captured['recordingWarnings'][0])
        self.assertEqual(self.store.get_project('study')['artifacts'], [])

    def test_concurrent_source_roots_are_merged_with_revision_retry(self):
        (self.root / 'evidence.txt').write_text('bytes')
        client = cli.Client(self.url, timeout=2)
        original = client.apply
        interleaved = []
        other_root = str(self.root / 'another-agent')
        def race(project, operations, revision=None, request_id=None):
            if operations[0]['op'] == 'project.update' and not interleaved:
                interleaved.append(True)
                self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'sourceRoots': [other_root]}}]})
            return original(project, operations, revision, request_id)
        client.apply = race
        _, result = self.invoke('record', '--project', 'study', '--title', 'Merge', '--artifact', 'evidence.txt', client=client)
        self.assertFalse(result['pending'], result)
        self.assertCountEqual(self.store.get_project('study')['sourceRoots'],
                              [other_root, str((self.root / '.exp-observer-runs' / 'study').resolve())])

    def test_apply_keeps_reference_validation(self):
        result = subprocess.run([sys.executable, str(CLI_PATH), '--url', self.url, 'apply', '--project', 'study'],
            input=json.dumps([{'op': 'run.add', 'data': {'nodeId': 'missing'}}]), text=True,
            encoding='utf-8', capture_output=True, cwd=self.root, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn('invalid_reference', result.stderr)


if __name__ == '__main__':
    unittest.main()