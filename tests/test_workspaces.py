"""Application-enrolled roots recover sandbox-local queues without a user registry."""
import builtins
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend import server as server_module
from backend.recovery import Recovery, WorkspaceDiscovery
from backend.server import Server
from backend.store import Store, StoreError
from tests.test_capture import cli, working_directory


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='exp workspace 研究 ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'research'
        self.root.mkdir()
        self.data = self.base / 'application data'
        self.state = self.base / 'legacy state'
        environment = patch.dict(os.environ, {'EXP_OBSERVER_STATE_DIR': str(self.state)})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = Store(self.data)
        self.server = Server(('127.0.0.1', 0), self.store, recovery=True, recovery_interval=0.04)
        self.addCleanup(self.server.server_close)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

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
        self.fail('Enrolled workspace recovery did not complete')

    def request(self, route, body=None):
        request = Request(self.url + route, data=None if body is None else json.dumps(body).encode('utf-8'),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=2) as response:
            return json.loads(response.read())

    def offline(self, directory, *arguments, url=None):
        directory.mkdir(parents=True, exist_ok=True)
        client = cli.Client(url or self.url, timeout=0.1)
        def fail(*args, **kwargs):
            raise cli.ClientError('Offline', code='unavailable')
        client.request = fail
        args = cli.parser().parse_args(['--url', client.url, *arguments])
        results = []
        with working_directory(directory), patch.object(cli, 'emit', side_effect=results.append):
            code = getattr(cli, args.command)(client, args)
        self.assertEqual(code, 0)
        return results[-1]

    def test_workspace_api_is_persistent_idempotent_and_does_not_delete_research(self):
        self.start(automatic=False)
        self.assertEqual(self.request('/api/workspaces'), {'workspaces': []})
        marker = self.root / 'experiment.txt'
        marker.write_text('research remains')
        first = self.request('/api/workspaces', {'path': str(self.root)})['workspaces']
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]['path'], str(self.root))
        self.assertTrue(first[0]['addedAt'])
        self.assertEqual(self.request('/api/workspaces', {'path': str(self.root / '.')}), {'workspaces': first})
        self.assertEqual(Store(self.data).list_workspaces(), first)
        for invalid in ('.', str(marker), str(self.root / 'missing')):
            with self.subTest(path=invalid), self.assertRaises(HTTPError) as raised:
                self.request('/api/workspaces', {'path': invalid})
            self.assertEqual(raised.exception.code, 400)
            raised.exception.close()
        self.assertEqual(self.request('/api/workspaces/remove', {'id': first[0]['id']}), {'workspaces': []})
        self.assertEqual(self.request('/api/workspaces/remove', {'id': first[0]['id']}), {'workspaces': []})
        self.assertEqual(marker.read_text(), 'research remains')
        self.assertEqual(self.store.list_projects(), [])

    def test_concurrent_workspace_enrollment_does_not_lose_entries(self):
        directories = [self.root / f'directory {index}' for index in range(5)]
        for directory in directories:
            directory.mkdir()
        with ThreadPoolExecutor(5) as pool:
            list(pool.map(lambda directory: Store(self.data).add_workspace({'path': str(directory)}), directories))
        self.assertCountEqual([entry['path'] for entry in self.store.list_workspaces()], [str(path) for path in directories])

    def test_startup_workspace_flags_enroll_once_and_persist(self):
        child = self.root / 'child'
        child.mkdir()
        with patch.object(server_module, 'Server') as server, redirect_stdout(io.StringIO()):
            server.return_value.serve_forever.side_effect = KeyboardInterrupt
            for _ in range(2):
                server_module.main(['--port', '0', '--no-demo', '--data-dir', str(self.data),
                                    '--workspace', str(self.root), '--workspace', str(child)])
        self.assertCountEqual([entry['path'] for entry in Store(self.data).list_workspaces()], [str(self.root), str(child)])

    def test_new_child_queue_after_startup_recovers_without_registry_or_source_reread(self):
        self.store.add_workspace({'path': str(self.root)})
        blocked_state = self.base / 'inaccessible state'
        blocked_state.write_text('Not a registry directory')
        with patch.dict(os.environ, {'EXP_OBSERVER_STATE_DIR': str(blocked_state)}), \
                patch.object(cli, 'register_outbox', side_effect=AssertionError('Agent attempted an outside registry write')):
            self.start()
            self.wait_for(lambda: self.server.recovery is not None and self.root in self.server.recovery.discovery
                          and self.server.recovery.discovery[self.root].next_scan > 0)
            child = self.root / 'created after startup' / 'nested experiment'
            child.mkdir(parents=True)
            source = child / 'result.txt'
            source.write_text('original evidence', encoding='utf-8')
            result = self.offline(child, 'record', '--project', 'new-child', '--title', 'New result', '--artifact', str(source))
            source.unlink()
            with patch('subprocess.Popen', side_effect=AssertionError('Recovery must never run research')):
                self.wait_for(lambda: len(self.store.get_project('new-child')['artifacts']) == 1)
            self.server.recovery.stop()
        self.assertTrue(result['pending'])
        project = self.store.get_project('new-child')
        self.assertEqual(project['nodes'][0]['id'], result['nodeId'])
        self.assertEqual(self.store.artifact_content('new-child', project['artifacts'][0]['id'])[0], b'original evidence')
        self.assertFalse(self.state.exists())

    def test_restarted_worker_uses_persisted_application_roots(self):
        self.store.add_workspace({'path': str(self.root)})
        self.start(automatic=False)
        initial = Recovery(self.url, self.state, store=self.store, interval=0.04)
        initial.drain_once()
        initial.stop()
        child = self.root / 'child created while closed'
        result = self.offline(child, 'record', '--project', 'after-restart', '--title', 'Retained queue')
        restarted = Recovery(self.url, self.state, store=Store(self.data), interval=0.04).start()
        self.addCleanup(restarted.stop)
        self.wait_for(lambda: len(self.store.get_project('after-restart')['nodes']) == 1)
        restarted.stop()
        self.assertEqual(self.store.get_project('after-restart')['nodes'][0]['id'], result['nodeId'])
        self.assertFalse(self.state.exists())

    def test_parent_explicit_init_precedes_child_implicit_plan_even_after_a_failed_attempt(self):
        self.store.add_workspace({'path': str(self.root)})
        self.offline(self.root, 'init', '--id', 'shared', '--name', 'Original project name', '--description', 'Original description')
        root_outbox = self.root / '.exp-observer-runs' / 'outbox'
        root_plan_path = cli.project_plan_path(root_outbox, self.url, 'shared')
        root_plan = json.loads(root_plan_path.read_text(encoding='utf-8'))
        child = self.root / 'aaa child'
        self.offline(child, 'record', '--project', 'shared', '--title', 'Child result')
        child_outbox = child / '.exp-observer-runs' / 'outbox'
        child_plan = dict(root_plan, implicit=True, state='ready', preparedAt='1900-01-01T00:00:00.000Z',
                          project={'id': 'shared', 'name': 'shared', 'description': '', 'sourceRoots': []})
        cli.save_task(cli.project_plan_path(child_outbox, self.url, 'shared'), child_plan)
        self.start(automatic=False)
        recovery = Recovery(self.url, self.state, store=self.store)
        synchronize = recovery.cli.sync_project
        def fail_root(client, path, plan):
            if path == root_plan_path:
                raise recovery.cli.ClientError('Original plan is temporarily unavailable', code='unavailable')
            return synchronize(client, path, plan)
        with patch.object(recovery.cli, 'sync_project', side_effect=fail_root):
            recovery.drain_once()
        self.assertEqual(self.store.list_projects(), [])
        with patch.object(self.store, 'create_project', wraps=self.store.create_project) as create:
            recovery.drain_once()
            self.assertEqual(create.call_count, 1)
            self.assertEqual(create.call_args.args[0]['name'], 'Original project name')
        project = self.store.get_project('shared')
        self.assertEqual((project['name'], project['description']), ('Original project name', 'Original description'))
        self.assertEqual(len(project['nodes']), 1)

    def test_symlinks_outside_evidence_and_generated_directories_are_not_read(self):
        self.store.add_workspace({'path': str(self.root)})
        outside = self.base / 'outside'
        self.offline(outside, 'record', '--project', 'outside', '--title', 'Not enrolled')
        skipped = self.root / 'node_modules'
        self.offline(skipped, 'record', '--project', 'generated', '--title', 'Not scanned')
        source = self.root / 'source.txt'
        source.write_text('capture')
        result = self.offline(self.root, 'record', '--project', 'escaped', '--title', 'Reject escape', '--artifact', str(source))
        outbox = self.root / '.exp-observer-runs' / 'outbox'
        capture = next(json.loads(path.read_text(encoding='utf-8')) for path in outbox.glob('*.json')
                       if not path.name.startswith('project-'))
        target = outside / 'secret.txt'
        target.write_text('must not be read')
        staged = Path(capture['artifacts'][0]['path'])
        staged.unlink()
        try:
            staged.symlink_to(target)
            (self.root / 'outside link').symlink_to(outside, target_is_directory=True)
            (outbox / 'outside.json').symlink_to(next((outside / '.exp-observer-runs' / 'outbox').glob('*.json')))
        except OSError:
            self.skipTest('Creating symlinks requires additional Windows permissions')
        self.start(automatic=False)
        original_open, original_io_open = builtins.open, io.open
        def scoped_open(file, *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and Path(file).is_absolute() and Path(file).resolve().is_relative_to(outside):
                raise AssertionError('Recovery tried to read outside the enrolled root')
            return original_open(file, *args, **kwargs)
        def scoped_io_open(file, *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and Path(file).is_absolute() and Path(file).resolve().is_relative_to(outside):
                raise AssertionError('Recovery tried to read a manifest outside the enrolled root')
            return original_io_open(file, *args, **kwargs)
        with patch('builtins.open', scoped_open), patch('io.open', scoped_io_open):
            results = Recovery(self.url, self.state, store=self.store).drain_once()
        self.assertTrue(any('leaves the workspace scope' in warning for record in results for warning in record.get('recordingWarnings', [])))
        self.assertEqual([project['id'] for project in self.store.list_projects()], ['escaped'])
        self.assertEqual(self.store.get_project('escaped')['nodes'], [])
        self.assertTrue(result['pending'])

    def test_task_and_project_lock_symlinks_are_not_opened_outside_the_workspace(self):
        self.store.add_workspace({'path': str(self.root)})
        outside = self.base / 'outside lock.txt'
        outside.write_text('unchanged')
        self.start(automatic=False)
        for project, project_lock in (('task-lock', False), ('project-lock', True)):
            with self.subTest(project_lock=project_lock):
                child = self.root / project
                self.offline(child, 'record', '--project', project, '--title', 'Do not open a foreign lock')
                outbox = child / '.exp-observer-runs' / 'outbox'
                path = next(path for path in outbox.glob('*.json') if path.name.startswith('project-') == project_lock)
                lock = path.with_suffix('.lock')
                lock.unlink(missing_ok=True)
                try:
                    lock.symlink_to(outside)
                except OSError:
                    self.skipTest('Creating symlinks requires additional Windows permissions')
                original_open = Path.open
                def guard(file, *args, **kwargs):
                    if file.resolve() == outside:
                        raise AssertionError('Recovery opened an outside lock file')
                    return original_open(file, *args, **kwargs)
                with patch.object(Path, 'open', guard):
                    results = Recovery(self.url, self.state, store=self.store).drain_once()
                self.assertTrue(any(record['pending'] for record in results))
                try:
                    self.assertEqual(self.store.get_project(project)['nodes'], [])
                except StoreError as exc:
                    self.assertEqual(exc.code, 'not_found')
                self.assertEqual(outside.read_text(), 'unchanged')

    def test_discovery_is_incremental_and_does_not_restart_the_walk_each_tick(self):
        self.store.add_workspace({'path': str(self.root)})
        for index in range(200):
            (self.root / f'child-{index}').mkdir()
        recovery = Recovery(self.url, self.state, store=self.store, discovery_budget=8, discovery_interval=60)
        self.addCleanup(recovery.stop)
        scans, scandir = [], os.scandir
        def observe(path):
            if Path(path).is_relative_to(self.root):
                scans.append(Path(path))
            return scandir(path)
        with patch('backend.recovery.os.scandir', side_effect=observe):
            recovery.drain_once()
            self.assertLessEqual(len(scans), 8)
            for _ in range(4):
                recovery.drain_once()
        # One initial direct-child priority scan plus the retained tree scan.
        self.assertEqual(scans.count(self.root), 2)
        self.assertIsNotNone(recovery.discovery[self.root].cursor)

    def test_new_root_child_is_recovered_while_old_font_cursor_keeps_progressing(self):
        self.store.add_workspace({'path': str(self.root)})
        fonts = self.root / 'fonts'
        fonts.mkdir()
        for index in range(256):
            (fonts / f'font-{index}.ttf').touch()
        for index in range(20):
            (self.root / f'a-directory-{index:02}').mkdir()
        recovery = Recovery(self.url, self.state, store=self.store, discovery_budget=4, discovery_interval=60)
        self.addCleanup(recovery.stop)
        scanner = WorkspaceDiscovery(self.root, 60)
        scanner.refresh_root()
        baseline = scanner.root_mtime
        scanner.queue.clear()
        recovery.discovery[self.root] = scanner
        child = self.root / 'zz-new-experiment'
        captured = self.offline(child, 'record', '--project', 'priority-child', '--title', 'New first-level experiment')
        self.start(automatic=False)
        operations, root_cursors = [], []
        scandir = os.scandir
        with scandir(self.root) as entries:
            # Fix traversal order so the experiment is last. Native filesystem
            # ordering must not make the starvation regression pass by chance.
            root_entries = sorted(entries, key=lambda entry: entry.name)
        class ObservedCursor:
            def __init__(self, entries, directory, owner=None):
                self.entries, self.directory, self.owner = iter(entries), directory, owner
                self.closed = False
                self.exhausted = False
            def __iter__(self):
                return self
            def __next__(self):
                operations.append(('next', self.directory))
                try:
                    return next(self.entries)
                except StopIteration:
                    self.exhausted = True
                    raise
            def close(self):
                self.closed = True
                if self.owner is not None:
                    self.owner.close()
        original_fonts = scandir(fonts)
        old_cursor = ObservedCursor(original_fonts, fonts, original_fonts)
        scanner.cursor = old_cursor
        def observe(directory):
            directory = Path(directory)
            if directory == self.root:
                if root_cursors:
                    self.assertTrue(root_cursors[-1].exhausted, 'A root mtime change reset an unfinished priority cursor')
                operations.append(('open', directory))
                cursor = ObservedCursor(root_entries, directory)
                root_cursors.append(cursor)
                return cursor
            return scandir(directory)
        with patch('backend.recovery.os.scandir', side_effect=observe):
            for tick in range(20):
                # Keep changing root mtime while a priority scan is in progress.
                # It must finish its current cursor rather than restart at entry 0.
                info = self.root.stat()
                os.utime(self.root, ns=(info.st_atime_ns, baseline + (tick + 1) * 1_000_000))
                before = len(operations)
                recovery.drain_once()
                self.assertLessEqual(len(operations) - before, recovery.discovery_budget)
                try:
                    if self.store.get_project('priority-child')['nodes']:
                        break
                except StoreError as exc:
                    self.assertEqual(exc.code, 'not_found')
            else:
                self.fail('Root changes kept the new experiment behind the large font traversal')
        self.assertEqual(self.store.get_project('priority-child')['nodes'][0]['id'], captured['nodeId'])
        self.assertLessEqual(len(root_cursors), 2)
        self.assertTrue(all(cursor.exhausted for cursor in root_cursors[:-1]))
        self.assertIs(scanner.cursor, old_cursor)
        self.assertFalse(old_cursor.closed)
        self.assertGreater(sum(directory == fonts for operation, directory in operations if operation == 'next'), 0)
        self.assertLess(sum(directory == fonts for operation, directory in operations if operation == 'next'), 256)

    def test_known_experiment_child_is_recovered_without_finishing_old_font_cursor(self):
        self.store.add_workspace({'path': str(self.root)})
        owner = self.root / 'known experiment'
        self.offline(owner, 'record', '--project', 'nested-priority', '--title', 'Existing experiment')
        for index in range(20):
            (owner / f'old-directory-{index:02}').mkdir()
        fonts = self.root / 'fonts'
        fonts.mkdir()
        for index in range(512):
            (fonts / f'font-{index}.ttf').touch()
        recovery = Recovery(self.url, self.state, store=self.store, discovery_budget=4, discovery_interval=60)
        self.addCleanup(recovery.stop)
        scanner = WorkspaceDiscovery(self.root, 60)
        scanner.refresh_root()
        root_mtime = scanner.root_mtime
        scanner.probe(owner)
        # Finish its initial direct-child probe before creating the new child:
        # only a later owner mtime check can trigger timely discovery now.
        while scanner.priority_queue or scanner.priority_cursor is not None:
            scanner.step()
        if scanner.cursor is not None:
            scanner.cursor.close()
            scanner.cursor = None
        scanner.queue.clear()
        recovery.discovery[self.root] = scanner
        child = owner / 'zz-new directory after app startup'
        captured = self.offline(child, 'record', '--project', 'nested-priority', '--title', 'New nested experiment')
        self.assertEqual(self.root.stat().st_mtime_ns, root_mtime)
        self.start(automatic=False)
        operations, owner_cursors = [], []
        scandir = os.scandir
        with scandir(owner) as entries:
            owner_entries = sorted(entries, key=lambda entry: entry.name)
        class ObservedCursor:
            def __init__(self, entries, directory, owner=None):
                self.entries, self.directory, self.owner = iter(entries), directory, owner
                self.closed = self.exhausted = False
            def __next__(self):
                operations.append(('next', self.directory))
                try:
                    return next(self.entries)
                except StopIteration:
                    self.exhausted = True
                    raise
            def close(self):
                self.closed = True
                if self.owner is not None:
                    self.owner.close()
        original_fonts = scandir(fonts)
        old_cursor = ObservedCursor(original_fonts, fonts, original_fonts)
        scanner.cursor = old_cursor
        def observe(directory):
            directory = Path(directory)
            if directory in (self.root, owner, fonts):
                operations.append(('open', directory))
            if directory == owner:
                if owner_cursors:
                    self.assertTrue(owner_cursors[-1].exhausted, 'Owner mtime changes reset its unfinished cursor')
                cursor = ObservedCursor(owner_entries, directory)
                owner_cursors.append(cursor)
                return cursor
            return scandir(directory)
        watch_owner = scanner._watch_directory
        def observe_watch():
            operations.append(('watch', scanner.watched[0]))
            return watch_owner()
        baseline = owner.stat().st_mtime_ns
        with patch('backend.recovery.os.scandir', side_effect=observe), patch.object(scanner, '_watch_directory', side_effect=observe_watch):
            for tick in range(80):
                info = owner.stat()
                os.utime(owner, ns=(info.st_atime_ns, baseline + (tick + 1) * 1_000_000))
                before = len(operations)
                recovery.drain_once()
                self.assertLessEqual(len(operations) - before, recovery.discovery_budget)
                if any(node['id'] == captured['nodeId'] for node in self.store.get_project('nested-priority')['nodes']):
                    break
            else:
                self.fail('The new child remained behind the unrelated old font traversal')
        self.assertIs(scanner.cursor, old_cursor)
        self.assertFalse(old_cursor.closed)
        font_steps = sum(operation == 'next' and directory == fonts for operation, directory in operations)
        self.assertGreater(font_steps, 0)
        self.assertLess(font_steps, 512)
        self.assertTrue(owner_cursors)
        self.assertTrue(all(cursor.exhausted for cursor in owner_cursors[:-1]))

    def _assert_empty_child_later_init_recovers(self, *, nested):
        self.store.add_workspace({'path': str(self.root)})
        owner = self.root
        if nested:
            owner = self.root / 'known experiment'
            self.offline(owner, 'record', '--project', 'owner', '--title', 'Existing owner')
        child = owner / 'empty directory prepared before init'
        child.mkdir()
        fonts = self.root / 'fonts'
        fonts.mkdir()
        for index in range(512):
            (fonts / f'font-{index}.ttf').touch()
        recovery = Recovery(self.url, self.state, store=self.store, discovery_budget=4, discovery_interval=60)
        self.addCleanup(recovery.stop)
        scanner = WorkspaceDiscovery(self.root, 60)
        recovery.discovery[self.root] = scanner
        scanner.queue.clear()
        original_fonts = os.scandir(fonts)
        class ObservedCursor:
            def __init__(self):
                self.steps = 0
                self.closed = False
            def __next__(self):
                self.steps += 1
                return next(original_fonts)
            def close(self):
                self.closed = True
                original_fonts.close()
        old_cursor = ObservedCursor()
        scanner.cursor = old_cursor
        scanner.refresh_root()
        # The initial priority scan must find an empty direct child even while
        # the ordinary walk is stuck elsewhere. Empty children are watched,
        # but their children must not be recursively scheduled for scanning.
        if nested:
            scanner.probe(owner)
        for _ in range(100):
            scanner.step()
            if not scanner.root_dirty and not scanner.priority_queue and scanner.priority_cursor is None:
                break
        else:
            self.fail('Initial direct-child discovery did not finish')
        self.assertIn(child, scanner.directory_mtimes)
        self.assertNotIn(child / '.exp-observer-runs' / 'outbox', scanner.outboxes)
        self.assertFalse(scanner.priority_queue)
        root_mtime = self.root.stat().st_mtime_ns
        owner_mtime = owner.stat().st_mtime_ns
        self.offline(child, 'init', '--id', 'prepared-child', '--name', 'Prepared directory project')
        captured = self.offline(child, 'record', '--project', 'prepared-child', '--title', 'Later capture')
        self.assertEqual(self.root.stat().st_mtime_ns, root_mtime)
        self.assertEqual(owner.stat().st_mtime_ns, owner_mtime)
        self.start(automatic=False)
        previous_steps = old_cursor.steps
        for _ in range(30):
            recovery.drain_once()
            try:
                project = self.store.get_project('prepared-child')
            except StoreError as exc:
                self.assertEqual(exc.code, 'not_found')
                continue
            if any(node['id'] == captured['nodeId'] for node in project['nodes']):
                break
        else:
            self.fail('An already-probed empty directory was not discovered after init')
        self.assertEqual(project['name'], 'Prepared directory project')
        self.assertIs(scanner.cursor, old_cursor)
        self.assertFalse(old_cursor.closed)
        self.assertGreater(old_cursor.steps, previous_steps)
        self.assertLess(old_cursor.steps, 512)

    def test_preexisting_empty_root_child_is_discovered_after_later_init(self):
        self._assert_empty_child_later_init_recovers(nested=False)

    def test_preexisting_empty_owner_child_is_discovered_after_later_init(self):
        self._assert_empty_child_later_init_recovers(nested=True)

    def test_unenrollment_suppresses_legacy_registry_until_reenrolled(self):
        workspace = self.store.add_workspace({'path': str(self.root)})[0]
        child = self.root / 'child'
        self.offline(child, 'record', '--project', 'removed', '--title', 'Retained locally')
        cli.register_outbox(child / '.exp-observer-runs' / 'outbox', self.url)
        self.store.remove_workspace({'id': workspace['id']})
        self.start(automatic=False)
        recovery = Recovery(self.url, self.state, store=Store(self.data))
        self.assertEqual(recovery.drain_once(), [])
        self.assertEqual(self.store.list_projects(), [])
        self.store.add_workspace({'path': str(self.root)})
        recovered = Recovery(self.url, self.state, store=Store(self.data))
        recovered.drain_once()
        self.assertEqual(len(self.store.get_project('removed')['nodes']), 1)
        self.assertTrue(child.is_dir())

    def test_overlap_and_legacy_registration_deduplicate_and_other_urls_stay_pending(self):
        child = self.root / 'child'
        child.mkdir()
        self.store.add_workspace({'path': str(self.root)})
        self.store.add_workspace({'path': str(child)})
        result = self.offline(child, 'record', '--project', 'deduplicated', '--title', 'One record')
        self.offline(child, 'record', '--project', 'another-server', '--title', 'Other URL', url='http://127.0.0.1:1')
        cli.register_outbox(child / '.exp-observer-runs' / 'outbox', self.url)
        self.start(automatic=False)
        recovery = Recovery(self.url, self.state, store=self.store)
        recovery.drain_once()
        revision = self.store.get_project('deduplicated')['revision']
        self.assertEqual(recovery.drain_once(), [])
        self.assertEqual(self.store.get_project('deduplicated')['revision'], revision)
        self.assertEqual(self.store.get_project('deduplicated')['nodes'][0]['id'], result['nodeId'])
        self.assertEqual(len(self.store.list_projects()), 1)

    def test_another_active_enrollment_overrides_removed_ancestor_suppression(self):
        ancestor = self.store.add_workspace({'path': str(self.root)})[0]
        child = self.root / 'active child'
        self.offline(child, 'record', '--project', 'still-active', '--title', 'Covered by an active root')
        self.store.add_workspace({'path': str(child)})
        self.store.remove_workspace({'id': ancestor['id']})
        cli.register_outbox(child / '.exp-observer-runs' / 'outbox', self.url)
        self.start(automatic=False)
        Recovery(self.url, self.state, store=self.store).drain_once()
        self.assertEqual(len(self.store.get_project('still-active')['nodes']), 1)


if __name__ == '__main__':
    unittest.main()