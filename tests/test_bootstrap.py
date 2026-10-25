"""A copied Skill can start the application without Node, pip or a live parent."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen
import zipfile

from scripts.package_release import ROOT, package_release
from backend.store import Store

SPEC = importlib.util.spec_from_file_location('observer_bootstrap', ROOT/'skills/exp-observer/scripts/bootstrap.py')
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class WindowsListenerTests(unittest.TestCase):
    def table(self, rows, count=None):
        import ctypes
        data = struct.pack('<I', len(rows) if count is None else count) + b''.join(struct.pack('<6I', *row) for row in rows)
        def get_table(buffer, length, ordered, family, table_class, reserved):
            self.assertEqual((family, table_class, reserved), (socket.AF_INET, 3, 0))
            ctypes.cast(length, ctypes.POINTER(ctypes.c_uint32)).contents.value = len(data)
            if buffer is None:
                return 122
            ctypes.memmove(buffer, data, len(data))
            return 0
        return type('IPHelper', (), {'GetExtendedTcpTable': staticmethod(get_table)})()

    def test_listener_table_filters_address_state_and_network_ordered_port(self):
        import ctypes
        port = 4317
        for row, expected in [
            ((2, 0x0100007f, socket.htons(port), 0, 0, 123), True),
            ((2, 0, socket.htons(port), 0, 0, 123), True),
            ((11, 0x0100007f, socket.htons(port), 0, 0, 123), False),
            ((2, 0x0100a8c0, socket.htons(port), 0, 0, 123), False),
            ((2, 0x0100007f, socket.htons(port+1), 0, 0, 123), False),
        ]:
            with self.subTest(row=row), patch.object(ctypes, 'WinDLL', return_value=self.table([row]), create=True), \
                 patch.object(bootstrap.socket, 'socket', side_effect=AssertionError('probe must not bind or connect')):
                self.assertIs(bootstrap.windows_listener(port), expected)

    def test_truncated_listener_table_remains_unknown(self):
        import ctypes
        with patch.object(ctypes, 'WinDLL', return_value=self.table([], count=1), create=True):
            self.assertIsNone(bootstrap.windows_listener(4317))
        with patch.object(ctypes, 'WinDLL', side_effect=OSError('unavailable'), create=True):
            self.assertIsNone(bootstrap.windows_listener(4317))

    @unittest.skipUnless(os.name == 'nt', 'Windows IP Helper native test')
    def test_native_probe_distinguishes_listening_from_merely_bound_and_closed_ports(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            self.assertIs(bootstrap.windows_listener(port), False)
            listener.listen()
            self.assertIs(bootstrap.windows_listener(port), True)
        with patch.object(bootstrap.socket, 'socket', side_effect=AssertionError('must not reserve a port')):
            self.assertEqual(bootstrap.probe(f'http://127.0.0.1:{port}'), 'missing')


@unittest.skipUnless((ROOT/'dist/index.html').is_file() or os.environ.get('EXP_OBSERVER_RELEASE_ZIP'), 'Build the portable runtime first')
class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release_temp = tempfile.TemporaryDirectory()
        supplied = os.environ.get('EXP_OBSERVER_RELEASE_ZIP')
        cls.archive = Path(supplied).resolve() if supplied else package_release(ROOT, Path(cls.release_temp.name)/'release.zip')

    @classmethod
    def tearDownClass(cls):
        cls.release_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='observer portable 研究 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.skill = self.root/'copied skill/exp-observer'
        with zipfile.ZipFile(self.archive) as archive:
            prefix = 'exp-observer/skills/exp-observer/'
            for item in archive.infolist():
                if item.filename.startswith(prefix):
                    target = self.skill/item.filename[len(prefix):]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(item))
        self.workspace = self.root/'research 工作'
        self.workspace.mkdir()
        self.state = self.root/'state'
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0)); self.port = reserved.getsockname()[1]
        self.url = f'http://127.0.0.1:{self.port}'
        self.env = dict(os.environ, EXP_OBSERVER_STATE_DIR=str(self.state), HOME=str(self.root/'home'),
                        USERPROFILE=str(self.root/'home'), LOCALAPPDATA=str(self.root/'local'), PATH='', PYTHONIOENCODING='cp1252')
        self.env.pop('EXP_OBSERVER_APP', None)
        self.env.pop('EXP_OBSERVER_AUTOSTART', None)
        self.addCleanup(self.stop)

    def stop(self):
        launch = self.state/('launch-'+str(self.port)+'.json')
        record = bootstrap.read_json(launch)
        if record.get('pid'):
            try:
                os.kill(record['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as exc:
                # Windows reports an already-exited child as ERROR_INVALID_PARAMETER.
                if getattr(exc, 'winerror', None) != 87:
                    raise
            for _ in range(60):
                if bootstrap.probe(self.url) != 'ready': break
                time.sleep(.05)

    def invoke(self, *arguments, cwd=None):
        result = subprocess.run([sys.executable, str(self.skill/'scripts/exp_observer.py'), '--url', self.url, *arguments],
                                cwd=cwd or self.workspace, env=self.env, capture_output=True, timeout=15)
        diagnostics = '\n'.join(path.read_text(encoding='utf-8',errors='replace')[-8000:] for path in self.state.glob('*') if path.suffix in ('.log','.json')) if self.state.exists() else 'No startup state written'
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace') + '\n' + diagnostics)
        return json.loads(result.stdout)

    def test_skill_only_boots_offline_then_reuses_and_restarts_the_same_data(self):
        created = self.invoke('init', '--id', 'study', '--name', '移植后实验')
        self.assertFalse(created['pending'], (created,bootstrap.read_json(self.state/('launch-'+str(self.port)+'.json'))))
        receipt = self.invoke('event', '--project', 'study', '--question', '已有结果需要验证吗？', '--finding', '保留真实已有结果')
        self.assertFalse(receipt['pending'])
        launch = self.state/('launch-'+str(self.port)+'.json')
        first = bootstrap.read_json(launch)
        self.assertEqual(first['state'], 'ready')
        self.invoke('projects')
        self.assertEqual(first['pid'], bootstrap.read_json(launch)['pid'])
        self.stop()
        resumed = self.invoke('context', '--project', 'study')
        self.assertEqual(resumed['name'], '移植后实验')
        self.assertEqual(len(resumed['nodes']), 2)
        second = bootstrap.read_json(launch)
        self.assertNotEqual(first['pid'], second['pid'])
        self.assertEqual(first['dataDir'], second['dataDir'])
        with urlopen(self.url) as response:
            self.assertIn(b'/assets/', response.read())
        with urlopen(self.url+'/api/workspaces') as response:
            self.assertEqual(json.load(response)['workspaces'][0]['path'], str(self.workspace))

    def test_running_platform_also_connects_a_new_research_directory(self):
        self.invoke('init', '--id', 'first', '--name', 'First research')
        other = self.root/'another research 研究'
        other.mkdir()
        self.invoke('init', '--id', 'second', '--name', 'Second research', cwd=other)
        with urlopen(self.url+'/api/workspaces') as response:
            paths = {w['path'] for w in json.load(response)['workspaces']}
        self.assertEqual(paths, {str(self.workspace), str(other)})

    def test_concurrent_first_use_starts_one_platform_and_preserves_all_records(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: self.invoke('init', '--id', 'study-'+str(n), '--name', 'Experiment '+str(n)), range(4)))
        self.assertEqual(len({r['id'] for r in results}), 4)
        deadline = time.monotonic()+5
        projects = []
        while time.monotonic()<deadline:
            try:
                with urlopen(self.url+'/api/projects') as response:
                    projects = json.load(response)['projects']
            except OSError:
                time.sleep(.05)
                continue
            if len(projects)==4: break
            time.sleep(.05)
        diagnostics = '\n'.join(path.read_text(encoding='utf-8', errors='replace')[-8000:]
                                for path in self.state.glob('*') if path.suffix in ('.log', '.json'))
        self.assertEqual(len(projects), 4, json.dumps(results, ensure_ascii=True)+'\n'+diagnostics)
        self.assertEqual(len(list((self.state/'runtime').iterdir())), 1)

    def test_known_installation_reuses_its_data_directory_without_a_bundle(self):
        app = self.root/'existing application'
        with zipfile.ZipFile(self.archive) as archive:
            archive.extractall(app)
        app = app/'exp-observer'
        data = self.root/'existing data'
        store = Store(data)
        store.create_project({'id':'old','name':'已有实验'})
        self.state.mkdir()
        bootstrap.write_json(self.state/('platform-'+str(self.port)+'.json'), {'appRoot':str(app), 'dataDir':str(data)})
        shutil.rmtree(self.skill/'assets')
        self.assertEqual(self.invoke('projects')['projects'][0]['name'], '已有实验')
        self.assertEqual(bootstrap.read_json(self.state/('launch-'+str(self.port)+'.json'))['dataDir'], str(data))

    def test_opt_out_and_corrupt_runtime_keep_records_locally_without_execution(self):
        self.env['EXP_OBSERVER_AUTOSTART']='0'
        self.assertTrue(self.invoke('init', '--id','offline','--name','离线研究')['pending'])
        self.assertFalse(self.state.exists())
        self.env.pop('EXP_OBSERVER_AUTOSTART')
        (self.skill/'assets/platform.zip').write_bytes(b'corrupted archive')
        self.assertTrue(self.invoke('event','--project','offline','--question','已经完成的研究')['pending'])
        self.assertFalse((self.state/'runtime').exists())

    def test_other_listener_is_not_started_or_sent_research_data(self):
        posts=[]
        class Other(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true,"app":"Other"}')
            def do_POST(self):
                posts.append(self.path); self.send_response(500); self.end_headers()
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',self.port),Other)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            self.assertTrue(self.invoke('init','--id','private','--name','本机研究')['pending'])
            self.assertEqual(posts,[])
            self.assertFalse(self.state.exists())
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_permission_denial_does_not_spawn_or_request_an_exception(self):
        with patch.object(bootstrap,'probe',return_value='unavailable'), patch.object(bootstrap,'detached',side_effect=AssertionError('must not spawn')):
            self.assertEqual(bootstrap.ensure_platform(self.url,self.workspace,self.state)['state'],'unavailable')
        self.assertFalse(self.state.exists())

    def test_starting_platform_is_probed_without_reserving_its_port(self):
        self.state.mkdir()
        bootstrap.write_json(self.state/('launch-'+str(self.port)+'.json'),
                             {'state':'starting', 'at':time.time(), 'pid':999999})
        for health, expected in [('unavailable', 'unavailable'), ('missing', 'starting')]:
            with self.subTest(health=health), \
                 patch.object(bootstrap, 'probe', return_value=health) as probe, \
                 patch.object(bootstrap, 'detached', side_effect=AssertionError('must not spawn')):
                self.assertEqual(bootstrap.ensure_platform(self.url, self.workspace, self.state)['state'], expected)
            probe.assert_called_once_with(self.url)

    def test_child_readiness_checks_do_not_bind_the_port_the_child_needs(self):
        # Model the child becoming ready on the second readiness check.
        state = self.root/'readiness-state'
        process = type('Child', (), {'pid':999999, 'poll':lambda self: None})()
        with patch.object(bootstrap, 'probe', side_effect=['missing', 'missing', 'unavailable', 'ready']) as probe, \
             patch.object(bootstrap, 'application_candidates', return_value=[(ROOT, None)]), \
             patch.object(bootstrap, 'detached', return_value=process), \
             patch.object(bootstrap.time, 'sleep'):
            result = bootstrap.ensure_platform(self.url, self.workspace, state)
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(probe.call_count, 4)

    def test_source_only_skill_provisions_in_background_without_waiting_for_a_download(self):
        state = self.root/'source-only-state'
        with patch.object(bootstrap,'__file__',str(self.root/'source-only/scripts/bootstrap.py')), \
             patch.object(bootstrap,'application_candidates',return_value=[]), \
             patch.object(bootstrap,'probe',return_value='missing'), \
             patch.object(bootstrap,'detached') as spawn, \
             patch.object(bootstrap,'download_runtime',side_effect=AssertionError('foreground download')):
            spawn.return_value.pid = 999999
            result = bootstrap.ensure_platform(self.url,self.workspace,state)
        self.assertEqual(result['state'],'provisioning')
        self.assertIn('--provision',spawn.call_args.args[0])

    def test_official_download_is_checksum_verified_and_bad_archives_never_execute(self):
        self.state.mkdir()
        contents = self.archive.read_bytes()
        expected = hashlib.sha256(contents).hexdigest()
        with patch.object(bootstrap,'urlopen',side_effect=[io.BytesIO((expected+'  exp-observer.zip\n').encode()),io.BytesIO(contents)]) as request:
            app = bootstrap.download_runtime(self.state)
        self.assertTrue(bootstrap.valid_app(app))
        self.assertEqual([call.args[0].full_url for call in request.call_args_list],
                         [bootstrap.RELEASE+'SHA256SUMS',bootstrap.RELEASE+'exp-observer.zip'])
        with patch.object(bootstrap,'urlopen',side_effect=[io.BytesIO(('0'*64+'  exp-observer.zip\n').encode()),io.BytesIO(contents)]):
            with self.assertRaisesRegex(ValueError,'checksum'):
                bootstrap.download_runtime(self.state)
        malicious = self.root/'malicious.zip'
        with zipfile.ZipFile(malicious,'w') as archive:
            archive.writestr('exp-observer/../outside.py',b'not executable')
        with self.assertRaisesRegex(ValueError,'Invalid portable runtime path'):
            bootstrap.extract_runtime(malicious,self.state,hashlib.sha256(malicious.read_bytes()).hexdigest())
        self.assertFalse((self.state/'outside.py').exists())
