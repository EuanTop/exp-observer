"""Best-effort local startup. Research capture works even when startup cannot."""
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen
from urllib.request import HTTPRedirectHandler
import zipfile

RELEASE = 'https://github.com/EuanTop/exp-observer/releases/latest/download/'
MAX_ARCHIVE = 64 * 1024 * 1024


class LaunchBusy(Exception):
    pass


def origin(url):
    try:
        p = urlsplit(url)
        if (p.scheme != 'http' or p.hostname not in ('localhost', '127.0.0.1') or
                p.username or p.password or p.path not in ('', '/') or p.query or p.fragment):
            return None
        port = p.port or 80
        return port if 1 <= port <= 65535 else None
    except ValueError:
        return None


def windows_listener(port):
    """Read the IPv4/IPv6 listener tables without reserving or connecting a port.

    GetExtendedTcpTable / MIB_TCPROW_OWNER_PID (six DWORD fields):
    https://learn.microsoft.com/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable
    Unknown API results fall back to the normal HTTP identity check.
    """
    try:
        import ctypes
        get_table = ctypes.WinDLL('iphlpapi').GetExtendedTcpTable
        get_table.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
                              ctypes.c_int, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        get_table.restype = ctypes.c_uint32
        for family, pattern in ((socket.AF_INET, '<6I'), (socket.AF_INET6, '<16sII16sIIII')):
            length = ctypes.c_uint32(0)
            buffer = None
            for _ in range(3):
                result = get_table(buffer, ctypes.byref(length), 0, family, 3, 0)
                if result == 122 and 4 <= length.value <= 8 * 1024 * 1024:
                    buffer = ctypes.create_string_buffer(length.value)
                    continue
                if result or buffer is None or length.value < 4:
                    return None
                data = buffer.raw[:length.value]
                count = struct.unpack_from('<I', data)[0]
                stride = struct.calcsize(pattern)
                if count > (len(data) - 4) // stride:
                    return None
                for row in struct.iter_unpack(pattern, data[4:4+stride*count]):
                    if family == socket.AF_INET:
                        state, address, local = row[:3]
                        loopback = address in (0, 0x0100007f)
                    else:
                        address, _, local, _, _, _, state, _ = row
                        loopback = address in (bytes(16), bytes(15)+b'\x01', bytes(10)+b'\xff\xff\x7f\x00\x00\x01')
                    if state == 2 and loopback and socket.ntohs(local & 0xffff) == port:
                        return True
                break
            else:
                return None
        return False
    except (OSError, AttributeError, ValueError, struct.error):
        return None


def probe(url):
    # A refused Windows connection can exceed a short HTTP deadline. Query the
    # OS listener tables instead of binding the port our child will need.
    if os.name == 'nt' and origin(url) is not None and windows_listener(origin(url)) is False:
        return 'missing'
    # Bypass proxy settings for a local service; do not follow redirects to a
    # different destination or mistake another listener for this application.
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    # Windows reports a refused localhost TCP connection after roughly one
    # second; a shorter deadline misclassifies a stopped platform as blocked.
    timeout = 1.5 if os.name == 'nt' else .35
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(url.rstrip('/') + '/api/health', timeout=timeout) as response:
            value = json.loads(response.read(8192))
        if value.get('ok') is True and value.get('app') == 'ExpObserver':
            return 'ready'
        # Older installed versions expose identity through agent setup.
        if value.get('ok') is True and isinstance(value.get('version'), str):
            with build_opener(ProxyHandler({}), NoRedirect()).open(url.rstrip('/') + '/api/agent-setup', timeout=timeout) as response:
                setup = json.loads(response.read(16384))
            if str(setup.get('clientPath', '')).replace('\\', '/').endswith('/scripts/exp_observer.py'):
                return 'ready'
        return 'occupied'
    except HTTPError as exc:
        exc.close()
        return 'occupied'
    except URLError as exc:
        reason = exc.reason
        return 'missing' if isinstance(reason, ConnectionRefusedError) or getattr(reason, 'errno', None) in (errno.ECONNREFUSED, 10061) else 'unavailable'
    except (OSError, ValueError, TypeError, AttributeError, socket.timeout):
        return 'unavailable'


@contextmanager
def launch_lock(path, wait=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b'0'); stream.flush()
        else:
            import fcntl
        deadline = time.monotonic() + wait
        while True:
            try:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise LaunchBusy() from exc
                time.sleep(.05)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.stat().st_size < 65536 else {}
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)


def valid_app(path):
    return all((path / name).is_file() for name in ('start.py', 'backend/server.py', 'dist/index.html'))


def application_candidates(state, port):
    saved = read_json(state / ('platform-' + str(port) + '.json'))
    if os.environ.get('EXP_OBSERVER_APP'):
        yield Path(os.environ['EXP_OBSERVER_APP']).expanduser(), None
    if isinstance(saved.get('appRoot'), str):
        yield Path(saved['appRoot']), saved.get('dataDir')
    # A release or a source checkout with a built interface.
    yield Path(__file__).resolve().parents[3], None
    if os.name == 'nt':
        yield Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'ExpObserver/exp-observer', None
    else:
        yield Path.home() / '.local/share/exp-observer', None


def extract_runtime(archive, state, expected):
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Portable runtime exceeds archive limit')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError('Portable runtime checksum mismatch')
    root = state / 'runtime' / digest
    if valid_app(root):
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.prepare-', dir=root.parent))
    try:
        with zipfile.ZipFile(archive) as bundle:
            if sum(i.file_size for i in bundle.infolist()) > 128 * 1024 * 1024 or len(bundle.infolist()) > 512:
                raise ValueError('Portable runtime exceeds extraction limits')
            for item in bundle.infolist():
                name = item.filename.removeprefix('exp-observer/')
                parts = PurePosixPath(name).parts
                if not parts or any(p in ('..', '.') or ':' in p or '\\' in p for p in parts) or name.startswith('/') or stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError('Invalid portable runtime path')
                # Extract executable application files only, never saved data,
                # other release documents or a recursively bundled runtime.
                allowed = (name in ('start.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md') or name.startswith('licenses/') or name.startswith('backend/') and name.endswith('.py') or
                           name == 'dist/index.html' or name.startswith('dist/assets/') or
                           name.startswith('skills/exp-observer/') and '/assets/' not in name)
                if not allowed or item.is_dir():
                    continue
                target = temporary.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
        if not valid_app(temporary):
            raise ValueError('Portable runtime is missing application files')
        try:
            os.replace(temporary, root)
        except OSError:
            if not valid_app(root):
                raise
        return root
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def detached(command, log, cwd):
    options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    return subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, **options)


def download_runtime(state):
    # Only the official release and its checksum; no caller-supplied URL/code.
    with urlopen(Request(RELEASE + 'SHA256SUMS', headers={'User-Agent': 'ExpObserver'}), timeout=8) as response:
        sums = response.read(16384).decode('utf-8')
    expected = next((line.split()[0] for line in sums.splitlines() if line.split()[-1:] == ['exp-observer.zip']), '')
    if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('Official release checksum is unavailable')
    descriptor, name = tempfile.mkstemp(prefix='.download-', suffix='.zip', dir=state)
    os.close(descriptor)
    archive = Path(name)
    try:
        with urlopen(Request(RELEASE + 'exp-observer.zip', headers={'User-Agent': 'ExpObserver'}), timeout=8) as response, archive.open('wb') as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE:
                    raise ValueError('Official release exceeds download limit')
                output.write(chunk)
        return extract_runtime(archive, state, expected)
    finally:
        archive.unlink(missing_ok=True)


def ensure_platform(url, workspace, state, *, provision=False):
    port = origin(url)
    if port is None or os.environ.get('EXP_OBSERVER_AUTOSTART') == '0':
        return {'state': 'disabled'}
    state = Path(state)
    status_path = state / ('launch-' + str(port) + '.json')
    previous = read_json(status_path)
    launching = previous.get('state') in ('starting', 'provisioning') and time.time() - previous.get('at', 0) < 30
    health = probe(url)
    if health != 'missing':
        return {'state': health}
    if launching:
        return previous
    try:
        with launch_lock(state / ('launch-' + str(port) + '.lock'), wait=2 if provision else 0):
            if probe(url) != 'missing':
                return {'state': probe(url)}
            previous = read_json(status_path)
            if not provision and previous.get('state') != 'ready' and time.time() - previous.get('at', 0) < 30:
                return previous
            write_json(status_path, {'state': 'starting', 'at': time.time()})
            app, data = None, None
            for candidate, saved_data in application_candidates(state, port):
                if valid_app(candidate):
                    app, data = candidate.resolve(), saved_data
                    break
            if app is None:
                bundle = Path(__file__).resolve().parents[1] / 'assets/platform.zip'
                checksum = bundle.with_suffix('.sha256')
                if bundle.is_file() and checksum.is_file():
                    app = extract_runtime(bundle, state, checksum.read_text(encoding='utf-8').split()[0])
                elif provision:
                    app = download_runtime(state)
                else:
                    with (state / 'startup.log').open('ab') as log:
                        process = detached([sys.executable, str(Path(__file__).resolve()), '--provision', '--url', url,
                            '--workspace', str(workspace), '--state', str(state)], log, str(state))
                    value = {'state': 'provisioning', 'pid': process.pid, 'at': time.time()}
                    write_json(status_path, value)
                    return value
            if data is None:
                managed = app.is_relative_to(state / 'runtime')
                data = str(state / 'data' if managed else app / '.exp-observer')
            with (state / 'startup.log').open('ab') as log:
                process = detached([sys.executable, str(app / 'start.py'), '--no-demo', '--no-browser', '--port', str(port),
                                    '--data-dir', data, '--workspace', str(workspace)], log, str(app))
            value = {'state': 'starting', 'pid': process.pid, 'appRoot': str(app), 'dataDir': data, 'at': time.time()}
            write_json(status_path, value)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and process.poll() is None:
                if probe(url) == 'ready':
                    value['state'] = 'ready'; break
                time.sleep(.05)
            write_json(status_path, value)
            return value
    except LaunchBusy:
        return {'state': 'starting'}
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        existing = read_json(status_path)
        if isinstance(exc, OSError) and existing.get('state') in ('starting', 'provisioning') and time.time() - existing.get('at', 0) < 30:
            return existing
        value = {'state': 'unavailable', 'at': time.time(), 'message': str(exc)[:200]}
        # Startup failure must never abort a queued experiment record.
        try:
            write_json(status_path, value)
        except OSError:
            pass
        return value


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--provision', action='store_true')
    parser.add_argument('--url', required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    ensure_platform(args.url, args.workspace, args.state, provision=args.provision)
