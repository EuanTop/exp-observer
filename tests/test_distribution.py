"""Verify the release whitelist and smoke-test the same ZIP on every supported OS."""
import json
import os
from pathlib import Path
import queue
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import urljoin
from urllib.request import urlopen
import zipfile

from scripts.package_release import FILES, ROOT, package_release, sha256


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source'
        self.output = Path(self.temp.name) / 'release' / 'exp-observer.zip'
        for relative in FILES:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('fixture\n', encoding='utf-8')
        (self.root / 'dist/assets').mkdir(parents=True)
        (self.root / 'dist/index.html').write_text(
            '<script type="module" src="/assets/app.js"></script><link href="/assets/app.css" rel="stylesheet">',
            encoding='utf-8')
        (self.root / 'dist/assets/app.js').write_bytes(b'console.log("fixture")')
        (self.root / 'dist/assets/app.css').write_bytes(b'body {}')

    def test_whitelist_checksum_and_launcher_permissions(self):
        for relative in ('node_modules/private.js', '.exp-observer/records.sqlite3',
                         'backend/__pycache__/store.pyc', 'skills/exp-observer/private-notes.md'):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'do not distribute')
        package_release(self.root, self.output)
        expected = set(FILES) | {'dist/index.html', 'dist/assets/app.js', 'dist/assets/app.css'}
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {'exp-observer/' + name for name in expected})
            launcher = archive.getinfo('exp-observer/start.command')
            self.assertTrue((launcher.external_attr >> 16) & stat.S_IXUSR)
            self.assertEqual(launcher.create_system, 3)
        self.assertEqual(self.output.with_name('SHA256SUMS').read_text(encoding='utf-8'),
                         f'{sha256(self.output)}  exp-observer.zip\n')

    def test_missing_build_or_asset_and_unexpected_build_data_are_rejected(self):
        javascript = self.root / 'dist/assets/app.js'
        javascript.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing or invalid frontend asset'):
            package_release(self.root, self.output)
        self.assertFalse(self.output.exists())
        javascript.write_bytes(b'fixture')
        private = self.root / 'dist/assets/records.sqlite3'
        private.write_bytes(b'private data')
        with self.assertRaisesRegex(ValueError, 'Unexpected build output'):
            package_release(self.root, self.output)
        private.unlink()
        (self.root / 'dist/index.html').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing release input: dist/index.html'):
            package_release(self.root, self.output)

    def test_symlinks_cannot_import_files_outside_the_whitelist(self):
        readme = self.root / 'README.md'
        readme.unlink()
        external = Path(self.temp.name) / 'private.txt'
        external.write_bytes(b'private')
        try:
            readme.symlink_to(external)
        except OSError:
            self.skipTest('Creating symlinks requires additional Windows permissions')
        with self.assertRaisesRegex(ValueError, 'must not be symlinks'):
            package_release(self.root, self.output)


@unittest.skipUnless(os.environ.get('EXP_OBSERVER_RELEASE_ZIP') or (ROOT / 'dist/index.html').is_file(),
                     'Build the frontend or set EXP_OBSERVER_RELEASE_ZIP to smoke-test a release')
class DistributionSmokeTests(unittest.TestCase):
    def test_extracted_release_starts_without_node_and_runs_packaged_client(self):
        with tempfile.TemporaryDirectory(prefix='exp-observer release ') as directory:
            temporary = Path(directory)
            supplied = os.environ.get('EXP_OBSERVER_RELEASE_ZIP')
            archive_path = Path(supplied).resolve() if supplied else package_release(ROOT, temporary / 'exp-observer.zip')
            expected = archive_path.with_name('SHA256SUMS').read_text(encoding='utf-8').split('  ', 1)[0]
            self.assertEqual(sha256(archive_path), expected)
            extraction = temporary / '发行包 with spaces'
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extraction)
            root = (extraction / 'exp-observer').resolve()
            self.assertFalse((root / 'node_modules').exists())
            self.assertFalse((root / '.exp-observer').exists())
            data = temporary / '研究 records'
            empty_path = temporary / 'no external executables'
            empty_path.mkdir()
            environment = dict(os.environ, PATH=str(empty_path), PYTHONIOENCODING='utf-8', PYTHONNOUSERSITE='1',
                               PYTHONPROFILEIMPORTTIME='1')
            process = subprocess.Popen(
                [sys.executable, '-u', str(root / 'start.py'), '--no-browser', '--port', '0',
                 '--data-dir', str(data), '--no-demo'], cwd=temporary,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                env=environment)
            lines = queue.Queue()

            def read_output():
                for line in process.stdout:
                    lines.put(line)

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            try:
                deadline, output, url = time.monotonic() + 20, [], None
                while time.monotonic() < deadline and url is None:
                    try:
                        line = lines.get(timeout=0.1)
                    except queue.Empty:
                        if process.poll() is not None:
                            break
                        continue
                    output.append(line)
                    match = re.search(r'http://127\.0\.0\.1:(\d+)', line)
                    if match and int(match.group(1)):
                        url = match.group(0)
                self.assertIsNotNone(url, f'Packaged launcher did not start (exit={process.poll()}):\n' + ''.join(output))
                with urlopen(url + '/api/health', timeout=10) as response:
                    self.assertTrue(json.load(response)['ok'])
                with urlopen(url, timeout=10) as response:
                    html = response.read().decode('utf-8')
                    self.assertEqual(response.headers.get_content_type(), 'text/html')
                assets = re.findall(r'''(?:src|href)=["'](/assets/[^"']+)["']''', html)
                self.assertTrue(assets)
                for asset in assets:
                    with urlopen(urljoin(url, asset), timeout=10) as response:
                        self.assertTrue(response.read())
                        if asset.endswith('.js'):
                            self.assertEqual(response.headers.get_content_type(), 'text/javascript')
                with urlopen(url + '/api/agent-setup', timeout=10) as response:
                    setup = json.load(response)
                self.assertEqual(Path(setup['skillPath']), root / 'skills/exp-observer/SKILL.md')
                self.assertEqual(Path(setup['clientPath']), root / 'skills/exp-observer/scripts/exp_observer.py')
                self.assertTrue(Path(setup['skillPath']).is_file())
                client = subprocess.run(
                    [sys.executable, setup['clientPath'], '--url', url, 'init', '--id', 'release-check', '--name', '发行验证'],
                    cwd=temporary, capture_output=True, timeout=20, env=environment)
                self.assertEqual(client.returncode, 0, client.stderr)
                self.assertEqual(json.loads(client.stdout)['name'], '发行验证')
                self.assertTrue((data / 'records.sqlite3').is_file())
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                reader.join(timeout=5)
                process.stdout.close()


if __name__ == '__main__':
    unittest.main()