"""Cold references and delivery receipts preserve facts without inventing nodes."""
import copy
import json
import unittest
from unittest.mock import patch

from tests import test_semantic_events as fixtures


class ReferenceDeliveryTests(unittest.TestCase):
    setUp = fixtures.SemanticEventTests.setUp
    invoke = fixtures.SemanticEventTests.invoke
    project = fixtures.SemanticEventTests.project
    tasks = fixtures.SemanticEventTests.tasks

    def test_cold_retained_id_fetches_real_title_without_duplicate(self):
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {
            'id': 'question-retained', 'title': 'An actual retained question', 'kind': 'question'}}]})
        _, result = self.invoke('event', '--project', 'study', '--question', 'question-retained',
                                '--finding', 'A new measured finding')
        self.assertFalse(result['pending'])
        self.assertEqual(result['questionId'], 'question-retained')
        self.assertEqual(len(self.project()['nodes']), 2)
        self.assertNotIn('question-retained', [n['title'] for n in self.project()['nodes']])

    def test_unknown_id_retains_finding_and_evidence_until_reference_arrives(self):
        evidence = self.root / 'result.txt'
        evidence.write_text('original evidence', encoding='utf-8')
        self.client.offline = True
        _, result = self.invoke('event', '--project', 'study', '--question', 'question-upstream',
                                '--finding', 'Actual finding', '--notes', '## Preserved analysis',
                                '--artifact', str(evidence), '--request-id', 'retained-finding')
        self.assertTrue(result['pending'])
        task = self.tasks()[0]
        original_ops = copy.deepcopy(task['operations'])
        artifact = task['artifacts'][0]
        self.assertTrue(task['operations'][0]['data']['referenceOnly'])
        evidence.write_text('changed source', encoding='utf-8')
        self.client.offline = False
        _, blocked = self.invoke('sync', '--project', 'study')
        self.assertEqual(blocked['pending'], 1)
        self.assertEqual(self.project()['nodes'], [])
        _, status = self.invoke('status', '--project', 'study')
        self.assertEqual(status['blockedCount'], 1)
        self.assertEqual(status['pendingRecords'][0]['delivery']['lastError']['code'], 'unresolved_reference')
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {
            'id': 'question-upstream', 'title': 'Real upstream question', 'kind': 'question'}}]})
        self.invoke('sync', '--project', 'study')
        self.invoke('sync', '--project', 'study')
        healed = self.tasks()[0]
        self.assertEqual(healed['operations'], original_ops)
        self.assertEqual(healed['artifacts'][0]['sha256'], artifact['sha256'])
        self.assertEqual(healed['capturedAt'], task['capturedAt'])
        self.assertIsNone(healed['delivery']['lastError'])
        self.assertEqual(healed['state'], 'synced')
        self.assertEqual(len(self.project()['nodes']), 2)
        self.assertEqual(len(self.project()['artifacts']), 1)
        self.assertEqual(self.project()['nodes'][1]['notes'], '## Preserved analysis')

    def test_transport_failure_diagnostics_survive_and_success_clears_current_error(self):
        self.client.offline = True
        _, result = self.invoke('event', '--project', 'study', '--question', 'A normal question?',
                                '--finding', 'Original discovery', '--request-id', 'outage')
        original = self.tasks()[0]
        self.assertEqual(original['delivery']['attempts'], 1)
        self.assertEqual(original['delivery']['lastError']['code'], 'unavailable')
        _, status = self.invoke('status', '--project', 'study')
        self.assertEqual(status['blockedCount'], 1)
        self.assertEqual(status['pendingRecords'][0]['delivery']['lastError'], original['delivery']['lastError'])
        self.client.offline = False
        self.client.lose_batch_reply = True
        self.invoke('sync', '--project', 'study')
        self.invoke('sync', '--project', 'study')
        healed = self.tasks()[0]
        self.assertEqual(healed['operations'], original['operations'])
        self.assertEqual(healed['requestId'], original['requestId'])
        self.assertEqual(healed['delivery']['attempts'], 3)
        self.assertIsNone(healed['delivery']['lastError'])
        self.assertTrue(healed['delivery']['lastFailureAt'])
        self.assertEqual(len(self.project()['nodes']), 2)
        self.assertEqual(len(self.project()['edges']), 1)

    def test_reference_only_capture_executes_once_even_if_reference_missing(self):
        marker = self.root / 'marker.txt'
        import sys
        args = ('execute', '--project', 'study', '--question', 'question-missing',
                '--title', 'Real command', '--request-id', 'one-command', '--', sys.executable,
                '-c', 'from pathlib import Path; p=Path("marker.txt"); p.write_text(p.read_text()+"x" if p.exists() else "x")')
        self.client.offline = True
        self.invoke(*args)
        self.client.offline = False
        self.invoke('sync', '--project', 'study')
        self.invoke(*args)
        self.assertEqual(marker.read_text(), 'x')
        self.assertEqual(self.project()['nodes'], [])
        self.assertEqual(self.project()['runs'], [])
        self.assertEqual(self.tasks()[0]['delivery']['lastError']['code'], 'unresolved_reference')

    def test_natural_hyphenated_question_is_still_prose(self):
        _, result = self.invoke('event', '--project', 'study', '--question', 'cross-validation')
        self.assertFalse(result['pending'])
        self.assertEqual(self.project()['nodes'][0]['title'], 'cross-validation')

    def test_status_is_local_only_after_reference_failure(self):
        self.client.offline = True
        self.invoke('event', '--project', 'study', '--question', 'node-unresolved', '--finding', 'Saved finding')
        with patch.object(self.client, 'request', side_effect=AssertionError('status must stay offline')):
            _, status = self.invoke('status', '--project', 'study')
        self.assertEqual(status['pendingCount'], 1)
        self.assertEqual(status['blockedCount'], 1)
        self.assertFalse(status['transportChecked'])
