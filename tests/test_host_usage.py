"""Host usage is measured once; attribution requires explicit, bounded evidence."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.host_usage import HappySQLiteAdapter, HostUsageImporter, active_intervals, attribute, cli_projects, iso_time
from backend.recovery import Recovery
from backend.store import Store, StoreError


class HostUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='host usage 研究 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.research = self.root / 'research'
        self.research.mkdir()
        self.store = Store(self.root / 'application')
        self.store.create_project({'id': 'study', 'name': 'Study', 'sourceRoots': [str(self.research)]})
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'a', 'status': 'completed'}}]})
        self.database = self.root / 'host.sqlite'
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE happy_agent_module_history (agent_id TEXT, record_id TEXT, role TEXT, run_id TEXT, message_json TEXT, tool_calls INTEGER)')
            db.execute('CREATE TABLE happy_agent_usage_records (agent_id TEXT, record_id TEXT, kind TEXT, run_id TEXT, record_json TEXT, finished_at INTEGER)')
            # These are deliberately irrelevant; the adapter must not use a
            # cumulative total, a descendant total, or credentials as usage.
            db.execute('CREATE TABLE happy_agent_usage_model_totals (input_tokens INTEGER)')
            db.execute('INSERT INTO happy_agent_usage_model_totals VALUES (999999999)')
            db.execute('CREATE TABLE secrets (value TEXT)')
        self.adapter = HappySQLiteAdapter(self.database)
        self.importer = HostUsageImporter(self.store, [self.adapter], interval=0, url='http://127.0.0.1:4317')

    def call(self, agent='research-agent', project='study', *, cmd=None, workdir=None):
        block = {'type': 'tool_call', 'callId': 'call-' + agent, 'name': 'exec_command',
                 'arguments': {'cmd': cmd or f'python3 /installed/exp_observer.py record --project {project} --title Result',
                               'workdir': str(self.research) if workdir is None else workdir}}
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT INTO happy_agent_module_history VALUES (?,?,?,?,?,?)',
                       (agent, 'message-' + agent, 'assistant', 'host-run', json.dumps({'blocks': [block]}), 1))

    def inference(self, key='response-1', *, agent='research-agent', start=11000, end=12000, kind='inference', tokens=None):
        raw = {'id': key, 'agentId': agent, 'runId': 'host-run', 'kind': kind, 'provider': 'codex', 'model': 'gpt-test',
               'startedAt': start, 'finishedAt': end, 'tokens': tokens if tokens is not None else
               {'input': 100, 'output': 7, 'cacheRead': 80, 'cacheWrite': 0}}
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT INTO happy_agent_usage_records VALUES (?,?,?,?,?,?)',
                       (agent, key, kind, 'host-run', json.dumps(raw), end))
        return raw

    def capture(self, key, node, status, at, *, command='record'):
        outbox = self.research / '.exp-observer-runs' / 'outbox'
        outbox.mkdir(parents=True, exist_ok=True)
        task = {'version': 1, 'url': 'http://127.0.0.1:4317', 'state': 'synced', 'projectId': 'study', 'intent': {'command': command},
                'nodeId': node, 'captureRoot': str(self.research / '.exp-observer-runs' / 'study'),
                'capturedAt': iso_time(at), 'finishedAt': iso_time(at),
                'operations': [{'op': 'node.update', 'data': {'id': node, 'status': status}}]}
        Path(task['captureRoot']).mkdir(exist_ok=True)
        (outbox / (key + '.json')).write_text(json.dumps(task))
        return outbox

    def test_windows_python_options_and_quoted_paths_are_recognized(self):
        for cmd in [
            r'python.exe -X utf8 -B C:\skills\exp_observer.py event --project study',
            r'& "C:\Program Files\Python\python.exe" -X utf8 -B "C:\Agent Skills\exp_observer.py" event --project study',
            r'py.exe -3.12 -Xutf8 -W ignore C:\skills\exp_observer.py record --project study',
            'python3 -X utf8 -B /skill/exp_observer.py event --project study',
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(cli_projects(cmd), {'study'})
        for cmd in [
            r'python.exe -X utf8 -c "print(1)" C:\skills\exp_observer.py event --project study',
            r'python.exe -m other exp_observer.py event --project study',
            r'Write-Output "python.exe -X utf8 C:\skills\exp_observer.py event --project study"',
        ]:
            self.assertEqual(cli_projects(cmd), set())

    def test_only_actual_top_level_cli_commands_bind(self):
        actual = "find . -maxdepth 1\npython3 /installed/exp_observer.py record --project study --title '字形研究'\npython3 /installed/exp_observer.py execute --project study -- python3 run.py"
        self.assertEqual(cli_projects(actual), {'study'})
        for diagnostic in [
            "python3 -c 'print(\"exp_observer.py record --project study\")'",
            "echo 'python3 exp_observer.py execute --project study'",
            "cat <<'PY'\npython3 exp_observer.py record --project study\nPY",
            "python3 scripts/diagnose.py --title exp_observer.py --project study",
            "python3 exp_observer.py execute --project study -- echo --project other",
        ]:
            with self.subTest(diagnostic=diagnostic):
                expected = {'study'} if diagnostic.startswith('python3 exp_observer.py execute') else set()
                self.assertEqual(cli_projects(diagnostic), expected)

    def test_imports_own_inference_records_preserving_cache_and_deduplicating(self):
        self.call()
        self.inference()
        self.inference('response-2', tokens={'input': 0, 'output': 2, 'cacheRead': None, 'cacheWrite': 1})
        self.inference('turn-summary', kind='turn', tokens={'input': 999999})
        self.inference('unbound-child-response', agent='child-agent')
        result = self.importer.drain_once()
        self.assertEqual(result[0]['imported'], 2)
        project = self.store.get_project('study')
        records = project['usageRecords']
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['inputTokens'], 100)
        self.assertEqual(records[0]['cacheReadTokens'], 80)
        self.assertEqual(records[0]['cacheWriteTokens'], 0)
        self.assertEqual(records[1]['inputTokens'], 0)
        self.assertIsNone(records[1]['cacheReadTokens'])
        self.assertTrue(all(r['nodeId'] is None for r in records))
        self.assertTrue(all(r['agentId'] == 'research-agent' for r in records))
        self.assertEqual(self.importer.drain_once(), [])
        self.assertEqual(self.store.get_project('study'), project)
        self.inference('response-3')
        self.assertEqual(self.importer.drain_once()[0]['imported'], 1)
        self.assertEqual(len(Store(self.root / 'application').get_project('study')['usageRecords']), 3)

    def test_diagnostic_agent_and_wrong_working_directory_cannot_bind(self):
        self.call(agent='operator', cmd="python3 -c 'print(\"exp_observer.py record --project study\")'")
        self.call(agent='outside', workdir=str(self.root))
        self.call(agent='unknown-directory', workdir='')
        for agent in ('operator', 'outside', 'unknown-directory'):
            self.inference(agent, agent=agent)
        self.assertEqual(self.importer.drain_once(), [])
        self.assertEqual(self.store.get_project('study')['usageRecords'], [])

    def test_agent_using_two_projects_is_not_guessed(self):
        self.call()
        self.call(project='another-project')
        self.inference()
        self.assertEqual(self.importer.drain_once(), [])
        self.assertEqual(self.store.get_project('study')['usageRecords'], [])

    def test_explicit_foreign_observer_does_not_bind_same_project_id(self):
        self.call(cmd='python3 /installed/exp_observer.py --url http://127.0.0.1:9999 record --project study --title Foreign')
        self.inference()
        self.assertEqual(self.importer.drain_once(), [])
        self.assertEqual(self.store.get_project('study')['usageRecords'], [])

    def test_agent_using_same_project_id_on_two_observers_remains_unbound(self):
        self.call()
        self.call(cmd='python3 /installed/exp_observer.py --url=http://127.0.0.1:9999 record --project study --title Foreign')
        self.inference()
        self.assertEqual(self.importer.drain_once(), [])
        self.assertEqual(self.store.get_project('study')['usageRecords'], [])

    def test_temporary_observer_requires_its_explicit_url_and_supports_both_spellings(self):
        url = 'http://127.0.0.1:57541'
        self.importer = HostUsageImporter(self.store, [HappySQLiteAdapter(self.database, url=url)], interval=0, url=url)
        for option in ('--url ' + url, '--url=' + url):
            self.call(cmd='python3 /installed/exp_observer.py ' + option + ' record --project study --title Local')
        # A default-URL call is evidence for 4317, never an inferred environment
        # override to the temporary observer's port.
        self.call(agent='default-url-agent')
        self.inference()
        self.inference('default-response', agent='default-url-agent')
        self.assertEqual(self.importer.drain_once()[0]['imported'], 1)
        self.assertEqual({r['agentId'] for r in self.store.get_project('study')['usageRecords']}, {'research-agent'})
        default_importer = HostUsageImporter(self.store, interval=0, url=url)
        self.assertEqual(default_importer.adapters[0].url, url)

    def test_staged_evidence_root_only_derives_owner_inside_connected_workspace(self):
        stage = self.research / '.exp-observer-runs' / 'study'
        stage.mkdir(parents=True)
        self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'sourceRoots': [str(stage)]}}]})
        self.call()
        self.inference()
        self.assertEqual(self.importer.drain_once(), [])
        self.store.add_workspace({'path': str(self.research)})
        self.assertEqual(self.importer.drain_once()[0]['imported'], 1)
        self.assertEqual(self.store.get_project('study')['sourceRoots'], [str(stage)])

    def test_text_only_capture_proves_binding_without_artifacts_or_source_roots(self):
        self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'sourceRoots': []}}]})
        self.store.add_workspace({'path': str(self.research)})
        self.call()
        self.inference()
        outbox = self.capture('active', 'a', 'active', 10000)
        self.capture('completed', 'a', 'completed', 20000)
        result = self.importer.drain_once([outbox])
        self.assertEqual(result[0]['imported'], 1)
        project = self.store.get_project('study')
        self.assertEqual(project['sourceRoots'], [])
        self.assertEqual(project['artifacts'], [])
        self.assertEqual(project['usageRecords'][0]['nodeId'], 'a')
        self.assertEqual(project['usageRecords'][0]['attribution'], 'unique-active-interval')
        self.assertEqual(self.importer.drain_once([outbox]), [])

    def test_native_text_capture_requires_connected_synced_same_observer_and_existing_node(self):
        self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'sourceRoots': []}}]})
        self.call()
        self.inference()
        outbox = self.capture('active', 'a', 'active', 10000)
        path = outbox / 'active.json'
        original = json.loads(path.read_text())
        self.assertEqual(self.importer.drain_once([outbox]), [])
        self.store.add_workspace({'path': str(self.research)})
        for changes in ({'state': 'ready'}, {'url': 'http://127.0.0.1:9999'}, {'nodeId': 'missing'},
                        {'version': 2}, {'intent': {'command': 'status'}}, {'operations': []},
                        {'captureRoot': str(self.research / 'unrelated')}):
            with self.subTest(changes=changes):
                path.write_text(json.dumps({**original, **changes}))
                self.assertEqual(self.importer.drain_once([outbox]), [])
        self.assertEqual(self.store.get_project('study')['usageRecords'], [])

    def test_staged_source_symlink_cannot_broaden_binding_scope(self):
        stage = self.research / '.exp-observer-runs' / 'study'
        stage.mkdir(parents=True)
        alias = self.root / 'linked research'
        try:
            alias.symlink_to(self.research, target_is_directory=True)
        except OSError:
            self.skipTest('Symlinks unavailable')
        self.store.add_workspace({'path': str(self.root)})
        self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'sourceRoots': [str(alias / '.exp-observer-runs' / 'study')]}}]})
        self.call()
        self.inference()
        self.assertEqual(self.importer.drain_once(), [])

    def test_only_complete_unique_active_intervals_receive_attribution(self):
        self.call()
        self.inference()
        self.inference('crosses-start', start=9000, end=11000)
        self.inference('crosses-end', start=19000, end=21000)
        self.inference('after-finish', start=21000, end=22000)
        outbox = self.capture('active', 'a', 'active', 10000)
        self.capture('finished', 'a', 'completed', 20000)
        self.importer.drain_once([outbox])
        records = self.store.get_project('study')['usageRecords']
        self.assertEqual({r['sourceRef']: r['nodeId'] for r in records},
                         {'response-1': 'a', 'crosses-start': None, 'crosses-end': None, 'after-finish': None})
        self.assertEqual(records[1]['attribution'], 'unique-active-interval')
        self.assertNotEqual(self.store.get_project('study')['nodes'][0]['createdAt'], iso_time(10000))
        # Later evidence of concurrent active work must remove an earlier
        # attribution without adding or changing the measured token record.
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'b', 'status': 'completed'}}]})
        self.capture('b-active', 'b', 'active', 10500)
        self.capture('b-finished', 'b', 'completed', 11500)
        result = self.importer.drain_once([outbox])
        self.assertEqual(result[0]['imported'], 0)
        self.assertEqual(result[0]['updated'], 1)
        self.assertTrue(all(r['nodeId'] is None for r in self.store.get_project('study')['usageRecords']))

    def test_completed_execute_does_not_invent_active_model_interval(self):
        self.call()
        self.inference()
        outbox = self.capture('execution', 'a', 'completed', 20000, command='execute')
        self.assertEqual(active_intervals(self.store.get_project('study'), [outbox]), [])
        self.importer.drain_once([outbox])
        self.assertIsNone(self.store.get_project('study')['usageRecords'][0]['nodeId'])

    def test_event_cli_binds_and_ensure_only_creates_first_activity_interval(self):
        self.call(cmd='python3 /installed/exp_observer.py event --project study --question Question')
        self.inference()
        self.inference('before-real-finish', start=16000, end=17000)
        self.inference('after-completed', start=31000, end=32000)
        outbox = self.capture('create', 'a', 'active', 10000, command='event')
        self.capture('premature-ensure', 'a', 'completed', 15000, command='event')
        self.capture('finish', 'a', 'completed', 20000)
        self.capture('later-ensure', 'a', 'active', 30000, command='event')
        self.capture('still-completed', 'a', 'completed', 40000)
        for name in ('create', 'premature-ensure', 'later-ensure'):
            path = outbox / (name + '.json')
            task = json.loads(path.read_text())
            task['operations'][0]['op'] = 'node.ensure'
            path.write_text(json.dumps(task))
        self.importer.drain_once([outbox])
        self.assertEqual({r['sourceRef']: r['nodeId'] for r in self.store.get_project('study')['usageRecords']},
                         {'response-1': 'a', 'before-real-finish': 'a', 'after-completed': None})

    def test_synced_event_ensure_proves_text_only_workspace_owner(self):
        self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'sourceRoots': []}}]})
        self.store.add_workspace({'path': str(self.research)})
        self.call(cmd='python3 /installed/exp_observer.py event --project study --question Question')
        self.inference()
        outbox = self.capture('ensure', 'a', 'completed', 20000, command='event')
        path = outbox / 'ensure.json'
        task = json.loads(path.read_text())
        task['operations'][0]['op'] = 'node.ensure'
        path.write_text(json.dumps(task))
        self.assertEqual(self.importer.drain_once([outbox])[0]['imported'], 1)
        record = self.store.get_project('study')['usageRecords'][0]
        self.assertIsNone(record['nodeId'])
        self.assertEqual(record['scope'], 'agent')

    def test_foreign_observer_urls_and_other_source_directories_cannot_attribute(self):
        self.call()
        self.inference()
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'b', 'status': 'completed'}}]})
        outbox = self.capture('a-active', 'a', 'active', 10000)
        self.capture('a-finished', 'a', 'completed', 20000)
        outside = self.root / 'other research' / '.exp-observer-runs' / 'outbox'
        outside.mkdir(parents=True)
        for key, status, at in [('b-active', 'active', 10000), ('b-finished', 'completed', 20000)]:
            self.capture(key, 'b', status, at)
            path = outbox / (key + '.json')
            task = json.loads(path.read_text())
            (outside / path.name).write_text(json.dumps(task))
            task['url'] = 'http://127.0.0.1:9999'
            path.write_text(json.dumps(task))
        self.importer.drain_once([outbox, outside])
        record = self.store.get_project('study')['usageRecords'][0]
        self.assertEqual(record['nodeId'], 'a')
        self.assertEqual(record['attribution'], 'unique-active-interval')

    def test_unreadable_activity_evidence_keeps_measured_project_usage(self):
        self.call()
        self.inference()
        outbox = self.capture('active', 'a', 'active', 10000)
        (outbox / 'incomplete.json').write_text('{')
        result = self.importer.drain_once([outbox])
        self.assertTrue(result[0]['pending'])
        self.assertEqual(result[1]['imported'], 1)
        record = self.store.get_project('study')['usageRecords'][0]
        self.assertEqual(record['inputTokens'], 100)
        self.assertIsNone(record['nodeId'])

    def test_missing_or_incompatible_optional_host_is_soft_and_generic_adapter_works(self):
        self.assertEqual(HostUsageImporter(self.store, [HappySQLiteAdapter(self.root / 'absent')], interval=0).drain_once(), [])
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DROP TABLE happy_agent_usage_records')
        result = self.importer.drain_once()
        self.assertTrue(result[0]['pending'])
        self.assertIn('Optional host usage', result[0]['recordingWarnings'][0])
        store = self.store
        class OtherRuntime:
            source = 'other-runtime'
            def read(self, projects):
                return {'study': [{'id': 'other-response', 'nodeId': None, 'source': self.source, 'sourceRef': 'unique-response',
                                   'provider': 'local', 'model': 'measured-model', 'inputTokens': 2, 'outputTokens': 0,
                                   'cacheReadTokens': None, 'cacheWriteTokens': None,
                                   'startedAt': iso_time(11000), 'finishedAt': iso_time(12000)}]}
        self.assertEqual(HostUsageImporter(store, [OtherRuntime()], interval=0).drain_once()[0]['imported'], 1)

    def test_counter_identity_changes_rollback_and_research_commands_cannot_fill_host_usage(self):
        self.call()
        self.inference()
        self.importer.drain_once()
        before = self.store.get_project('study')
        changed = deepcopy(before['usageRecords'][0])
        changed['inputTokens'] += 1
        with self.assertRaises(StoreError):
            self.store.import_usage_records('study', [changed])
        self.assertEqual(self.store.get_project('study'), before)
        self.store.batch('study', {'operations': [{'op': 'project.update', 'data': {'usageRecords': []}}]})
        self.assertEqual(self.store.get_project('study')['usageRecords'], before['usageRecords'])
        with self.assertRaises(StoreError):
            self.store.batch('study', {'operations': [{'op': 'usage.add', 'data': changed}]})

    def test_deletion_and_restore_keep_actual_host_consumption(self):
        self.call()
        self.inference()
        outbox = self.capture('active', 'a', 'active', 10000)
        self.capture('finished', 'a', 'completed', 20000)
        self.importer.drain_once([outbox])
        measured = self.store.get_project('study')['usageRecords'][0]
        self.assertEqual(measured['nodeId'], 'a')
        self.store.batch('study', {'operations': [{'op': 'node.delete', 'data': {'id': 'a'}}]})
        project = self.store.get_project('study')
        self.assertEqual(len(project['usageRecords']), 1)
        self.assertIsNone(project['usageRecords'][0]['nodeId'])
        restored = self.store.restore('study', {'revision': 1, 'expectedRevision': project['revision']})
        self.assertEqual(restored['usageRecords'], project['usageRecords'])

    def test_merge_moves_usage_without_changing_measured_identity_or_counters(self):
        self.call()
        self.inference()
        outbox = self.capture('active', 'a', 'active', 10000)
        self.capture('finished', 'a', 'completed', 20000)
        self.importer.drain_once([outbox])
        before = self.store.get_project('study')['usageRecords'][0]
        self.store.batch('study', {'operations': [
            {'op': 'node.add', 'data': {'id': 'target', 'status': 'completed'}},
            {'op': 'node.merge', 'data': {'id': 'a', 'target': 'target'}}]})
        after = self.store.get_project('study')['usageRecords'][0]
        self.assertEqual(after, {**before, 'nodeId': 'target'})
        self.assertEqual(self.importer.drain_once([outbox]), [])

    def test_merge_preserves_overlapping_original_active_intervals_and_later_usage(self):
        self.call()
        self.inference(start=21000, end=24000)
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'b', 'status': 'completed'}}]})
        outbox = self.capture('a-start', 'a', 'active', 10000)
        self.capture('b-start', 'b', 'active', 15000)
        self.capture('a-end', 'a', 'completed', 20000)
        self.capture('b-end', 'b', 'completed', 25000)
        self.importer.drain_once([outbox])
        record = self.store.get_project('study')['usageRecords'][0]
        self.assertEqual(record['nodeId'], 'b')
        self.store.batch('study', {'operations': [{'op': 'node.merge', 'data': {'id': 'b', 'target': 'a'}}]})
        merged = self.store.get_project('study')
        self.assertEqual(merged['usageRecords'][0], {**record, 'nodeId': 'a'})
        self.assertEqual(active_intervals(merged, [outbox], self.importer.url), [('a', 10.0, 25.0)])
        self.assertEqual(self.importer.drain_once([outbox]), [])
        self.assertEqual(self.store.get_project('study'), merged)

    def test_restarting_importer_does_not_increment_revision_or_duplicate_records(self):
        self.call()
        self.inference()
        self.importer.drain_once()
        before = self.store.get_project('study')
        restarted = HostUsageImporter(Store(self.root / 'application'), [HappySQLiteAdapter(self.database)], interval=0)
        self.assertEqual(restarted.drain_once(), [])
        self.assertEqual(self.store.get_project('study'), before)

    def test_recovery_invokes_optional_import_without_network_or_research_commands(self):
        self.call()
        self.inference()
        recovery = Recovery('http://127.0.0.1:4317', self.root / 'legacy', store=self.store)
        self.addCleanup(recovery.stop)
        recovery.host_usage = self.importer
        self.assertEqual(recovery.drain_once()[0]['imported'], 1)
        self.assertEqual(recovery.drain_once(), [])


if __name__ == '__main__':
    unittest.main()