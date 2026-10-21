import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from backend.store import CHECKPOINT_INTERVAL, Store, StoreError, canonical


class SQLiteStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Study', 'sourceRoots': [str(self.root)]})
        self.edit([{'op': 'node.add', 'data': {'id': 'a'}}])

    def tearDown(self):
        self.temp.cleanup()

    def edit(self, operations, **extra):
        return self.store.batch('study', {'operations': operations, **extra})

    def test_small_edits_store_deltas_and_periodic_checkpoints(self):
        payload = 'UNCHANGED-PAYLOAD-' * 16000
        self.edit([{'op': 'node.update', 'data': {'id': 'a', 'notes': payload}}])
        snapshots = {}
        for index in range(110):
            result = self.edit([{'op': 'node.update', 'data': {'id': 'a', 'title': f'Revision {index}'}}])
            snapshots[result['revision']] = result
        with closing(sqlite3.connect(self.store.database)) as db:
            count, checkpoints, delta_bytes = db.execute('SELECT COUNT(*), COUNT(checkpoint), SUM(LENGTH(delta)) FROM versions').fetchone()
            self.assertEqual(checkpoints, 1 + count // CHECKPOINT_INTERVAL)
            self.assertLess(delta_bytes, len(payload) * 2)
            self.assertIsNone(db.execute('SELECT checkpoint FROM versions WHERE revision = 4').fetchone()[0])
        self.assertFalse((self.store.root / 'study/state.json').exists())
        # Exact retry results cross multiple checkpoints without re-generating IDs or times.
        for revision in (4, 49, 50, 51, 99, 100, 101, 113):
            with self.store._transaction() as db:
                self.assertEqual(self.store._revision(db, 'study', revision), snapshots[revision])

    def test_current_reads_and_project_list_do_not_read_history(self):
        current = self.edit([{'op': 'node.update', 'data': {'id': 'a', 'notes': 'current data'}}])
        with closing(sqlite3.connect(self.store.database)) as db:
            db.execute("UPDATE versions SET delta = 'invalid JSON', checkpoint = 'invalid JSON'")
            db.commit()
        self.assertEqual(self.store.get_project('study'), current)
        summary = self.store.list_projects()
        self.assertEqual(summary[0]['revision'], current['revision'])
        self.assertEqual(summary[0]['nodeCount'], 1)
        self.assertEqual(len(self.store.history('study')), current['revision'])

    def test_changes_keep_order_unknown_fields_and_json_value_types(self):
        initial = self.edit([
            {'op': 'project.update', 'data': {'custom': {'settings': [1, 2, 3]}}},
            {'op': 'node.add', 'data': {'id': 'b'}},
            {'op': 'node.add', 'data': {'id': 'c'}},
            {'op': 'run.add', 'data': {'id': 'r', 'nodeId': 'b', 'metrics': {'score': 1}}},
        ], requestId='initial')
        changed = self.edit([
            {'op': 'project.update', 'data': {'custom': {'settings': [True], 'new': None}}},
            {'op': 'node.delete', 'data': {'id': 'a'}},
            {'op': 'run.update', 'data': {'id': 'r', 'metrics': {'score': True}}},
            {'op': 'run.event', 'data': {'runId': 'r', 'event': {'message': 'Generated event identity'}}},
        ], requestId='changed')
        loaded = Store(self.store.root).get_project('study')
        self.assertEqual(loaded, changed)
        self.assertIs(loaded['runs'][0]['metrics']['score'], True)
        self.assertIs(loaded['custom']['settings'][0], True)
        self.assertEqual([n['id'] for n in loaded['nodes']], ['b', 'c'])
        restored = self.store.restore('study', {'revision': initial['revision'], 'expectedRevision': changed['revision']})
        self.assertEqual(restored['nodes'], initial['nodes'])
        self.assertEqual(restored['custom'], initial['custom'])
        retried = self.store.batch('study', {'requestId': 'changed', 'operations': [
            {'op': 'project.update', 'data': {'custom': {'settings': [True], 'new': None}}},
            {'op': 'node.delete', 'data': {'id': 'a'}},
            {'op': 'run.update', 'data': {'id': 'r', 'metrics': {'score': True}}},
            {'op': 'run.event', 'data': {'runId': 'r', 'event': {'message': 'Generated event identity'}}},
        ]})
        self.assertEqual(retried, changed)

    def test_failed_commit_rolls_back_metadata_history_and_evidence(self):
        before = self.store.get_project('study')
        source = self.root / 'evidence.txt'
        source.write_bytes(b'preserve exact bytes')
        # Fail at COMMIT, after the retained file and SQL changes have been installed.
        with closing(sqlite3.connect(self.store.database)) as db:
            db.executescript('CREATE TABLE deferred_failure (id TEXT REFERENCES projects(id) DEFERRABLE INITIALLY DEFERRED); '
                             "CREATE TRIGGER fail_commit AFTER INSERT ON versions BEGIN INSERT INTO deferred_failure VALUES ('missing'); END;")
        with self.assertRaises(StoreError) as raised:
            self.store.register_artifact('study', {'path': str(source), 'nodeId': 'a'})
        self.assertEqual(raised.exception.code, 'storage_error')
        self.assertEqual(self.store.get_project('study'), before)
        self.assertEqual(len(self.store.history('study')), before['revision'])
        self.assertEqual(list((self.store.root / 'study/evidence').iterdir()), [])

    def test_windows_device_names_and_retained_paths_are_portable(self):
        for project_id in ('CON', 'con.txt', 'study.', 'study', 'a' * 127 + '.'):
            if project_id != 'study':
                self.store.create_project({'id': project_id, 'name': project_id, 'sourceRoots': [str(self.root)]})
            source = self.root / 'source.txt'
            source.write_bytes(b'portable evidence')
            artifact = self.store.register_artifact(project_id, {'id': 'NUL', 'path': str(source)})
            self.assertEqual(self.store.artifact_content(project_id, artifact['id'])[0], source.read_bytes())
            self.assertFalse(Path(artifact['path']).name.upper().startswith('NUL.'))
        self.assertNotEqual(self.store._dir('study.'), self.store._dir('study'))
        artifact = self.store.register_artifact('study', {'id': 'cross-host', 'path': str(source)})
        imported = self.store.get_project('study')
        imported['artifacts'][-1]['path'] = 'C:\\Users\\researcher\\evidence\\cross-host.txt'
        imported['sourceRoots'] = ['C:\\Users\\researcher\\study']
        other = Store(self.root / 'other')
        other.import_project(imported)
        location = other.root / 'study/evidence/cross-host.txt'
        location.parent.mkdir(parents=True)
        location.write_bytes(source.read_bytes())
        self.assertEqual(other.artifact_content('study', 'cross-host')[0], source.read_bytes())

    def test_restore_and_id_reuse_cannot_overwrite_historical_evidence(self):
        before = self.store.get_project('study')
        source = self.root / 'result.TXT'
        source.write_bytes(b'original evidence')
        artifact = self.store.register_artifact('study', {'id': 'proof', 'path': str(source), 'nodeId': 'a'})
        recorded = self.store.get_project('study')
        reverted = self.store.restore('study', {'revision': before['revision'], 'expectedRevision': recorded['revision']})
        source = self.root / 'replacement.txt'
        source.write_bytes(b'replacement evidence')
        with self.assertRaises(StoreError) as raised:
            self.store.register_artifact('study', {'id': 'proof', 'path': str(source), 'nodeId': 'a'})
        self.assertEqual(raised.exception.code, 'conflict')
        self.assertEqual(self.store.get_project('study'), reverted)
        restored = self.store.restore('study', {'revision': recorded['revision'], 'expectedRevision': reverted['revision']})
        self.assertEqual(restored['artifacts'], recorded['artifacts'])
        self.assertEqual(self.store.artifact_content('study', artifact['id'])[0], b'original evidence')

    def test_case_only_ids_have_distinct_portable_evidence_locations(self):
        locations = []
        for project_id in ('Case', 'case'):
            self.store.create_project({'id': project_id, 'name': project_id, 'sourceRoots': [str(self.root)]})
            for artifact_id in ('Proof', 'proof'):
                source = self.root / 'result.txt'
                content = (project_id + ':' + artifact_id).encode()
                source.write_bytes(content)
                artifact = self.store.register_artifact(project_id, {'id': artifact_id, 'path': str(source)})
                locations.append(artifact['path'].casefold())
        self.assertEqual(len(set(locations)), 4)
        for project_id in ('Case', 'case'):
            for artifact_id in ('Proof', 'proof'):
                self.assertEqual(self.store.artifact_content(project_id, artifact_id)[0], (project_id + ':' + artifact_id).encode())

    def test_migration_encodes_old_directories_and_retains_deleted_evidence(self):
        data = self.root / 'json-data'
        folder = data / 'CON'
        # Windows cannot create the old device-name directory; migrate from an ordinary
        # folder there while still checking the logical ID and old artifact filename.
        if os.name == 'nt':
            folder = data / 'original'
        (folder / 'evidence').mkdir(parents=True)
        original_file = folder / 'evidence/Proof.txt'
        original_file.write_bytes(b'historical evidence')
        before = self.store.get_project('study')
        before['id'] = 'CON'
        registered = copy.deepcopy(before)
        registered['revision'] += 1
        registered['artifacts'] = [{'id': 'Proof', 'nodeId': 'a', 'runId': None, 'title': 'Evidence', 'path': str(original_file),
                                    'sha256': hashlib.sha256(original_file.read_bytes()).hexdigest(), 'bytes': original_file.stat().st_size,
                                    'origin': 'observed', 'mime': 'text/plain'}]
        deleted = copy.deepcopy(registered)
        deleted['revision'] += 1
        deleted['nodes'], deleted['artifacts'] = [], []
        snapshots = [before, registered, deleted]
        bundle = {'project': deleted, 'requests': {}, 'history': [
            {'revision': item['revision'], 'at': item['updatedAt'], 'operations': [{'op': 'project.import'}], 'snapshot': item}
            for item in snapshots]}
        original_json = canonical(bundle).encode('utf-8')
        (folder / 'state.json').write_bytes(original_json)
        migrated = Store(data)
        self.assertEqual(migrated.get_project('CON'), deleted)
        migrated.restore('CON', {'revision': registered['revision'], 'expectedRevision': deleted['revision']})
        self.assertEqual(migrated.artifact_content('CON', 'Proof')[0], b'historical evidence')
        self.assertNotEqual(Path(migrated.artifact_metadata('CON', 'Proof')['path']), original_file)
        self.assertEqual(original_file.read_bytes(), b'historical evidence')
        self.assertEqual((folder / 'state.json').read_bytes(), original_json)

    def json_bundle(self):
        first = self.store.get_project('study')
        request = {'requestId': 'migrated-request', 'operations': [{'op': 'observation.start', 'data': {'nodeId': 'a'}}]}
        second = self.store.batch('study', request)
        fingerprint = hashlib.sha256(canonical(request['operations']).encode()).hexdigest()
        entries = [
            {'revision': first['revision'], 'at': first['updatedAt'], 'operations': [{'op': 'project.import'}], 'snapshot': first},
            {'revision': second['revision'], 'at': second['updatedAt'], 'operations': [{'op': 'observation.start'}], 'snapshot': second},
        ]
        return {'project': second, 'history': entries, 'requests': {'migrated-request': {'revision': second['revision'], 'fingerprint': fingerprint}}}, request

    def test_json_migration_preserves_history_retries_and_original_file(self):
        bundle, request = self.json_bundle()
        folder = self.root / 'json-data/study'
        folder.mkdir(parents=True)
        original = (canonical(bundle) + '\n').encode('utf-8')
        (folder / 'state.json').write_bytes(original)
        migrated = Store(folder.parent)
        self.assertEqual(migrated.get_project('study'), bundle['project'])
        self.assertEqual(migrated.batch('study', request), bundle['project'])
        current = migrated.batch('study', {'operations': [{'op': 'node.update', 'data': {'id': 'a', 'title': 'after migration'}}]})
        self.assertEqual(migrated.batch('study', request), bundle['project'])
        restored = migrated.restore('study', {'revision': bundle['history'][0]['revision'], 'expectedRevision': current['revision']})
        self.assertEqual(restored['nodes'], bundle['history'][0]['snapshot']['nodes'])
        self.assertEqual((folder / 'state.json').read_bytes(), original)
        self.assertEqual(Store(folder.parent).get_project('study'), restored)

    def test_failed_json_migration_is_atomic_and_can_be_retried(self):
        bundle, _ = self.json_bundle()
        data = self.root / 'json-data'
        good = data / 'a/state.json'
        bad = data / 'z/state.json'
        good.parent.mkdir(parents=True)
        bad.parent.mkdir(parents=True)
        good.write_text(canonical(bundle), encoding='utf-8')
        bad.write_text('{broken', encoding='utf-8')
        with self.assertRaises(StoreError) as raised:
            Store(data)
        self.assertEqual(raised.exception.code, 'migration_error')
        with closing(sqlite3.connect(data / 'records.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM projects').fetchone()[0], 0)
        bad.unlink()
        recovered = Store(data)
        self.assertEqual(recovered.get_project('study'), bundle['project'])


if __name__ == '__main__':
    unittest.main()