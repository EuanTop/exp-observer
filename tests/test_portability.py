"""Exercise native paths, encodings and command arguments on every supported OS."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from backend.server import Server
from backend.store import Store

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'skills' / 'exp-observer' / 'scripts' / 'exp_observer.py'


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='exp-observer paths ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '研究 with spaces'
        self.root.mkdir()
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': '研究项目'})
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'a'}}]})
        self.dist = self.root / 'dist'
        self.dist.mkdir()
        self.server = Server(('127.0.0.1', 0), self.store, dist=self.dist)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def cli(self, *args, input=None):
        # Simulate redirected Windows stdio even on Unix. The client's JSON stays UTF-8.
        return subprocess.run([sys.executable, str(CLI), '--url', self.url, *args],
                              input=input, capture_output=True, cwd=self.root,
                              env=dict(os.environ, PYTHONIOENCODING='cp1252'), timeout=20)

    def test_utf8_json_and_powershell_bom_file_and_stdin(self):
        for source in ('file', 'stdin'):
            with self.subTest(source=source):
                body = json.dumps([{'op': 'node.update', 'data': {'id': 'a', 'title': '结果 ' + source}}],
                                  ensure_ascii=False).encode('utf-8-sig')
                args = ['apply', '--project', 'study']
                if source == 'file':
                    changes = self.root / '更改 file.json'
                    changes.write_bytes(body)
                    args += ['--file', str(changes)]
                applied = self.cli(*args, input=body if source == 'stdin' else None)
                self.assertEqual(applied.returncode, 0, applied.stderr)
                context = self.cli('context', '--project', 'study')
                self.assertEqual(context.returncode, 0, context.stderr)
                self.assertEqual(json.loads(context.stdout.decode('utf-8'))['nodes'][0]['title'], '结果 ' + source)

    def test_execute_unicode_paths_and_literal_command_arguments(self):
        script = self.root / '测量 script.py'
        script.write_text(
            'import json, sys\nfrom pathlib import Path\n'
            "Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:], ensure_ascii=False), encoding='utf-8')\n"
            "sys.stdout.buffer.write('实测\\n'.encode('utf-8'))\n", encoding='utf-8')
        output = '结果 file.json'
        arguments = ['value with spaces', 'literal "quote"', '& echo unexpected', '$HOME', '研究']
        result = self.cli('execute', '--project', 'study', '--node', 'a', '--title', '实际命令',
                          '--artifact', output, '--', sys.executable, str(script), output, *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'completed')
        project = self.store.get_project('study')
        evidence = {artifact['title']: artifact for artifact in project['artifacts']}
        retained = self.store.artifact_content('study', evidence[output]['id'])[0]
        self.assertEqual(json.loads(retained), arguments)
        self.assertEqual(self.store.artifact_content('study', evidence['Standard output']['id'])[0],
                         '实测\n'.encode('utf-8'))

    def test_browser_asset_mime_does_not_depend_on_windows_registry(self):
        for suffix, expected in (('js', 'text/javascript'), ('css', 'text/css'), ('html', 'text/html')):
            with self.subTest(suffix=suffix):
                (self.dist / ('asset.' + suffix)).write_bytes(b'fixture')
                with patch('backend.server.mimetypes.guess_type', return_value=('text/plain', None)):
                    with urlopen(self.url + '/asset.' + suffix, timeout=10) as response:
                        self.assertEqual(response.headers.get_content_type(), expected)
                        self.assertEqual(response.read(), b'fixture')

    def test_execute_project_ids_with_windows_path_aliases(self):
        captures = set()
        for project_id in ('CON', 'study.', 'a' * 127 + '.', 'Case', 'case'):
            with self.subTest(project_id=project_id):
                self.store.create_project({'id': project_id, 'name': project_id})
                self.store.batch(project_id, {'operations': [{'op': 'node.add', 'data': {'id': 'a'}}]})
                result = self.cli('execute', '--project', project_id, '--node', 'a', '--title', 'Capture',
                                  '--', sys.executable, '-c', "print('captured')")
                self.assertEqual(result.returncode, 0, result.stderr)
                project = self.store.get_project(project_id)
                self.assertTrue(self.store.artifact_metadata(project_id, project['artifacts'][0]['id'])['verified'])
                capture = Path(project['sourceRoots'][0])
                self.assertTrue(capture.is_dir())
                self.assertNotIn(capture.name.upper(), ('CON', 'STUDY.'))
                self.assertNotIn(str(capture).lower(), captures)
                captures.add(str(capture).lower())


@unittest.skipUnless(os.name == 'nt', 'Requires native Windows Command Prompt')
class WindowsLauncherTests(unittest.TestCase):
    def test_prebuilt_launcher_needs_only_python_and_preserves_arguments(self):
        with tempfile.TemporaryDirectory(prefix='exp-observer launcher ') as directory:
            root = Path(directory) / '研究 with spaces'
            root.mkdir()
            shutil.copyfile(ROOT / 'start.bat', root / 'start.bat')
            (root / 'dist').mkdir()
            (root / 'dist' / 'index.html').write_bytes(b'fixture')
            # A tiny entrypoint verifies launcher dispatch without starting a persistent server.
            (root / 'start.py').write_text(
                'import json, os, sys\n'
                "print(json.dumps({'cwd': os.getcwd(), 'argv': sys.argv[1:]}))\n"
                'sys.exit(7)\n', encoding='utf-8')
            result = subprocess.run(['cmd', '/d', '/c', 'start.bat', '--no-demo', '--data-dir', 'data folder'],
                                    cwd=root, capture_output=True, timeout=30,
                                    env=dict(os.environ, PYTHONIOENCODING='utf-8'))
            self.assertEqual(result.returncode, 7, result.stderr)
            captured = json.loads(result.stdout.decode('utf-8'))
            self.assertEqual(Path(captured['cwd']), root)
            self.assertEqual(captured['argv'], ['--no-demo', '--data-dir', 'data folder'])


if __name__ == '__main__':
    unittest.main()