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
            for _ in range(60):
                if bootstrap.probe(self.url) != 'ready': break
                time.sleep(.05)

    def invoke(self, *arguments):
        result = subprocess.run([sys.executable, str(self.skill/'scripts/exp_observer.py'), '--url', self.url, *arguments],
                                cwd=self.workspace, env=self.env, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        return json.loads(result.stdout)

    def test_skill_only_boots_offline_then_reuses_and_restarts_the_same_data(self):
        created = self.invoke('init', '--id', 'study', '--name', '移植后实验')
        self.assertFalse(created['pending'], created)
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
        self.assertEqual(len(projects), 4)
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
