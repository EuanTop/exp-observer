"""Frozen legacy evidence requests recover without changing their identities."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.store import Store, StoreError, canonical
from tests.test_capture import cli, working_directory
from tests.test_semantic_events import StoreClient


class LegacyEvidenceRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='observer legacy evidence ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Legacy evidence study'})
        self.store.batch('study', {'operations': [
            {'op': 'node.add', 'data': {'id': 'experiment', 'title': 'Observed execution'}},
            {'op': 'node.add', 'data': {'id': 'finding', 'title': 'Observed finding'}},
            {'op': 'run.add', 'data': {'id': 'run-actual', 'nodeId': 'experiment',
                                     'title': 'Actual measurement', 'status': 'completed',
                                     'metrics': {'accuracy': 0.91}}},
        ]})

    def request(self, source='run-actual', **data):
        return {'requestId': 'capture-legacy', 'operations': [
            {'op': 'edge.add', 'data': {'id': 'supported', 'source': source,
                                      'target': 'finding', 'relation': 'supports', **data}},
        ]}

    def assert_rejected_unchanged(self, body, code='invalid_reference'):
        before = self.store.get_project('study')
        with self.assertRaises(StoreError) as raised:
            self.store.batch('study', body)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(self.store.get_project('study'), before)

    def test_exact_run_source_recovers_with_original_fingerprint_and_dependent_batch(self):
        body = self.request()
        original = copy.deepcopy(body)
        retained = self.store.batch('study', body)
        self.assertEqual(body, original)
        edge = retained['edges'][0]
        self.assertEqual((edge['source'], edge['target'], edge['runIds']),
                         ('experiment', 'finding', ['run-actual']))
        history = next(row for row in self.store.history('study') if row.get('requestId') == body['requestId'])
        self.assertEqual(history['fingerprint'], hashlib.sha256(canonical(original['operations']).encode()).hexdigest())
        self.store.batch('study', {'requestId': 'dependent-update', 'operations': [
            {'op': 'node.update', 'data': {'id': 'finding', 'notes': 'Follow-up retained after recovery'}},
        ]})
        latest = self.store.get_project('study')
        # A retry after a lost reply returns its original committed revision,
        # without overwriting the dependent update or appending more history.
        self.assertEqual(self.store.batch('study', body), retained)
        self.assertEqual(self.store.get_project('study'), latest)
        self.assertEqual(Store(self.root / 'data').get_project('study'), latest)
        changed = copy.deepcopy(body)
        changed['operations'][0]['data']['source'] = 'experiment'
        self.assert_rejected_unchanged(changed, 'idempotency_conflict')

    def test_existing_node_and_merged_node_alias_take_priority_over_run_id(self):
        self.store.batch('study', {'operations': [
            {'op': 'node.add', 'data': {'id': 'run-actual', 'title': 'A real node with this ID'}},
        ]})
        result = self.store.batch('study', self.request())
        self.assertEqual(result['edges'][0]['source'], 'run-actual')
        self.assertNotIn('runIds', result['edges'][0])
        self.store.batch('study', {'operations': [
            {'op': 'node.merge', 'data': {'id': 'run-actual', 'target': 'finding'}},
        ]})
        body = self.request(target='experiment')
        body['requestId'] = 'alias-priority'
        body['operations'][0]['data']['id'] = 'alias-supported'
        result = self.store.batch('study', body)
        edge = next(edge for edge in result['edges'] if edge['id'] == 'alias-supported')
        self.assertEqual(edge['source'], 'finding')
        self.assertNotIn('runIds', edge)

    def test_run_owner_merge_is_resolved_and_self_edge_rejected(self):
        self.store.batch('study', {'operations': [
            {'op': 'node.add', 'data': {'id': 'merged-owner', 'title': 'Merged execution owner'}},
            {'op': 'node.merge', 'data': {'id': 'experiment', 'target': 'merged-owner'}},
        ]})
        result = self.store.batch('study', self.request())
        self.assertEqual(result['edges'][0]['source'], 'merged-owner')
        self.assertEqual(result['edges'][0]['runIds'], ['run-actual'])
        body = self.request(target='merged-owner')
        body['requestId'] = 'self-edge-attempt'
        body['operations'][0]['data']['id'] = 'self-supported'
        self.assert_rejected_unchanged(body, 'self_edge')

    def test_forward_node_reference_beats_colliding_run_and_forward_run_resolves(self):
        body = self.request()
        body['operations'].append({'op': 'node.add', 'data': {'id': 'run-actual', 'title': 'A later node'}})
        result = self.store.batch('study', body)
        self.assertEqual(result['edges'][0]['source'], 'run-actual')
        self.assertNotIn('runIds', result['edges'][0])
        body = self.request('run-added-later')
        body['requestId'] = 'forward-run'
        body['operations'][0]['data']['id'] = 'forward-supported'
        body['operations'].append({'op': 'run.add', 'data': {'id': 'run-added-later',
                                                           'nodeId': 'experiment', 'status': 'completed'}})
        result = self.store.batch('study', body)
        edge = next(edge for edge in result['edges'] if edge['id'] == 'forward-supported')
        self.assertEqual((edge['source'], edge['runIds']), ('experiment', ['run-added-later']))

    def test_run_ids_are_preserved_deduplicated_and_owner_constraints_still_apply(self):
        self.store.batch('study', {'operations': [
            {'op': 'run.add', 'data': {'id': 'run-other', 'nodeId': 'experiment', 'status': 'completed'}},
            {'op': 'run.add', 'data': {'id': 'run-foreign-owner', 'nodeId': 'finding', 'status': 'completed'}},
        ]})
        result = self.store.batch('study', self.request(runIds=['run-other', 'run-actual']))
        self.assertEqual(result['edges'][0]['runIds'], ['run-other', 'run-actual'])
        body = self.request(runIds=['run-foreign-owner'])
        body['requestId'] = 'mismatched-evidence'
        body['operations'][0]['data']['id'] = 'mismatched-supported'
        self.assert_rejected_unchanged(body)

    def test_unknown_cross_project_and_ambiguous_titles_are_not_guessed(self):
        self.store.create_project({'id': 'other-study', 'name': 'Another study'})
        self.store.batch('other-study', {'operations': [
            {'op': 'node.add', 'data': {'id': 'other-owner'}},
            {'op': 'run.add', 'data': {'id': 'run-other-project', 'nodeId': 'other-owner', 'status': 'completed'}},
        ]})
        self.store.batch('study', {'operations': [
            {'op': 'run.add', 'data': {'id': 'run-same-title', 'nodeId': 'experiment',
                                     'title': 'Actual measurement', 'status': 'completed'}},
        ]})
        for source in ('run-missing', 'run-other-project', 'Actual measurement'):
            with self.subTest(source=source):
                self.assert_rejected_unchanged(self.request(source))
        self.assert_rejected_unchanged(self.request(runIds='run-actual'), 'invalid_request')
        related = self.store.batch('study', self.request(relation='related_to'))
        self.assertEqual(related['edges'][0]['source'], 'experiment')
        self.assertNotIn('runIds', related['edges'][0])

    def test_reference_only_ensure_stays_atomic_until_real_node_arrives(self):
        body = {'requestId': 'deferred-exact-reference', 'operations': [
            {'op': 'node.add', 'data': {'id': 'dependent-finding', 'title': 'Retained finding'}},
            {'op': 'node.ensure', 'data': {'id': 'question-retained', 'referenceOnly': True}},
            {'op': 'edge.add', 'data': {'id': 'deferred-edge', 'source': 'question-retained',
                                      'target': 'dependent-finding', 'relation': 'has_finding'}},
        ]}
        original = copy.deepcopy(body)
        self.assert_rejected_unchanged(body, 'unresolved_reference')
        self.assertEqual(body, original)
        self.assertFalse(any(row.get('requestId') == body['requestId'] for row in self.store.history('study')))
        self.store.batch('study', {'operations': [
            {'op': 'node.add', 'data': {'id': 'question-retained', 'title': 'The real question', 'status': 'paused'}},
        ]})
        result = self.store.batch('study', body)
        node = next(node for node in result['nodes'] if node['id'] == 'question-retained')
        self.assertEqual((node['title'], node['status']), ('The real question', 'paused'))
        self.assertNotIn('referenceOnly', node)
        self.assertEqual(body, original)
        self.assertEqual(self.store.batch('study', body), result)
        history = next(row for row in self.store.history('study') if row.get('requestId') == body['requestId'])
        self.assertEqual(history['fingerprint'], hashlib.sha256(canonical(original['operations']).encode()).hexdigest())

    def test_reference_only_ensure_accepts_alias_without_changing_retained_metadata(self):
        self.store.batch('study', {'operations': [
            {'op': 'node.merge', 'data': {'id': 'experiment', 'target': 'finding'}},
        ]})
        before = self.store.get_project('study')['nodes']
        result = self.store.batch('study', {'operations': [
            {'op': 'node.ensure', 'data': {'id': 'experiment', 'referenceOnly': True,
                                         'title': 'Must never overwrite the real title'}},
        ]})
        self.assertEqual(result['nodes'], before)
        self.assertTrue(all('referenceOnly' not in node for node in result['nodes']))
        self.assert_rejected_unchanged({'operations': [
            {'op': 'node.ensure', 'data': {'id': 'missing', 'referenceOnly': 'true'}},
        ]}, 'invalid_request')

    def test_legacy_queue_lost_reply_and_dependent_capture_recover_without_rerunning(self):
        client = StoreClient(self.store)

        def invoke(*arguments):
            args = cli.parser().parse_args(['--url', client.url, *arguments])
            output = []
            with working_directory(self.root), patch.object(cli, 'emit', side_effect=output.append):
                getattr(cli, args.command)(client, args)
            return output[-1]

        executed = invoke('execute', '--project', 'study', '--node', 'experiment', '--title', 'Execute once',
                          '--', sys.executable, '-c',
                          "from pathlib import Path; p=Path('execution-count.txt'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')")
        client.offline = True
        finding = invoke('event', '--project', 'study', '--question', 'Retained question',
                         '--finding', 'The measured result', '--evidence', executed['runId'],
                         '--request-id', 'legacy-finding')
        pending = self.root / '.exp-observer-runs' / 'outbox'
        path = next(path for path in pending.glob('*.json') if cli.read_queue_task(path).get('requestId') == 'legacy-finding')
        task = cli.read_queue_task(path)
        edge = next(operation['data'] for operation in task['operations']
                    if operation['op'] == 'edge.add' and operation['data']['relation'] == 'supports')
        edge['source'] = executed['runId']
        edge.pop('runIds', None)
        cli.save_task(path, task)
        frozen = copy.deepcopy(task['operations'])
        frozen_artifacts = copy.deepcopy(task['artifacts'])
        dependent = invoke('event', '--project', 'study', '--question', 'Retained question',
                           '--correction', 'A retained qualification', '--after', finding['nodeId'],
                           '--request-id', 'dependent-correction')
        client.offline = False
        client.lose_batch_reply = True
        invoke('sync', '--project', 'study')
        invoke('sync', '--project', 'study')
        latest = self.store.get_project('study')
        invoke('sync', '--project', 'study')
        self.assertEqual(self.store.get_project('study'), latest)
        self.assertEqual(cli.read_queue_task(path)['operations'], frozen)
        self.assertEqual(cli.read_queue_task(path)['artifacts'], frozen_artifacts)
        self.assertEqual(cli.read_queue_task(path)['state'], 'synced')
        self.assertEqual((self.root / 'execution-count.txt').read_text(), '1')
        self.assertEqual(len([node for node in latest['nodes'] if node['id'] == finding['nodeId']]), 1)
        self.assertTrue(any(edge['source'] == finding['nodeId'] and edge['target'] == dependent['nodeId']
                            for edge in latest['edges']))
        support = next(edge for edge in latest['edges'] if edge['target'] == finding['nodeId'] and edge['relation'] == 'supports')
        self.assertEqual(support['runIds'], [executed['runId']])
        self.assertEqual(len([run for run in latest['runs'] if run['id'] == executed['runId']]), 1)
        for artifact in latest['artifacts']:
            self.assertTrue(self.store.artifact_metadata('study', artifact['id'])['verified'])


if __name__ == '__main__':
    unittest.main()
