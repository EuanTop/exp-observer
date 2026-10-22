"""Explicit measured execution evidence stays separate from agent inference usage.

The fixture follows Codex SDK's documented ThreadEvent JSONL protocol. Its
synthetic counters test ingestion; they are not evidence for any user project.
"""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.execution_usage import CapturedUsageAdapter
from backend.host_usage import HostUsageImporter, iso_time
from backend.recovery import Recovery
from backend.store import Store


FIXTURE = Path(__file__).parent / 'fixtures' / 'codex-exec-usage.jsonl'


class ExecutionUsageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='execution usage 研究 ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store = Store(self.root / 'application')
        self.store.create_project({'id': 'study', 'name': 'Synthetic usage fixture', 'sourceRoots': [str(self.root)]})
        self.store.batch('study', {'operations': [
            {'op': 'node.add', 'data': {'id': 'a', 'status': 'completed'}},
            {'op': 'node.add', 'data': {'id': 'b', 'status': 'completed'}}]})
        self.adapter = CapturedUsageAdapter(self.store)
        self.importer = HostUsageImporter(self.store, [self.adapter], interval=0)

    def project(self):
        return self.store.get_project('study')

    def add_run(self, key='run-1', *, node='a', external=False, metrics=None, unknown_time=False):
        configuration = {'capturedExternalResult': True} if external else {'command': ['codex', 'exec', '--json', 'fixture task']}
        self.store.batch('study', {'operations': [{'op': 'run.add', 'data': {
            'id': key, 'nodeId': node, 'origin': 'observed', 'status': 'completed', 'configuration': configuration,
            'startedAt': None if unknown_time else iso_time(10000),
            'finishedAt': None if unknown_time else iso_time(20000), 'metrics': metrics or {}}}]})

    def evidence(self, key='stdout-1', *, run='run-1', content=None, suffix='.jsonl'):
        source = self.root / (key + suffix)
        source.write_bytes(FIXTURE.read_bytes() if content is None else content)
        artifact = self.store.register_artifact('study', {'id': key, 'nodeId': next(r['nodeId'] for r in self.project()['runs'] if r['id'] == run),
                                                        'runId': run, 'path': str(source)})
        return source, artifact

    def declaration(self, **overrides):
        return {'source': 'test-runtime', 'sourceRef': 'original-invocation-1', 'provider': 'local', 'model': 'test-model',
                'inputTokens': 100, 'outputTokens': 7, 'cacheReadTokens': 80, 'cacheWriteTokens': 0, **overrides}

    def test_native_turn_counters_direct_node_and_unknown_model(self):
        self.add_run()
        self.evidence()
        self.assertEqual(self.importer.drain_once()[0]['imported'], 2)
        records = self.project()['usageRecords']
        self.assertEqual([(r['inputTokens'], r['outputTokens'], r['cacheReadTokens'], r['cacheWriteTokens']) for r in records],
                         [(24763, 122, 24448, None), (31000, 250, 29000, 128)])
        self.assertEqual(records[1]['reasoningOutputTokens'], 64)
        self.assertEqual(sum(r['outputTokens'] for r in records), 372)
        for record in records:
            self.assertEqual((record['nodeId'], record['scope'], record['model']), ('a', 'execution', 'unknown'))
            self.assertEqual((record['startedAt'], record['finishedAt']), (iso_time(10000), iso_time(20000)))
            self.assertEqual(record['timestampScope'], 'execution')
            self.assertEqual(record['executionRunId'], 'run-1')
            self.assertEqual(record['evidenceArtifactId'], 'stdout-1')

    def test_repeated_artifact_and_restart_do_not_add_usage_or_revision(self):
        self.add_run()
        self.evidence()
        self.evidence('stdout-copy')
        self.importer.drain_once()
        before = self.project()
        self.assertEqual(len(before['usageRecords']), 2)
        self.assertEqual(self.importer.drain_once(), [])
        restarted = HostUsageImporter(self.store, [CapturedUsageAdapter(self.store)], interval=0)
        self.assertEqual(restarted.drain_once(), [])
        self.assertEqual(self.project(), before)

    def test_same_thread_resumed_in_distinct_execution_is_distinct_usage(self):
        self.add_run()
        self.evidence()
        self.add_run('run-2', node='b')
        self.evidence('stdout-2', run='run-2')
        self.importer.drain_once()
        records = self.project()['usageRecords']
        self.assertEqual(len(records), 4)
        self.assertEqual(len({r['sourceRef'] for r in records}), 4)
        self.assertEqual({r['executionRunId'] for r in records}, {'run-1', 'run-2'})

    def test_external_snapshot_cannot_invent_native_invocation_identity(self):
        self.add_run(external=True)
        self.evidence()
        self.assertEqual(self.importer.drain_once(), [])
        self.assertEqual(self.project()['usageRecords'], [])

    def test_explicit_namespace_and_stream_reference_original_execution_once(self):
        declaration = self.declaration()
        self.add_run(external=True, metrics={'expObserverUsage': {'version': 1, 'records': [declaration]}})
        self.evidence(content=(json.dumps({'type': 'expobserver.usage.v1', **declaration}) + '\n').encode())
        self.add_run('run-2', external=True)
        self.evidence('saved-again', run='run-2', content=json.dumps({'expObserverUsage': {'version': 1, 'records': [declaration]}}).encode())
        self.importer.drain_once()
        records = self.project()['usageRecords']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['sourceRef'], 'original-invocation-1')
        before = self.project()
        self.assertEqual(self.importer.drain_once(), [])
        self.assertEqual(self.project(), before)

    def test_shared_explicit_source_reference_on_two_nodes_remains_unassigned(self):
        metrics = {'expObserverUsage': {'version': 1, 'records': [self.declaration()]}}
        self.add_run(metrics=metrics)
        self.add_run('run-2', node='b', metrics=metrics)
        self.importer.drain_once()
        record = self.project()['usageRecords'][0]
        self.assertIsNone(record['nodeId'])
        self.assertEqual(record['attribution'], 'ambiguous-execution')
        before = self.project()
        self.assertEqual(self.importer.drain_once(), [])
        self.assertEqual(self.project(), before)

    def test_absent_execution_bounds_stay_unknown(self):
        self.add_run(unknown_time=True)
        self.evidence()
        self.importer.drain_once()
        self.assertEqual(len(self.project()['usageRecords']), 2)
        self.assertTrue(all(r['startedAt'] is None and r['finishedAt'] is None for r in self.project()['usageRecords']))

    def test_research_token_metrics_and_unframed_completion_are_ignored(self):
        self.add_run(metrics={'tokens': 999999, 'model': {'usage': {'inputTokens': 999999}}})
        self.evidence(content=b'{"type":"turn.completed","usage":{"input_tokens":999999,"output_tokens":1}}\n')
        self.assertEqual(self.importer.drain_once(), [])
        self.assertEqual(self.project()['usageRecords'], [])

    def test_invalid_declared_counters_fail_soft_and_do_not_block_valid_run(self):
        for index, overrides in enumerate(({'inputTokens': True}, {'outputTokens': -1}, {'counterKind': 'cumulative'}, {'scope': 'agent'})):
            self.add_run('bad-' + str(index), metrics={'expObserverUsage': {'version': 1, 'records': [self.declaration(**overrides)]}})
        self.add_run()
        self.evidence()
        result = self.importer.drain_once()
        self.assertEqual(sum(bool(r.get('pending')) for r in result), 4)
        self.assertEqual(len(self.project()['usageRecords']), 2)

    def test_retained_copy_survives_changed_original_and_tamper_is_soft(self):
        self.add_run()
        source, artifact = self.evidence()
        source.write_text('changed original source')
        self.importer.drain_once()
        before = self.project()['usageRecords']
        self.assertEqual(len(before), 2)
        Path(artifact['path']).write_text('tampered retained evidence')
        self.add_run('run-2', node='b')
        self.evidence('good-2', run='run-2')
        restarted = HostUsageImporter(self.store, [CapturedUsageAdapter(self.store)], interval=0)
        result = restarted.drain_once()
        self.assertTrue(any(r.get('pending') for r in result))
        self.assertEqual(self.project()['usageRecords'][:2], before)
        self.assertEqual(len(self.project()['usageRecords']), 4)

    def test_images_are_skipped_without_warning_or_verification_read(self):
        self.add_run()
        self.evidence(content=b'\x89PNG\r\n\xff', suffix='.png')
        with patch.object(self.store, 'artifact_content', side_effect=AssertionError('Binary evidence must be skipped')):
            self.assertEqual(self.importer.drain_once(), [])

    def test_optional_host_failure_cannot_block_execution_import(self):
        class UnavailableHost:
            source = 'unavailable-host'
            def read(self, projects):
                raise sqlite3.OperationalError('Unsupported optional schema')
        self.add_run()
        self.evidence()
        importer = HostUsageImporter(self.store, [UnavailableHost(), self.adapter], interval=0)
        results = importer.drain_once()
        self.assertTrue(results[0]['pending'])
        self.assertEqual(results[1]['imported'], 2)

    def test_agent_and_execution_scopes_keep_distinct_source_records(self):
        class OwnAgent:
            source = 'synthetic-agent'
            def read(self, projects):
                return {'study': [{'id': 'agent-response', 'nodeId': None, 'scope': 'agent',
                                   'source': self.source, 'sourceRef': 'agent-response', 'provider': 'local', 'model': 'agent-model',
                                   'inputTokens': 9, 'outputTokens': 3, 'cacheReadTokens': 0, 'cacheWriteTokens': None,
                                   'startedAt': iso_time(9000), 'finishedAt': iso_time(21000)}]}
        self.add_run()
        self.evidence()
        HostUsageImporter(self.store, [OwnAgent(), self.adapter], interval=0).drain_once()
        records = self.project()['usageRecords']
        self.assertEqual(len(records), 3)
        self.assertEqual(sum(r['inputTokens'] for r in records if r['scope'] == 'agent'), 9)
        self.assertEqual(sum(r['inputTokens'] for r in records if r['scope'] == 'execution'), 55763)

    def test_default_recovery_imports_retained_execution_without_running_commands(self):
        self.add_run()
        self.evidence()
        recovery = Recovery('http://127.0.0.1:4317', store=self.store, state_dir=self.root / 'state')
        with patch('backend.host_usage.HappySQLiteAdapter.read', return_value={}), \
             patch('subprocess.Popen', side_effect=AssertionError('Recovery must never rerun research')):
            result = recovery.drain_once()
        self.assertEqual(result[0]['imported'], 2)
        self.assertEqual(len(self.project()['usageRecords']), 2)

    def test_invalid_earlier_evidence_cannot_starve_later_valid_evidence(self):
        self.add_run()
        self.evidence('bad-first', content=b'\xff' * len(FIXTURE.read_bytes()), suffix='.txt')
        self.evidence('valid-second')
        with patch('backend.execution_usage.MAX_POLL_BYTES', len(FIXTURE.read_bytes()) + 1):
            first = self.importer.drain_once()
            self.assertTrue(first[0]['pending'])
            self.assertEqual(self.project()['usageRecords'], [])
            self.assertEqual(self.importer.drain_once()[0]['imported'], 2)

    def test_conflicting_explicit_reference_cannot_replace_original_counters(self):
        self.add_run(metrics={'expObserverUsage': {'version': 1, 'records': [self.declaration()]}})
        self.importer.drain_once()
        before = self.project()['usageRecords']
        self.add_run('run-2', metrics={'expObserverUsage': {'version': 1, 'records': [self.declaration(inputTokens=101)]}})
        result = self.importer.drain_once()
        self.assertTrue(any(r.get('pending') for r in result))
        self.assertEqual(self.project()['usageRecords'], before)

    def test_repeated_thread_header_is_not_treated_as_new_turn_sequence(self):
        self.add_run()
        self.evidence(content=FIXTURE.read_bytes() + b'\n' + FIXTURE.read_bytes())
        self.assertTrue(self.importer.drain_once()[0]['pending'])
        self.assertEqual(self.project()['usageRecords'], [])


if __name__ == '__main__':
    unittest.main()