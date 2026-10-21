import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
from backend.store import Store, StoreError
from backend.server import Server

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'skills/exp-observer/scripts/exp_observer.py'


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Study', 'sourceRoots': [str(self.root)]})
        self.add_node('a')

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, ops, **extra):
        return self.store.batch('study', {'operations': ops, **extra})

    def add_node(self, key, parent=None):
        return self.apply([{'op': 'node.add', 'data': {'id': key, 'title': key, 'parentId': parent}}])

    def assertCode(self, code, function, *args, **kwargs):
        with self.assertRaises(StoreError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def test_stale_revision_and_durable_reload(self):
        revision = self.store.get_project('study')['revision']
        self.add_node('b')
        self.assertCode('revision_conflict', self.apply, [{'op': 'node.update', 'data': {'id': 'a', 'title': 'stale'}}], expectedRevision=revision)
        loaded = Store(self.root / 'data').get_project('study')
        self.assertEqual([n['title'] for n in loaded['nodes']], ['a', 'b'])

    def test_node_importance_and_suspended_work_survive_context_and_reload(self):
        self.apply([
            {'op': 'node.update', 'data': {'id': 'a', 'status': 'completed', 'importance': 'critical', 'importanceReason': 'Counterexample changes the main conclusion'}},
            {'op': 'run.add', 'data': {'id': 'failed-attempt', 'nodeId': 'a', 'status': 'failed'}},
        ])
        context = self.store.context('study', 'a')
        self.assertEqual(context['nodes'][0]['status'], 'completed')
        self.assertEqual(context['nodes'][0]['importance'], 'critical')
        self.assertEqual(context['runs'][0]['status'], 'failed')
        self.apply([
            {'op': 'node.update', 'data': {'id': 'a', 'status': 'paused', 'pauseReason': 'Investigate a new lead first', 'resumeWhen': 'After explaining the counterexample', 'nextAction': 'Finish repeated measurements'}},
            {'op': 'node.add', 'data': {'id': 'new-lead', 'status': 'proposed'}},
            {'op': 'edge.add', 'data': {'id': 'pivot', 'source': 'a', 'target': 'new-lead', 'relation': 'leads_to'}},
        ])
        other = Store(self.root / 'data')
        node = other.context('study', 'a')['nodes'][0]
        self.assertEqual(node['status'], 'paused')
        self.assertEqual(node['importanceReason'], 'Counterexample changes the main conclusion')
        self.assertEqual(node['pauseReason'], 'Investigate a new lead first')
        self.assertEqual(node['resumeWhen'], 'After explaining the counterexample')
        self.assertEqual(node['nextAction'], 'Finish repeated measurements')
        self.assertEqual(next(n for n in other.get_project('study')['nodes'] if n['id'] == 'new-lead')['status'], 'proposed')

    def test_invalid_node_observation_fields_roll_back(self):
        before = self.store.get_project('study')
        for data in ({'importance': 'high'}, {'pauseReason': {'unstructured': True}}, {'resumeWhen': None}, {'importanceReason': 42}):
            with self.subTest(data=data):
                self.assertCode('invalid_request', self.apply, [{'op': 'node.update', 'data': {'id': 'a', **data}}])
                self.assertEqual(self.store.get_project('study'), before)

    def test_atomic_batch_rollback(self):
        before = self.store.get_project('study')
        self.assertCode('invalid_reference', self.apply, [{'op': 'node.add', 'data': {'id': 'b'}}, {'op': 'edge.add', 'data': {'source': 'b', 'target': 'missing'}}])
        self.assertEqual(self.store.get_project('study'), before)
        self.assertEqual(len(self.store.history('study')), before['revision'])

    def test_containment_cycle_and_dangling_parent(self):
        self.add_node('b', 'a')
        self.assertCode('containment_cycle', self.apply, [{'op': 'node.update', 'data': {'id': 'a', 'parentId': 'b'}}])
        self.assertCode('invalid_reference', self.apply, [{'op': 'node.update', 'data': {'id': 'a', 'parentId': 'missing'}}])
        self.assertCode('self_edge', self.apply, [{'op': 'edge.add', 'data': {'source': 'a', 'target': 'a'}}])

    def test_idempotence_and_request_reuse(self):
        body = {'expectedRevision': 2, 'requestId': 'write-1', 'operations': [{'op': 'node.add', 'data': {'id': 'b'}}]}
        result = self.store.batch('study', body)
        self.add_node('c')
        self.assertEqual(self.store.batch('study', body), result)
        self.assertEqual(len(self.store.get_project('study')['nodes']), 3)
        body['operations'][0]['data']['id'] = 'd'
        self.assertCode('idempotency_conflict', self.store.batch, 'study', body)

    def test_independent_clients(self):
        other = Store(self.root / 'data')
        revision = self.store.get_project('study')['revision']
        def write(item):
            store, name = item
            try:
                store.batch('study', {'expectedRevision': revision, 'operations': [{'op': 'node.add', 'data': {'id': name}}]})
                return 'ok'
            except StoreError as exc:
                return exc.code
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(write, [(self.store, 'b'), (other, 'c')]))
        self.assertEqual(sorted(results), ['ok', 'revision_conflict'])
        self.assertEqual(len(self.store.get_project('study')['nodes']), 2)

    def test_process_lock(self):
        script = "from backend.store import Store; import sys; s=Store(sys.argv[1]); s.batch('study', {'operations':[{'op':'node.add','data':{'id':sys.argv[2]}}]})"
        procs = [subprocess.Popen([sys.executable, '-c', script, str(self.root / 'data'), f'p{i}'], cwd=ROOT) for i in range(5)]
        self.assertEqual([p.wait(timeout=15) for p in procs], [0] * 5)
        self.assertEqual(len(self.store.get_project('study')['nodes']), 6)

    def test_evidence_copy_and_tamper(self):
        source = self.root / 'output.txt'
        source.write_text('measured evidence\n')
        artifact = self.store.register_artifact('study', {'path': str(source), 'nodeId': 'a'})
        source.write_text('source changed independently')
        self.assertEqual(self.store.artifact_content('study', artifact['id'])[0], b'measured evidence\n')
        Path(artifact['path']).write_text('tampered')
        self.assertCode('evidence_changed', self.store.artifact_content, 'study', artifact['id'])
        self.assertCode('path_not_allowed', self.store.register_artifact, 'study', {'path': '/etc/hosts'})
        self.assertCode('registration_required', self.apply, [{'op': 'artifact.add', 'data': {'id': 'fake', 'origin': 'observed'}}])

    def test_evidence_survives_data_directory_relocation(self):
        source = self.root / 'result.json'
        source.write_text('{"measurement":42}')
        artifact = self.store.register_artifact('study', {'path': str(source), 'nodeId': 'a'})
        relocated_dir = self.root / 'relocated-data'
        shutil.copytree(self.root / 'data', relocated_dir)
        # Keep the old path present but corrupt: reads must use the retained copy in the new directory.
        Path(artifact['path']).write_text('external stale copy')
        relocated = Store(relocated_dir)
        self.assertEqual(relocated.artifact_content('study', artifact['id'])[0], b'{"measurement":42}')
        metadata = relocated.artifact_metadata('study', artifact['id'])
        self.assertTrue(metadata['verified'])
        self.assertTrue(Path(metadata['path']).is_relative_to(relocated_dir.resolve()))
        shutil.rmtree(self.root / 'data')
        self.assertEqual(relocated.artifact_content('study', artifact['id'], offset=2, limit=6)[0], b'measur')
        Path(metadata['path']).write_bytes(b'corrupted')
        self.assertCode('evidence_changed', relocated.artifact_metadata, 'study', artifact['id'])

    def test_mock_content_and_import(self):
        source = self.root / 'demo.txt'
        source.write_text('mock')
        p = self.apply([{'op': 'artifact.add', 'data': {'id': 'mock', 'nodeId': 'a', 'path': str(source), 'sha256': hashlib.sha256(b'mock').hexdigest(), 'bytes': 4}}])
        self.assertEqual(self.store.artifact_content('study', 'mock')[0], b'mock')
        imported = self.store.import_project(p)
        self.assertNotEqual(imported['id'], 'study')
        bad = copy.deepcopy(p)
        bad['edges'] = [{'id': 'x', 'source': 'a', 'target': 'missing'}]
        self.assertCode('invalid_reference', self.store.import_project, bad)

    def test_assessment_revision(self):
        self.apply([{'op': 'run.add', 'data': {'id': 'r', 'nodeId': 'a'}}, {'op': 'assessment.add', 'data': {'id': 'v1', 'runId': 'r', 'rubric': 'quality-v1', 'metrics': {'accuracy': 0.5}}}])
        self.apply([{'op': 'assessment.add', 'data': {'id': 'v2', 'runId': 'r', 'rubric': 'quality-v1', 'supersedes': 'v1', 'metrics': {'accuracy': 0.7}}}])
        self.assertEqual(len(self.store.get_project('study')['runs']), 1)
        self.assertEqual([a['id'] for a in self.store.context('study')['assessments']], ['v2'])
        self.assertCode('invalid_supersession', self.apply, [{'op': 'assessment.add', 'data': {'id': 'v3', 'runId': 'r', 'rubric': 'different', 'supersedes': 'v2'}}])

    def test_context_includes_decision_evidence_across_nodes_without_expansion(self):
        self.add_node('algorithm')
        self.add_node('unrelated')
        marker = 'RAW-PAYLOAD-EXCLUDED-FROM-CONTEXT'
        self.apply([
            {'op': 'run.add', 'data': {'id': 'chosen-run', 'nodeId': 'algorithm', 'artifactIds': ['run-evidence']}},
            {'op': 'run.add', 'data': {'id': 'unrelated-run', 'nodeId': 'unrelated'}},
            {'op': 'artifact.add', 'data': {'id': 'run-evidence', 'runId': 'chosen-run', 'content': marker}},
            {'op': 'artifact.add', 'data': {'id': 'decision-evidence', 'content': marker}},
            {'op': 'artifact.add', 'data': {'id': 'assessment-evidence', 'content': marker}},
            {'op': 'artifact.add', 'data': {'id': 'unrelated-evidence', 'runId': 'unrelated-run', 'content': marker}},
            {'op': 'assessment.add', 'data': {'id': 'v1', 'runId': 'chosen-run', 'rubric': 'quality', 'metrics': {'score': 1}}},
            {'op': 'assessment.add', 'data': {'id': 'v2', 'runId': 'chosen-run', 'rubric': 'quality', 'supersedes': 'v1', 'metrics': {'score': 2}, 'artifactIds': ['assessment-evidence'], 'rawPayload': marker}},
            {'op': 'decision.add', 'data': {'id': 'decision', 'nodeId': 'a', 'runIds': ['chosen-run'], 'artifactIds': ['decision-evidence'], 'rawPayload': marker}},
            {'op': 'edge.add', 'data': {'id': 'boundary', 'source': 'a', 'target': 'unrelated'}},
        ])
        context = self.store.context('study', 'a')
        self.assertEqual([r['id'] for r in context['runs']], ['chosen-run'])
        self.assertEqual([a['id'] for a in context['assessments']], ['v2'])
        self.assertEqual({a['id'] for a in context['artifacts']}, {'run-evidence', 'decision-evidence', 'assessment-evidence'})
        self.assertEqual({n['id'] for n in context['boundaryNodes']}, {'algorithm', 'unrelated'})
        self.assertEqual([n['id'] for n in context['nodes']], ['a'])
        self.assertNotIn(marker, json.dumps(context))

    def test_delete_and_restore(self):
        self.add_node('b', 'a')
        self.add_node('c')
        before = self.apply([{'op': 'edge.add', 'data': {'id': 'edge', 'source': 'b', 'target': 'c'}}, {'op': 'run.add', 'data': {'id': 'r', 'nodeId': 'b'}}, {'op': 'assessment.add', 'data': {'id': 'v1', 'runId': 'r', 'rubric': 'rubric'}}, {'op': 'decision.add', 'data': {'id': 'd', 'nodeId': 'c', 'runIds': ['r']}}])
        deleted = self.apply([{'op': 'node.delete', 'data': {'id': 'a'}}])
        self.assertEqual([n['id'] for n in deleted['nodes']], ['c'])
        self.assertEqual(deleted['runs'], [])
        self.assertEqual(deleted['edges'], [])
        self.assertEqual(deleted['decisions'][0]['runIds'], [])
        restored = self.store.restore('study', {'revision': before['revision'], 'expectedRevision': deleted['revision']})
        self.assertEqual(restored['nodes'], before['nodes'])
        self.assertGreater(restored['revision'], deleted['revision'])
        self.assertEqual(self.store.history('study')[-1]['operations'][0]['op'], 'project.restore')

    def test_unknown_fields_and_traversal(self):
        self.apply([{'op': 'node.update', 'data': {'id': 'a', 'custom': {'algorithm': 'BM25'}}}])
        p = self.apply([{'op': 'node.update', 'data': {'id': 'a', 'title': 'new'}}])
        self.assertEqual(p['nodes'][0]['custom'], {'algorithm': 'BM25'})
        self.assertCode('invalid_id', self.store.get_project, '../study')

    def test_observation_actual_server_elapsed_unknown_tokens_and_status_independence(self):
        before_node = self.store.get_project('study')['nodes'][0]
        started = self.apply([{'op': 'observation.start', 'data': {'id': 'step', 'nodeId': 'a', 'title': 'Inspect candidate',
                             'startedAt': '1900-01-01T00:00:00Z', 'durationMs': 999999, 'inputTokens': 999, 'origin': 'mock'}}])['observations'][0]
        self.assertEqual(started['status'], 'running')
        self.assertEqual(started['origin'], 'observed')
        self.assertNotEqual(started['startedAt'], '1900-01-01T00:00:00Z')
        self.assertIsNone(started['durationMs'])
        self.assertIsNone(started['inputTokens'])
        self.assertIsNone(started['outputTokens'])
        time.sleep(0.02)
        p = self.apply([{'op': 'observation.finish', 'data': {'id': 'step', 'finishedAt': '1900-01-01T00:00:00Z', 'durationMs': 999999}}])
        finished = p['observations'][0]
        elapsed = (datetime.fromisoformat(finished['finishedAt'].replace('Z', '+00:00')) - datetime.fromisoformat(started['startedAt'].replace('Z', '+00:00'))).total_seconds() * 1000
        self.assertGreaterEqual(finished['durationMs'], 15)
        self.assertAlmostEqual(finished['durationMs'], elapsed, places=3)
        self.assertEqual(finished['status'], 'finished')
        self.assertIsNone(finished['inputTokens'])
        self.assertIsNone(finished['outputTokens'])
        self.assertEqual(p['nodes'][0], before_node)
        self.assertEqual(p['runs'], [])
        self.assertEqual(Store(self.root / 'data').get_project('study')['observations'][0], finished)

    def test_observation_explicit_zero_requires_source(self):
        self.apply([{'op': 'observation.start', 'data': {'id': 'step', 'nodeId': 'a'}}])
        before = self.store.get_project('study')
        self.assertCode('usage_source_required', self.apply, [{'op': 'observation.finish', 'data': {'id': 'step', 'inputTokens': 0}}])
        self.assertEqual(self.store.get_project('study'), before)
        p = self.apply([{'op': 'observation.finish', 'data': {'id': 'step', 'inputTokens': 0, 'usageSource': 'runtime-counter'}}])
        self.assertEqual(p['observations'][0]['inputTokens'], 0)
        self.assertIsNone(p['observations'][0]['outputTokens'])
        self.assertCode('observation_finished', self.apply, [{'op': 'observation.finish', 'data': {'id': 'step'}}])

    def test_mock_observation_import_and_consistent_intervals(self):
        fixture = self.store.get_project('study')
        fixture['id'] = 'mock-study'
        fixture['observations'] = [{'id': 'demo-step', 'nodeId': 'a', 'title': 'Synthetic timing', 'status': 'finished',
                                    'startedAt': '2026-10-20T12:00:00.000Z', 'finishedAt': '2026-10-20T12:00:00.050Z',
                                    'durationMs': 50, 'inputTokens': None, 'outputTokens': None,
                                    'usageSource': '', 'usageRef': '', 'origin': 'mock'}]
        imported = self.store.import_project(fixture)
        self.assertEqual(imported['observations'][0]['origin'], 'mock')
        self.assertEqual(Store(self.root / 'data').context('mock-study')['observations'][0]['durationMs'], 50)
        for finished_at, duration in (('2026-10-20T11:59:59.999Z', 0), ('2026-10-20T12:00:00.050Z', 55)):
            invalid = copy.deepcopy(fixture)
            invalid['observations'][0].update({'finishedAt': finished_at, 'durationMs': duration})
            self.assertCode('invalid_observation_duration', self.store.import_project, invalid)
        self.apply([{'op': 'observation.start', 'data': {'id': 'clock-step', 'nodeId': 'a'}}])
        before = self.store.get_project('study')
        with patch('backend.store.now', return_value='1900-01-01T00:00:00.000Z'):
            self.assertCode('invalid_observation_duration', self.apply, [{'op': 'observation.finish', 'data': {'id': 'clock-step'}}])
        self.assertEqual(self.store.get_project('study'), before)

    def test_invalid_observation_tokens_and_duplicate_usage_roll_back(self):
        self.apply([{'op': 'observation.start', 'data': {'id': 'first', 'nodeId': 'a'}},
                    {'op': 'observation.start', 'data': {'id': 'second', 'nodeId': 'a'}}])
        before = self.store.get_project('study')
        for invalid in (True, -1, 2.5, '10', None):
            with self.subTest(counter=invalid):
                self.assertCode('invalid_token_counter', self.apply, [
                    {'op': 'node.update', 'data': {'id': 'a', 'title': 'must roll back'}},
                    {'op': 'observation.finish', 'data': {'id': 'first', 'inputTokens': invalid, 'usageSource': 'provider'}}])
                self.assertEqual(self.store.get_project('study'), before)
        self.assertCode('usage_source_required', self.apply, [{'op': 'observation.finish', 'data': {'id': 'first', 'usageRef': 'response-id'}}])
        self.apply([{'op': 'observation.finish', 'data': {'id': 'first', 'inputTokens': 12, 'outputTokens': 0, 'usageSource': 'provider', 'usageRef': 'response-id'}}])
        before_duplicate = self.store.get_project('study')
        self.assertCode('duplicate_usage_ref', self.apply, [
            {'op': 'node.update', 'data': {'id': 'a', 'summary': 'must roll back'}},
            {'op': 'observation.finish', 'data': {'id': 'second', 'outputTokens': 20, 'usageSource': 'provider', 'usageRef': 'response-id'}}])
        self.assertEqual(self.store.get_project('study'), before_duplicate)

    def test_observation_idempotence_scope_delete_restore_and_legacy(self):
        self.add_node('child', 'a')
        self.add_node('other')
        start_body = {'requestId': 'start-retry', 'operations': [{'op': 'observation.start', 'data': {'nodeId': 'child'}}]}
        started = self.store.batch('study', start_body)
        self.assertEqual(self.store.batch('study', start_body), started)
        observation_id = started['observations'][0]['id']
        finish_body = {'requestId': 'finish-retry', 'operations': [{'op': 'observation.finish', 'data': {'id': observation_id}}]}
        finished = self.store.batch('study', finish_body)
        self.assertEqual(self.store.batch('study', finish_body), finished)
        p = self.apply([{'op': 'observation.start', 'data': {'id': 'parent-step', 'nodeId': 'a'}},
                        {'op': 'observation.start', 'data': {'id': 'other-step', 'nodeId': 'other'}},
                        {'op': 'edge.add', 'data': {'source': 'a', 'target': 'other'}}])
        context = self.store.context('study', 'a')
        self.assertEqual({o['nodeId'] for o in context['observations']}, {'a', 'child'})
        self.assertEqual(context['counts']['observations'], 3)
        deleted = self.apply([{'op': 'node.delete', 'data': {'id': 'a'}}])
        self.assertEqual([o['id'] for o in deleted['observations']], ['other-step'])
        restored = self.store.restore('study', {'revision': p['revision'], 'expectedRevision': deleted['revision']})
        self.assertEqual(restored['observations'], p['observations'])
        legacy = copy.deepcopy(restored)
        legacy['id'] = 'legacy'
        del legacy['observations']
        imported = self.store.import_project(legacy)
        self.assertNotIn('observations', imported)
        self.assertEqual(Store(self.root / 'data').context('legacy')['observations'], [])
        updated = self.store.batch('legacy', {'operations': [{'op': 'observation.start', 'data': {'nodeId': 'a'}}]})
        self.assertEqual(len(updated['observations']), 1)

    def test_activity_metadata_and_restore_chronology(self):
        before = self.store.get_project('study')
        marker = 'RAW-NOTE-CONTENT-MUST-NOT-BE-DUPLICATED'
        edited = self.apply([{'op': 'node.update', 'data': {'id': 'a', 'notes': marker}}])
        self.assertEqual(len(edited['activity']), len(before['activity']) + 1)
        event = edited['activity'][-1]
        self.assertTrue(event['id'])
        self.assertTrue(event['at'])
        self.assertEqual(event['operations'], [{'op': 'node.update', 'recordId': 'a'}])
        self.assertNotIn(marker, json.dumps(edited['activity']))
        self.assertNotIn(marker, json.dumps(self.store.history('study')))
        source = self.root / 'evidence.txt'
        source.write_text('observed')
        self.store.register_artifact('study', {'path': str(source), 'nodeId': 'a'})
        registered = self.store.get_project('study')
        self.assertEqual(registered['activity'][-1]['operations'][0]['op'], 'artifact.register')
        restored = self.store.restore('study', {'revision': before['revision'], 'expectedRevision': registered['revision']})
        self.assertEqual(len(restored['activity']), len(registered['activity']) + 1)
        self.assertEqual(restored['activity'][-1]['operations'][0]['op'], 'project.restore')

    def test_evicted_request_retry_stays_idempotent(self):
        body = {'requestId': 'original', 'operations': [{'op': 'node.update', 'data': {'id': 'a', 'title': 'original'}}]}
        original = self.store.batch('study', body)
        # Exercise cache eviction without growing 256 full project snapshots in the fixture.
        with self.store._lock():
            bundle = self.store._load('study')
            bundle['requests'] = {}
            self.store._save(bundle)
        self.add_node('b')
        self.assertEqual(self.store.batch('study', body), original)
        body['operations'][0]['data']['title'] = 'different'
        self.assertCode('idempotency_conflict', self.store.batch, 'study', body)


class HTTPAndCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Study'})
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'a'}}]})
        self.server = Server(('127.0.0.1', 0), self.store, dist=self.root / 'dist')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, route, body=None, headers=None):
        req = Request(self.url + route, data=None if body is None else json.dumps(body).encode(), headers=headers or {})
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read())

    def cli(self, *args, input=None):
        return subprocess.run([sys.executable, str(CLI), '--url', self.url, *args], input=input, text=True, capture_output=True, cwd=self.root, timeout=20)

    def test_agent_setup_uses_repo_paths_and_actual_custom_port(self):
        setup = self.request('/api/agent-setup')
        self.assertEqual(setup['url'], self.url)
        self.assertNotEqual(self.server.server_port, 4317)
        self.assertEqual(Path(setup['skillPath']), ROOT / 'skills/exp-observer/SKILL.md')
        self.assertEqual(Path(setup['clientPath']), CLI)
        for key in ('skillPath', 'clientPath'):
            self.assertTrue(Path(setup[key]).is_absolute())
            self.assertTrue(Path(setup[key]).is_file())
        with self.assertRaises(HTTPError) as raised:
            self.request('/api/agent-setup', headers={'Host': 'evil.example'})
        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(json.loads(raised.exception.read())['code'], 'untrusted_host')
        raised.exception.close()

    def test_cli_url_environment_and_explicit_override(self):
        env = dict(os.environ, EXP_OBSERVER_URL=self.url)
        current = subprocess.run([sys.executable, str(CLI), 'projects'], env=env,
                                 text=True, capture_output=True, cwd=self.root, timeout=20)
        self.assertEqual(current.returncode, 0, current.stderr)
        env['EXP_OBSERVER_URL'] = 'http://127.0.0.1:1'
        explicit = subprocess.run([sys.executable, str(CLI), '--url', self.url, 'projects'],
                                  env=env, text=True, capture_output=True, cwd=self.root, timeout=20)
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertEqual(json.loads(current.stdout), json.loads(explicit.stdout))

    def test_security_and_body_limit(self):
        self.assertTrue(self.request('/api/health')['ok'])
        for headers in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'}):
            with self.assertRaises(HTTPError) as raised:
                self.request('/api/projects', {'name': 'bad'}, headers)
            self.assertEqual(raised.exception.code, 403)
            raised.exception.close()
        req = Request(self.url + '/api/projects', data=b'', headers={'Content-Length': str(2 * 1024 * 1024 + 1)})
        with self.assertRaises(HTTPError) as raised:
            urlopen(req, timeout=10)
        self.assertEqual(raised.exception.code, 413)
        raised.exception.close()
        with self.assertRaises(HTTPError) as raised:
            self.request('/api/projects/../context')
        self.assertEqual(raised.exception.code, 400)
        raised.exception.close()

    def test_cli_execute_export_check(self):
        result = self.cli('apply', '--project', 'study', '--request-id', 'test-apply', input=json.dumps([{'op': 'node.add', 'data': {'id': 'b', 'parentId': 'a'}}]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['counts']['nodes'], 2)
        result = self.cli('execute', '--project', 'study', '--node', 'b', '--title', 'Actual command', '--', sys.executable, '-c', "print('observed')")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary['status'], 'completed')
        self.assertEqual(len(summary['artifactIds']), 2)
        run = self.store.get_project('study')['runs'][0]
        self.assertEqual(run['origin'], 'observed')
        self.assertEqual(run['metrics']['exitCode'], 0)
        self.assertGreater(run['metrics']['wallTimeMs'], 0)
        self.assertEqual(self.store.artifact_content('study', run['artifactIds'][0])[0], b'observed\n')
        result = self.cli('check', '--project', 'study')
        self.assertTrue(json.loads(result.stdout)['ok'])
        result = self.cli('export', '--project', 'study', '--output', str(self.root / 'export.json'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.root / 'export.json').read_text())['id'], 'study')
        result = self.cli('context', '--project', 'study', '--node', 'b')
        self.assertEqual([n['id'] for n in json.loads(result.stdout)['nodes']], ['b'])

    def test_cli_failure_lifecycle(self):
        result = self.cli('execute', '--project', 'study', '--node', 'a', '--title', 'Failure', '--', sys.executable, '-c', "import sys; print('failure detail', file=sys.stderr); sys.exit(7)")
        self.assertEqual(result.returncode, 7, result.stderr)
        run = self.store.get_project('study')['runs'][0]
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['metrics']['exitCode'], 7)
        self.assertEqual(len(run['artifactIds']), 2)

    def test_cli_observe_start_finish_stable_retry(self):
        args = ('observe', 'start', '--project', 'study', '--node', 'a', '--title', 'Read results', '--request-id', 'cli-start')
        started = self.cli(*args)
        self.assertEqual(started.returncode, 0, started.stderr)
        observation = json.loads(started.stdout)
        self.assertIsNone(observation['inputTokens'])
        self.assertEqual(json.loads(self.cli(*args).stdout), observation)
        invalid = self.cli('observe', 'finish', '--project', 'study', '--id', observation['observationId'], '--input-tokens', '0')
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn('usage_source_required', invalid.stderr)
        finish_args = ('observe', 'finish', '--project', 'study', '--id', observation['observationId'], '--input-tokens', '0', '--output-tokens', '27', '--usage-source', 'runtime-meter', '--usage-ref', 'response-abc', '--request-id', 'cli-finish')
        finished = self.cli(*finish_args)
        self.assertEqual(finished.returncode, 0, finished.stderr)
        result = json.loads(finished.stdout)
        self.assertEqual(result['inputTokens'], 0)
        self.assertEqual(result['outputTokens'], 27)
        self.assertEqual(result['status'], 'finished')
        self.assertGreater(result['durationMs'], 0)
        self.assertEqual(json.loads(self.cli(*finish_args).stdout), result)
        self.assertEqual(len(self.store.get_project('study')['observations']), 1)

    def test_execute_result_artifacts_and_bulk_registration(self):
        code = "from pathlib import Path; Path('result.json').write_text('{\"measured\":42}'); Path('result.csv').write_text('score\\n42\\n')"
        result = self.cli('execute', '--project', 'study', '--node', 'a', '--title', 'Measured files',
                          '--artifact', 'result.json', '--artifact', 'result.csv', '--', sys.executable, '-c', code)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(len(summary['artifactIds']), 4)
        p = self.store.get_project('study')
        self.assertEqual(p['sourceRoots'], [str((self.root / '.exp-observer-runs/study').resolve())])
        by_title = {a['title']: a for a in p['artifacts']}
        captured = by_title['result.json']
        self.assertEqual(json.loads(self.store.artifact_content('study', captured['id'])[0]), {'measured': 42})
        self.assertTrue(Path(captured['sourcePath']).is_relative_to((self.root / '.exp-observer-runs/study').resolve()))
        self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'sourceRoots': p['sourceRoots'] + [str(self.root)]}}]})
        bulk = self.cli('artifact', '--project', 'study', '--node', 'a', '--path', 'result.json', 'result.csv')
        self.assertEqual(bulk.returncode, 0, bulk.stderr)
        self.assertEqual(len(json.loads(bulk.stdout)['artifacts']), 2)
        single = self.cli('artifact', '--project', 'study', '--node', 'a', '--path', 'result.json')
        self.assertEqual(single.returncode, 0, single.stderr)
        self.assertIn('id', json.loads(single.stdout))
        self.assertNotIn('artifacts', json.loads(single.stdout))

    def test_bounded_preview_and_streaming_metadata(self):
        source = self.root / 'large.txt'
        content = b'0123456789abcdef' * 131073
        source.write_bytes(content)
        self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'sourceRoots': [str(self.root)]}}]})
        artifact = self.store.register_artifact('study', {'path': str(source), 'nodeId': 'a'})
        route = '/api/projects/study/artifacts/' + artifact['id']
        metadata = self.request(route + '/metadata')
        self.assertTrue(metadata['verified'])
        self.assertEqual(metadata['bytes'], len(content))
        with urlopen(self.url + route + '/content?offset=5&limit=19', timeout=10) as response:
            self.assertEqual(response.read(), content[5:24])
        with urlopen(self.url + route + '/content?limit=262144', timeout=10) as response:
            self.assertEqual(len(response.read()), 262144)
        # CLI verification must not call the full-content endpoint.
        with patch.object(self.store, 'artifact_content', side_effect=AssertionError('content endpoint should not be used')):
            result = self.cli('check', '--project', 'study')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])
        with self.assertRaises(HTTPError) as raised:
            self.request(route + '/content?limit=1048577')
        self.assertEqual(raised.exception.code, 400)
        raised.exception.close()
        # A modification outside the requested window must also fail verification.
        with Path(artifact['path']).open('r+b') as stream:
            stream.seek(-1, 2)
            stream.write(b'X')
        for suffix in ('/metadata', '/content?limit=16'):
            with self.assertRaises(HTTPError) as raised:
                self.request(route + suffix)
            self.assertEqual(raised.exception.code, 409)
            raised.exception.close()

    def test_cli_read_verified_text_and_original_range_bytes(self):
        source = self.root / 'readable.txt'
        source.write_bytes(b'sample result\n\x00\xff')
        self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'sourceRoots': [str(self.root)]}}]})
        artifact = self.store.register_artifact('study', {'path': str(source), 'nodeId': 'a'})
        before = self.store.get_project('study')['revision']
        result = self.cli('read', '--project', 'study', '--artifact', artifact['id'], '--offset', '7', '--limit', '6')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'result')
        result = self.cli('read', '--project', 'study', '--artifact', artifact['id'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'sample result\n\x00\ufffd')
        output = self.root / 'saved' / 'range.bin'
        result = self.cli('read', '--project', 'study', '--artifact', artifact['id'], '--offset', '13', '--limit', '3', '--output', str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_bytes(), b'\n\x00\xff')
        self.assertEqual(json.loads(result.stdout)['bytes'], 3)
        self.assertEqual(self.store.get_project('study')['revision'], before)
        result = self.cli('read', '--project', 'study', '--artifact', artifact['id'], '--limit', '1048577')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        Path(artifact['path']).write_bytes(b'tampered')
        result = self.cli('read', '--project', 'study', '--artifact', artifact['id'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('evidence_changed', result.stderr)


if __name__ == '__main__':
    unittest.main()
