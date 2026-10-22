"""Research results retain their native JSON shape; layout stays with the platform."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from backend.store import Store, StoreError


class ObservationRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Study', 'sourceRoots': [str(self.root)]})

    def test_nested_metrics_roundtrip_retry_history_and_restore(self):
        metrics = {'latency': {'p50': 0, 'samples': [0.1, 0.2, None]},
                   'groups': [{'name': '中文', 'ok': True}, {'ok': False}],
                   'empty': {}, 'missing': None, 'array': [], 'a.b': {'/key~': 3}}
        body = {'requestId': 'capture-results', 'operations': [
            {'op': 'node.add', 'data': {'id': 'n', 'title': 'Actual result'}},
            {'op': 'run.add', 'data': {'id': 'r', 'nodeId': 'n', 'metrics': metrics}},
            {'op': 'assessment.add', 'data': {'id': 'a', 'runId': 'r', 'rubric': 'raw', 'metrics': metrics}},
        ]}
        recorded = self.store.batch('study', body)
        self.assertEqual(recorded['runs'][0]['metrics'], metrics)
        self.assertEqual(recorded['assessments'][0]['metrics'], metrics)
        self.store.batch('study', {'operations': [
            {'op': 'run.update', 'data': {'id': 'r', 'metrics': {'later': [None, {'value': 1}]}}}
        ]})
        self.assertEqual(self.store.batch('study', body), recorded)
        restored = self.store.restore('study', {'revision': recorded['revision'],
                                               'expectedRevision': self.store.get_project('study')['revision']})
        self.assertEqual(restored['runs'][0]['metrics'], metrics)
        self.assertEqual(Store(self.root / 'data').get_project('study')['assessments'][0]['metrics'], metrics)

    def test_invalid_json_metrics_do_not_partially_save(self):
        before = self.store.get_project('study')
        for metrics in ({'deep': [float('nan')]}, {'deep': {'infinity': float('inf')}},
                        {'tuple': (1, 2)}, {'bad': {1: 'non-string key'}}, []):
            with self.subTest(metrics=metrics):
                with self.assertRaises(StoreError):
                    self.store.batch('study', {'operations': [
                        {'op': 'node.add', 'data': {'id': 'n'}},
                        {'op': 'run.add', 'data': {'nodeId': 'n', 'metrics': metrics}},
                    ]})
                self.assertEqual(self.store.get_project('study'), before)

    def test_automatic_positions_do_not_overlap_and_retry_is_exact(self):
        body = {'requestId': 'add-nodes', 'operations': [
            {'op': 'node.add', 'data': {'title': f'Step {i}'}} for i in range(10)
        ]}
        recorded = self.store.batch('study', body)
        positions = [node['position'] for node in recorded['nodes']]
        self.assertEqual(len({(pos['x'], pos['y']) for pos in positions}), 10)
        for i, a in enumerate(positions):
            for b in positions[i + 1:]:
                self.assertTrue(abs(a['x'] - b['x']) >= 396 or abs(a['y'] - b['y']) >= 258)
        self.assertGreater(len({pos['x'] for pos in positions}), 1)
        self.assertTrue(all(node['positionSource'] == 'auto' for node in recorded['nodes']))
        self.assertEqual(self.store.batch('study', body), recorded)

    def test_children_can_precede_parent_without_agent_coordinates(self):
        result = self.store.batch('study', {'operations': [
            {'op': 'node.add', 'data': {'id': 'child', 'parentId': 'parent'}},
            {'op': 'node.add', 'data': {'id': 'parent'}},
            {'op': 'node.add', 'data': {'id': 'manual', 'position': {'x': -500, 'y': 700}}},
        ]})
        nodes = {node['id']: node for node in result['nodes']}
        # An ordinary research parent is a card, not an enclosing frame. Its
        # child shares the root visual scope and follows it vertically.
        self.assertEqual(nodes['child']['position']['x'], nodes['parent']['position']['x'])
        self.assertGreaterEqual(nodes['child']['position']['y'], nodes['parent']['position']['y'] + 230 + 52)
        self.assertEqual(nodes['child']['positionSource'], 'auto')
        self.assertEqual(nodes['manual']['position'], {'x': -500, 'y': 700})
        existing = copy.deepcopy(nodes)
        result = self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'later'}}]})
        for node in result['nodes']:
            if node['id'] in existing:
                self.assertEqual(node['position'], existing[node['id']]['position'])

    def test_registration_keeps_capture_time_separate_from_registration(self):
        evidence = self.root / 'result.json'
        evidence.write_text('{"raw": {"nested": [1, null]}}', encoding='utf-8')
        capture_time = '2026-10-20T12:00:00.000Z'
        artifact = self.store.register_artifact('study', {'path': str(evidence), 'capturedAt': capture_time})
        self.assertEqual(artifact['capturedAt'], capture_time)
        self.assertNotEqual(artifact['createdAt'], capture_time)
        self.assertEqual(self.store.artifact_content('study', artifact['id'])[0], evidence.read_bytes())

    def test_changed_capture_is_rejected_before_evidence_or_history_is_committed(self):
        evidence = self.root / 'changed.txt'
        original = b'original result'
        evidence.write_bytes(b'later result')
        before = self.store.get_project('study')
        with self.assertRaises(StoreError) as raised:
            self.store.register_artifact('study', {'path': str(evidence),
                                                 'sha256': hashlib.sha256(original).hexdigest(), 'bytes': len(original)})
        self.assertEqual(raised.exception.code, 'evidence_changed')
        self.assertEqual(self.store.get_project('study'), before)
        self.assertEqual(list((self.root / 'data' / 'study' / 'evidence').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
