"""Loopback HTTP service for ExpObserver."""
from __future__ import annotations
import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
import sys
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from .store import Store, StoreError, canonical, now

MAX_BODY = 2 * 1024 * 1024
MAX_BATCH_BODY = 8 * 1024 * 1024
STATIC_MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store, dist=None, *, recovery=False, recovery_interval=2):
        self.store = store
        self.dist = Path(dist or Path(__file__).resolve().parents[1] / 'dist').resolve()
        self.recovery_enabled = recovery
        self.recovery_interval = recovery_interval
        self.recovery = None
        super().__init__(address, Handler)

    def serve_forever(self, poll_interval=0.5):
        if self.recovery_enabled:
            from .recovery import Recovery
            host = self.server_address[0]
            host = '[' + host + ']' if ':' in host else host
            self.recovery = Recovery(f'http://{host}:{self.server_port}', interval=self.recovery_interval, store=self.store).start()
        try:
            super().serve_forever(poll_interval=poll_interval)
        finally:
            if self.recovery is not None:
                self.recovery.stop()

    def server_close(self):
        if self.recovery is not None:
            self.recovery.stop()
        super().server_close()

    def server_bind(self):
        # The service is local: HTTPServer's reverse DNS lookup can stall startup
        # on macOS when the machine's resolver is unavailable.
        TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    server_version = f'ExpObserver/{__version__}'

    def log_message(self, format, *args):
        if args and isinstance(args[0], str) and args[0].startswith('GET /api/projects'):
            return
        super().log_message(format, *args)

    def _security(self):
        host = self.headers.get('Host', '')
        try:
            parsed_host = urlsplit('http://' + host)
            hostname = parsed_host.hostname
            port = parsed_host.port
        except ValueError:
            raise StoreError('Untrusted Host header.', 'untrusted_host', 403)
        if hostname not in ('127.0.0.1', 'localhost', '::1') or parsed_host.username or parsed_host.password or parsed_host.path or port not in (None, self.server.server_port):
            raise StoreError('Untrusted Host header.', 'untrusted_host', 403)
        if self.command in ('POST', 'PUT', 'PATCH', 'DELETE'):
            origin = self.headers.get('Origin')
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != 'http' or parsed.netloc != host or parsed.path not in ('', '/'):
                    raise StoreError('Cross-origin changes are not allowed.', 'origin_not_allowed', 403)
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise StoreError('Cross-site changes are not allowed.', 'origin_not_allowed', 403)

    def _body(self, limit=MAX_BODY):
        if self.headers.get('Transfer-Encoding'):
            raise StoreError('Chunked requests are not supported.', 'invalid_body')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise StoreError('Invalid Content-Length.', 'invalid_body')
        if length < 0 or length > limit:
            raise StoreError(f'Request is too large (limit {limit // (1024 * 1024)} MiB).', 'body_too_large', 413)
        try:
            return json.loads(self.rfile.read(length).decode('utf-8'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        except (ValueError, UnicodeError):
            raise StoreError('Request body must be valid JSON.', 'invalid_json')

    def _send(self, data, status=200, mime='application/json; charset=utf-8', attachment=None):
        if not isinstance(data, bytes):
            data = (canonical(data) + '\n').encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        if attachment:
            self.send_header('Content-Disposition', f'attachment; filename="{attachment}"')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def _handle(self):
        try:
            self._security()
            self._route()
        except StoreError as exc:
            self._send({'error': str(exc), 'code': exc.code}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._send({'error': 'Local service could not complete this request.', 'code': 'internal_error'}, 500)

    do_GET = _handle
    do_POST = _handle
    do_HEAD = _handle
    do_OPTIONS = _handle

    def _route(self):
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        parts = path.strip('/').split('/')
        query = parse_qs(parsed.query)
        method = 'GET' if self.command == 'HEAD' else self.command
        store = self.server.store
        if path == '/api/health' and method == 'GET':
            return self._send({'ok': True, 'app': 'ExpObserver', 'version': __version__})
        if path == '/api/workspaces':
            if method == 'GET':
                return self._send({'workspaces': store.list_workspaces()})
            if method == 'POST':
                return self._send({'workspaces': store.add_workspace(self._body())})
        if path == '/api/workspaces/remove' and method == 'POST':
            return self._send({'workspaces': store.remove_workspace(self._body())})
        if path == '/api/agent-setup' and method == 'GET':
            root = Path(__file__).resolve().parents[1]
            return self._send({'skillPath': str(root / 'skills' / 'exp-observer' / 'SKILL.md'),
                               'clientPath': str(root / 'skills' / 'exp-observer' / 'scripts' / 'exp_observer.py'),
                               'pythonPath': sys.executable, 'shell': 'powershell' if os.name == 'nt' else 'posix',
                               'url': f'http://127.0.0.1:{self.server.server_port}'})
        if path == '/api/projects':
            if method == 'GET':
                return self._send({'projects': store.list_projects()})
            if method == 'POST':
                return self._send(store.create_project(self._body()), 201)
        if path == '/api/import' and method == 'POST':
            return self._send(store.import_project(self._body()), 201)
        if path == '/api/events' and method == 'GET':
            p = store.get_project(query.get('project', [''])[0])
            event = f'event: revision\ndata: {canonical({"projectId": p["id"], "revision": p["revision"]})}\n\n'.encode()
            return self._send(event, mime='text/event-stream')
        if parts[:2] == ['api', 'projects'] and len(parts) >= 3:
            project_id = parts[2]
            tail = parts[3:]
            if not tail and method == 'GET':
                return self._send(store.get_project(project_id))
            if tail == ['focus']:
                from . import work_sessions
                if method == 'GET':
                    return self._send(work_sessions.get(store, project_id))
                if method == 'POST':
                    return self._send(work_sessions.update(store, project_id, self._body()))
            if tail == ['usage-status'] and method == 'GET':
                store.get_project(project_id)
                recovery = self.server.recovery
                importer = recovery.host_usage if recovery is not None else None
                return self._send(importer.status(project_id) if importer is not None else {
                    'projectId': project_id, 'adapters': [], 'available': False})
            if tail == ['runtime'] and method == 'GET':
                store.get_project(project_id)
                recovery = self.server.recovery
                return self._send(recovery.runtime(project_id) if recovery is not None else {
                    'projectId': project_id, 'checkedAt': now(), 'source': 'unavailable', 'active': []})
            if tail == ['delivery-status'] and method == 'GET':
                store.get_project(project_id)
                recovery = self.server.recovery
                return self._send(recovery.delivery_status(project_id) if recovery is not None else {
                    'projectId': project_id, 'available': False, 'checkedAt': now(), 'state': 'unknown',
                    'scope': 'connected-workspaces', 'discoveryComplete': False, 'pendingCount': 0,
                    'blockedCount': 0, 'interruptedCount': 0, 'syncedCount': 0, 'items': []})
            if tail == ['delivery', 'retry'] and method == 'POST':
                store.get_project(project_id)
                body = self._body() if self.headers.get('Content-Length', '0') != '0' else {}
                if not isinstance(body, dict) or set(body) - {'taskId'} or ('taskId' in body and
                        (not isinstance(body['taskId'], str) or not body['taskId'])):
                    raise StoreError('Retry accepts only an optional taskId.', 'invalid_body')
                recovery = self.server.recovery
                if recovery is None:
                    raise StoreError('Queue recovery is unavailable.', 'recovery_unavailable', 409)
                return self._send(recovery.retry_delivery(project_id, body.get('taskId')))
            if tail == ['context'] and method == 'GET':
                return self._send(store.context(project_id, query.get('node', [None])[0]))
            if tail == ['batch'] and method == 'POST':
                return self._send(store.batch(project_id, self._body(limit=MAX_BATCH_BODY)))
            if tail == ['artifacts'] and method == 'POST':
                return self._send(store.register_artifact(project_id, self._body()), 201)
            if len(tail) == 3 and tail[0] == 'artifacts' and tail[2] == 'metadata' and method == 'GET':
                return self._send(store.artifact_metadata(project_id, tail[1]))
            if len(tail) == 3 and tail[0] == 'artifacts' and tail[2] == 'content' and method == 'GET':
                try:
                    offset = int(query['offset'][0]) if 'offset' in query else None
                    limit = int(query['limit'][0]) if 'limit' in query else None
                except ValueError:
                    raise StoreError('Preview offset and limit must be integers.', 'invalid_preview_range')
                raw, artifact = store.artifact_content(project_id, tail[1], offset, limit)
                # Text evidence is always inert, including HTML and SVG.
                text_like = artifact.get('mime', '').startswith('text/') or artifact.get('mime') in ('application/json', 'application/x-ndjson', 'application/javascript')
                mime = 'text/plain; charset=utf-8' if text_like else 'application/octet-stream'
                return self._send(raw, mime=mime, attachment=None if text_like else artifact['id'] + '.bin')
            if tail == ['export'] and method == 'GET':
                return self._send(store.get_project(project_id), attachment=project_id + '.json')
            if tail == ['history'] and method == 'GET':
                return self._send({'history': store.history(project_id)})
            if tail == ['restore'] and method == 'POST':
                return self._send(store.restore(project_id, self._body()))
        if path.startswith('/api/'):
            raise StoreError('API route not found.', 'not_found', 404)
        if method != 'GET':
            raise StoreError('Method not allowed.', 'method_not_allowed', 405)
        if '\x00' in path:
            raise StoreError('Invalid path.')
        target = (self.server.dist / path.lstrip('/')).resolve()
        if not target.is_relative_to(self.server.dist):
            raise StoreError('Invalid path.', 'path_not_allowed', 403)
        if not target.is_file() and not Path(path).suffix:
            target = self.server.dist / 'index.html'
        if not target.is_file():
            raise StoreError('Build the frontend to open ExpObserver.', 'not_found', 404)
        # Windows registry entries may misidentify JavaScript and break strict MIME checks.
        mime = STATIC_MIME.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        return self._send(target.read_bytes(), mime=mime)


def main(argv=None):
    parser = argparse.ArgumentParser(description='ExpObserver local experiment workspace')
    parser.add_argument('--port', type=int, default=4317)
    parser.add_argument('--data-dir', default=str(Path(__file__).resolve().parents[1] / '.exp-observer'))
    parser.add_argument('--no-demo', action='store_true')
    parser.add_argument('--open', action='store_true', help='Open the interface in your browser')
    parser.add_argument('--no-browser', action='store_true', help='Keep the browser closed when using a launcher')
    parser.add_argument('--workspace', action='append', default=[], help='Enroll a research directory for automatic recovery; repeat as needed')
    args = parser.parse_args(argv)
    store = Store(args.data_dir)
    for workspace in args.workspace:
        store.add_workspace({'path': str(Path(workspace).expanduser().resolve())})
    if not args.no_demo and not store.list_projects():
        try:
            from .seed import make_demo
            store.import_project(make_demo())
        except ImportError:
            pass
    server = Server(('127.0.0.1', args.port), store, recovery=True)
    try:
        from .recovery import load_client
        client = load_client()
        registry = client.state_directory() / ('platform-' + str(server.server_port) + '.json')
        client.ensure_directory(registry.parent)
        client.save_task(registry, {'appRoot': str(Path(__file__).resolve().parents[1]),
                                    'dataDir': str(Path(args.data_dir).expanduser().resolve())})
    except (OSError, ValueError):
        pass  # Optional startup discovery must not prevent serving research.
    print(f'ExpObserver http://127.0.0.1:{server.server_port}', flush=True)
    if args.open and not args.no_browser:
        import threading
        import webbrowser
        threading.Thread(target=webbrowser.open, args=(f'http://127.0.0.1:{server.server_port}',), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
