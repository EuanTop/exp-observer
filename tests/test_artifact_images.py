"""Verified image evidence can render without making SVG an active document."""
import base64
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from backend.artifact_images import IMAGE_CSP, image_mime
from backend.server import Server
from backend.store import Store, StoreError


class ArtifactImageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Study', 'sourceRoots': [str(self.root)]})
        self.server = Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}/api/projects/study/artifacts/'

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def artifact(self, name, raw):
        source = self.root / name
        source.write_bytes(raw)
        return self.store.register_artifact('study', {'path': str(source)})

    def assert_error(self, artifact, suffix, status, code):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + artifact['id'] + suffix, timeout=10)
        with caught.exception as response:
            self.assertEqual(response.code, status)
            self.assertEqual(json.loads(response.read())['code'], code)

    def test_svg_is_complete_verified_inert_image_and_raw_content_is_unchanged(self):
        # Bigger than the existing text window: image previews must never be
        # truncated into invalid XML. Script is deliberately retained evidence.
        raw = (b'<svg xmlns="http://www.w3.org/2000/svg" width="820" height="430">'
               b'<style>text{fill:#111827}</style><script>alert("not executable")</script>'
               b'<!--' + b' original chart evidence ' * 16000 + b'--><text>IoU</text></svg>')
        artifact = self.artifact('learning-curve.svg', raw)
        before = self.store.get_project('study')
        with urlopen(self.base + artifact['id'] + '/image', timeout=10) as response:
            self.assertEqual(response.read(), raw)
            self.assertEqual(response.headers['Content-Type'], 'image/svg+xml')
            self.assertEqual(int(response.headers['Content-Length']), len(raw))
            self.assertEqual(response.headers['Content-Security-Policy'], IMAGE_CSP)
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertIsNone(response.headers.get('Content-Disposition'))
        with urlopen(self.base + artifact['id'] + '/content', timeout=10) as response:
            self.assertEqual(response.read(), raw)
            self.assertEqual(response.headers['Content-Type'], 'application/octet-stream')
            self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertEqual(self.store.get_project('study'), before)

    def test_png_is_returned_as_image_not_download_or_text(self):
        raw = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7WQAAAAASUVORK5CYII=')
        artifact = self.artifact('chart.png', raw)
        with urlopen(self.base + artifact['id'] + '/image', timeout=10) as response:
            self.assertEqual(response.read(), raw)
            self.assertEqual(response.headers['Content-Type'], 'image/png')
            self.assertIsNone(response.headers.get('Content-Disposition'))

    def test_mime_parameters_aliases_and_unsupported_types(self):
        self.assertEqual(image_mime('IMAGE/SVG+XML; charset=utf-8'), 'image/svg+xml')
        self.assertEqual(image_mime(' image/jpg '), 'image/jpeg')
        self.assertEqual(image_mime('image/vnd.microsoft.icon'), 'image/x-icon')
        self.assertEqual(image_mime('image/x-ms-bmp'), 'image/bmp')
        for mime in ('text/html', 'application/xml', 'application/octet-stream', 'image/tiff', None):
            with self.subTest(mime=mime):
                self.assertIsNone(image_mime(mime))

    def test_nonimage_rejected_and_html_never_served_as_active_document(self):
        artifact = self.artifact('page.html', b'<html><script>alert(1)</script></html>')
        self.assert_error(artifact, '/image', 415, 'unsupported_image')
        with urlopen(self.base + artifact['id'] + '/content', timeout=10) as response:
            self.assertEqual(response.headers['Content-Type'], 'text/plain; charset=utf-8')

    def test_modified_or_missing_evidence_never_renders(self):
        artifact = self.artifact('chart.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><text>IoU</text></svg>')
        retained = Path(artifact['path'])
        retained.write_bytes(retained.read_bytes().replace(b'IoU', b'BAD'))
        self.assert_error(artifact, '/image', 409, 'evidence_changed')
        retained.unlink()
        self.assert_error(artifact, '/image', 404, 'evidence_missing')

    def test_actual_size_is_bounded_before_loading_image(self):
        artifact = self.artifact('chart.svg', b'<svg xmlns="http://www.w3.org/2000/svg">' + b' ' * 1024 + b'</svg>')
        with patch('backend.artifact_images.MAX_IMAGE_BYTES', 512):
            self.assert_error(artifact, '/image', 413, 'image_too_large')
        # A file growing past the bound must be rejected even when its retained
        # size originally fitted: metadata alone is not the allocation bound.
        small = self.artifact('small.svg', b'<svg/>')
        Path(small['path']).write_bytes(b'x' * 1024)
        with patch('backend.artifact_images.MAX_IMAGE_BYTES', 512):
            self.assert_error(small, '/image', 413, 'image_too_large')

    def test_image_endpoint_rejects_range_parameters_and_project_cross_reference(self):
        artifact = self.artifact('chart.svg', b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.assert_error(artifact, '/image?offset=0&limit=16', 400, 'invalid_preview_range')
        self.store.create_project({'id': 'other', 'name': 'Other'})
        with self.assertRaises(StoreError) as caught:
            self.store.artifact_image('other', artifact['id'])
        self.assertEqual(caught.exception.code, 'not_found')


if __name__ == '__main__':
    unittest.main()
