#!/usr/bin/env python3
"""Standalone ExpObserver client with durable, nonblocking experiment capture."""
from __future__ import annotations
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen
from uuid import uuid4


class ClientError(Exception):
    def __init__(self, message, *, code=None, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        response.close()
        raise ClientError('Automatic recovery does not follow HTTP redirects.', code='redirect_not_allowed', status=code)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def emit(value, stream=sys.stdout):
    print(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False), file=stream)


class Client:
    def __init__(self, url, timeout=30, transport_url=None, local_only=False, queue_root=None):
        self.url = url.rstrip('/')
        self.timeout = timeout
        self.transport_url = (transport_url or self.url).rstrip('/')
        self.queue_root = Path(queue_root).resolve() if queue_root is not None else None
        if local_only and loopback_origin(self.transport_url) is None:
            raise ClientError('Automatic recovery requires a loopback HTTP origin.')
        self.opener = build_opener(ProxyHandler({}), NoRedirect()) if local_only else None

    def request(self, route, body=None, raw=False):
        data = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        request = Request(self.transport_url + route, data=data, headers={'Content-Type': 'application/json'})
        try:
            with (self.opener.open(request, timeout=self.timeout) if self.opener else urlopen(request, timeout=self.timeout)) as response:
                content = response.read()
                return content if raw else json.loads(content)
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read())
                if not isinstance(detail, dict):
                    raise ValueError('Invalid error response')
                code = detail.get('code', str(exc.code))
                raise ClientError(f'{code}: {detail.get("error", exc.reason)}', code=code, status=exc.code) from exc
            except (ValueError, UnicodeError):
                raise ClientError(f'HTTP {exc.code}: {exc.reason}', code='http_error', status=exc.code) from exc
            finally:
                exc.close()
        except (URLError, TimeoutError, OSError) as exc:
            raise ClientError(f'Cannot reach ExpObserver at {self.url}: {exc.reason if isinstance(exc, URLError) else exc}', code='unavailable') from exc

    def project_route(self, project):
        return '/api/projects/' + quote(project, safe='')

    def project(self, project):
        return self.request(self.project_route(project))

    def apply(self, project, operations, revision=None, request_id=None):
        body = {'operations': operations, 'requestId': request_id or 'req-' + uuid4().hex}
        if revision is not None:
            body['expectedRevision'] = revision
        return self.request(self.project_route(project) + '/batch', body)


def parser():
    root = argparse.ArgumentParser(description='Maintain independent ExpObserver experiment records.')
    root.add_argument('--url', default=os.environ.get('EXP_OBSERVER_URL') or 'http://127.0.0.1:4317')
    commands = root.add_subparsers(dest='command', required=True)
    commands.add_parser('projects', help='List experiments')
    init = commands.add_parser('init', help='Create an experiment')
    init.add_argument('--name', required=True)
    init.add_argument('--id')
    init.add_argument('--description', default='')
    init.add_argument('--source-root', action='append', default=[])
    record = commands.add_parser('record', help='Record work; generate IDs, references and a durable retry automatically')
    record.add_argument('--project', required=True)
    record.add_argument('--title', required=True)
    record.add_argument('--summary')
    record.add_argument('--conclusion', help='The substantive finding displayed directly on the node')
    record.add_argument('--kind', help='Natural research type, e.g. question, experiment, finding or decision; omitted updates preserve the type')
    notes = record.add_mutually_exclusive_group()
    notes.add_argument('--notes', help='Full analysis retained in the node notes')
    notes.add_argument('--notes-file', help='UTF-8 analysis loaded verbatim into node notes; - reads stdin without creating a report file')
    record.add_argument('--node', help='Update this node; omit to create a node')
    record.add_argument('--after', help='Related node ID or exact locally recorded title')
    record.add_argument('--relation', default='leads_to', help='Meaning of an explicit --after relationship')
    record.add_argument('--independent', action='store_true', help='Omit the automatic record-order connection')
    record.add_argument('--parent')
    record.add_argument('--status', default=None, help='Node status (default for new nodes: active)')
    record.add_argument('--metrics-file', help='UTF-8 JSON; nested objects are preserved and other root values use a result key')
    record.add_argument('--artifact', action='append', default=[])
    record.add_argument('--request-id', help='Stable identifier for retries of this record')
    sync = commands.add_parser('sync', help='Retry local pending records without executing experiments')
    sync.add_argument('--project', help='Only sync this project')
    status_command = commands.add_parser('status', help='Read current durable queue receipts locally, without HTTP or polling')
    status_command.add_argument('--project', required=True)
    observe = commands.add_parser('observe', help='Record a node step duration and explicit runtime token counters')
    observation_actions = observe.add_subparsers(dest='observation_action', required=True)
    for action in ('start', 'finish'):
        observation = observation_actions.add_parser(action)
        observation.add_argument('--project', required=True)
        observation.add_argument('--request-id', help='Stable retry identifier')
        if action == 'start':
            observation.add_argument('--node', required=True)
            observation.add_argument('--title', default='')
        else:
            observation.add_argument('--id', required=True, help='Observation ID returned by start')
            observation.add_argument('--input-tokens', type=int)
            observation.add_argument('--output-tokens', type=int)
            observation.add_argument('--usage-source', help='Runtime or provider counter source; required for supplied token counts')
            observation.add_argument('--usage-ref', help='Unique usage record reference within this source')
    for command in ('context', 'apply', 'artifact', 'export', 'check', 'execute', 'read'):
        options = {'help': 'Read a verified artifact byte range', 'description': 'Read a verified artifact byte range. Defaults: offset 0, limit 262144 bytes; maximum limit 1048576. Text goes to stdout; --output saves the original range bytes.'} if command == 'read' else {}
        cmd = commands.add_parser(command, **options)
        cmd.add_argument('--project', required=True)
        if command in ('context', 'artifact', 'execute'):
            cmd.add_argument('--node', help='Existing node; execute creates a node when omitted')
        if command == 'apply':
            cmd.add_argument('--file')
            cmd.add_argument('--expected-revision', type=int)
            cmd.add_argument('--request-id')
        if command == 'artifact':
            cmd.add_argument('--path', required=True, nargs='+')
            cmd.add_argument('--title')
            cmd.add_argument('--run')
        if command == 'export':
            cmd.add_argument('--output')
        if command == 'read':
            cmd.add_argument('--artifact', required=True)
            cmd.add_argument('--offset', type=int, default=0, help='Starting byte offset (default: 0)')
            cmd.add_argument('--limit', type=int, default=262144, help='Maximum bytes to read, up to 1048576 (default: 262144)')
            cmd.add_argument('--output', help='Save original range bytes to this file instead of printing text')
        if command == 'execute':
            cmd.add_argument('--title', required=True)
            cmd.add_argument('--after', help='Related node ID or exact locally recorded title')
            cmd.add_argument('--relation', default='leads_to')
            cmd.add_argument('--independent', action='store_true', help='Omit the automatic record-order connection')
            cmd.add_argument('--request-id', help='Stable identifier; retries never rerun this command')
            cmd.add_argument('--artifact', action='append', default=[], help='Capture a result file after execution; repeat for multiple files')
            cmd.add_argument('argv', nargs=argparse.REMAINDER)
    return root


def capture_root(project_id):
    directory = project_id
    stem = directory.split('.')[0].upper()
    if directory != directory.lower() or directory.endswith('.') or stem in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} or re.fullmatch(r'(COM|LPT)[1-9]', stem):
        directory = '~' + hashlib.sha256(directory.encode('utf-8')).hexdigest()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', directory):
        directory = '~' + hashlib.sha256(project_id.encode('utf-8')).hexdigest()
    return (Path.cwd() / '.exp-observer-runs' / directory).resolve()


def sync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def ensure_directory(path):
    missing, ancestor = [], path
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    path.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing):
        sync_directory(created.parent)


def save_task(path, task):
    """Atomic replacement keeps a timeout or interrupted sync safely retryable."""
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(task, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def task_lock(path):
    """An OS lock is released on process death, including on Windows."""
    ensure_directory(path.parent)
    with path.with_suffix('.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0, os.SEEK_END)
            if not lock.tell():
                lock.write(b'\0')
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ClientError('This local record is already being processed.', code='busy') from exc
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ClientError('This local record is already being processed.', code='busy') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def state_directory():
    """Only the small directory registry is shared between workspaces."""
    override = os.environ.get('EXP_OBSERVER_STATE_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Local')
        return base / 'ExpObserver'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'ExpObserver'
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state') / 'exp-observer'


def loopback_origin(url):
    """Automatic recovery accepts only an explicit local HTTP origin."""
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else 80
        hostname = '127.0.0.1' if parsed.hostname == 'localhost' else parsed.hostname
        return (hostname, port) if 1 <= port <= 65535 else None
    except ValueError:
        return None


def register_outbox(outbox, url):
    if loopback_origin(url) is None:
        return 'Automatic recovery requires a loopback HTTP URL; this outbox remains available to manual sync.'
    outbox = str(Path(outbox).resolve())
    key = hashlib.sha256(json.dumps([url, outbox], ensure_ascii=False).encode('utf-8')).hexdigest()
    registration = state_directory() / 'outboxes' / (key + '.json')
    try:
        with task_lock(registration):
            if not registration.exists():
                save_task(registration, {'version': 1, 'url': url, 'outbox': outbox, 'registeredAt': stamp()})
    except (ClientError, OSError, ValueError) as exc:
        return f'Automatic recovery registration is unavailable; the durable outbox is retained: {exc}'
    return None


def persist_task(path, task):
    # Research clients write only inside their working directory. The application
    # discovers queues in enrolled workspaces, including future experiment folders.
    save_task(path, task)


def project_plan_path(outbox, url, project_id):
    key = hashlib.sha256(json.dumps([url, project_id], ensure_ascii=False).encode('utf-8')).hexdigest()[:32]
    return Path(outbox) / ('project-' + key + '.json')


def prepare_project(outbox, url, metadata, implicit=False):
    """First writer freezes a creation plan; later captures never edit it."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', metadata['id']):
        raise ClientError('Project IDs must use 1–128 letters, numbers, dots, underscores or hyphens.')
    path = project_plan_path(outbox, url, metadata['id'])
    with task_lock(path):
        if path.exists():
            plan = json.loads(path.read_text(encoding='utf-8'))
            return path, plan
        plan = {'version': 1, 'kind': 'project', 'url': url, 'projectId': metadata['id'],
                'project': metadata, 'implicit': implicit, 'preparedAt': stamp(), 'state': 'ready',
                'recordingWarnings': []}
        persist_task(path, plan)
        return path, plan


def ensure_project(client, path, plan):
    """Create only after a confirmed not_found. Never update an existing project."""
    try:
        project = client.project(plan['projectId'])
    except ClientError as exc:
        if not str(exc).startswith('not_found:'):
            raise
        try:
            project = client.request('/api/projects', plan['project'])
        except ClientError as creation_error:
            if not str(creation_error).startswith('conflict:'):
                raise
            # A concurrent creator may have won after our GET.
            project = client.project(plan['projectId'])
    if plan['state'] != 'synced':
        plan['state'] = 'synced'
        save_task(path, plan)
    return project


def sync_project(client, path, plan):
    warnings = list(plan['recordingWarnings'])
    project = None
    try:
        project = ensure_project(client, path, plan)
    except (ClientError, OSError, ValueError) as exc:
        warnings.append(str(exc))
    source = project if project is not None else plan['project']
    result = {key: source[key] for key in ('id', 'name', 'description', 'revision') if key in source}
    result.update({'projectId': plan['projectId'], 'pending': project is None, 'preparedAt': plan['preparedAt'],
                   'availability': 'available' if project is not None else 'unavailable'})
    if warnings:
        result['recordingWarnings'] = warnings
    return result


def pending_project_receipt(project_id, plan=None):
    result = {'id': project_id, 'projectId': project_id, 'pending': plan is not None,
              'availability': 'pending' if plan is not None else 'unavailable'}
    warnings = []
    if plan is not None:
        result.update({key: plan['project'][key] for key in ('name', 'description') if key in plan['project']})
        if isinstance(plan.get('preparedAt'), str):
            result['preparedAt'] = plan['preparedAt']
        warnings.extend(plan.get('recordingWarnings', []))
    warnings.append('Project initialization is already being processed.' if plan is not None else
                    'Project initialization is already being processed, but a durable project plan could not be confirmed.')
    result['recordingWarnings'] = warnings
    return result


def init(client, args):
    if not args.name.strip():
        raise ClientError('Experiment name is required.')
    project_id = args.id or 'study-' + hashlib.sha256(json.dumps(
        [client.url, str(Path.cwd().resolve()), args.name.strip()], ensure_ascii=False).encode('utf-8')).hexdigest()[:24]
    metadata = {'id': project_id, 'name': args.name.strip(), 'description': args.description,
                'sourceRoots': [str(Path(root).expanduser().resolve()) for root in args.source_root]}
    outbox = Path.cwd() / '.exp-observer-runs' / 'outbox'
    path, plan = project_plan_path(outbox, client.url, project_id), None
    try:
        path, plan = prepare_project(outbox, client.url, metadata)
        with task_lock(path):
            plan = json.loads(path.read_text(encoding='utf-8'))
            result = sync_project(client, path, plan)
    except ClientError as exc:
        if exc.code != 'busy':
            raise
        if plan is None:
            # A readable atomic snapshot can confirm frozen metadata. Windows may
            # refuse this read during replacement; then report only the known ID.
            try:
                candidate = read_queue_task(path)
                if (candidate.get('kind') == 'project' and candidate['url'] == client.url
                        and candidate['projectId'] == project_id and isinstance(candidate.get('project'), dict)
                        and candidate['project'].get('id') == project_id
                        and isinstance(candidate['project'].get('name'), str) and isinstance(candidate.get('preparedAt'), str)):
                    plan = candidate
            except (OSError, ValueError, KeyError, TypeError):
                pass
        # When preparation already returned a plan, use that snapshot directly:
        # no further reads, writes or HTTP requests while recovery owns its lock.
        result = pending_project_receipt(project_id, plan)
    if plan is not None and plan['project'] != metadata:
        result.setdefault('recordingWarnings', []).append('Creation metadata was already prepared; the original plan is retained.')
    emit(result)
    return 0


def read_queue_task(path):
    task = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(task, dict) or any(not isinstance(task.get(key), str) for key in ('url', 'projectId', 'state')):
        raise ValueError('Queued records require an object with url, projectId and state text fields.')
    return task


def local_context(outbox, client, project_id, node_id=None):
    project, records = None, []
    node_updates = []
    for path in Path(outbox).glob('*.json'):
        try:
            task = read_queue_task(path)
            if task['url'] != client.url or task['projectId'] != project_id:
                continue
            if task.get('kind') == 'project':
                project = {'metadata': task['project'], 'preparedAt': task['preparedAt'], 'state': task['state']}
            else:
                record = {key: task[key] for key in
                          ('requestId', 'nodeId', 'runId', 'state', 'capturedAt', 'startedAt', 'finishedAt') if key in task}
                record['localTaskPath'] = str(path.resolve())
                record['operations'] = []
                for index, operation in enumerate(task.get('operations', [])):
                    data = operation.get('data', {})
                    detail = {'op': operation['op'], **{key: data[key] for key in
                              ('id', 'title', 'kind', 'status', 'nodeId', 'source', 'target', 'parentId') if key in data}}
                    for field, limit in (('summary', 512), ('conclusion', 512)):
                        if isinstance(data.get(field), str):
                            detail[field] = data[field][:limit]
                            if len(data[field]) > limit:
                                detail[field + 'Truncated'] = True
                    if isinstance(data.get('notes'), str):
                        detail.update({'notes': data['notes'], 'hasNotes': bool(data['notes'])})
                    if operation['op'] in ('node.add', 'node.update') and isinstance(data.get('id'), str):
                        fields = ('id', 'title', 'kind', 'status', 'parentId', 'summary', 'conclusion', 'notes')
                        node_updates.append(((task.get('capturedAt') or task.get('startedAt') or '', path.name, index),
                                             {key: data[key] for key in fields if key in data}))
                    record['operations'].append(detail)
                record['artifactCount'] = len(task.get('artifacts', []))
                records.append(record)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    records.sort(key=lambda record: record.get('capturedAt') or record.get('startedAt') or '')
    # Fold all local updates before applying the receipt window: an old notes
    # operation can remain current after many later summary-only revisions.
    nodes = {}
    for _, update in sorted(node_updates, key=lambda entry: entry[0]):
        nodes.setdefault(update['id'], {}).update(update)
    scoped = {node_id} if node_id else set()
    if node_id:
        changed = True
        while changed:
            children = {key for key, node in nodes.items() if node.get('parentId') in scoped}
            changed = bool(children - scoped)
            scoped.update(children)
    for record in records:
        for detail in record['operations']:
            if detail.get('id') not in scoped:
                detail.pop('notes', None)
    local_nodes = []
    for key, node in nodes.items():
        if node_id and key not in scoped:
            continue
        detail = {field: node[field] for field in ('id', 'title', 'kind', 'status', 'parentId') if field in node}
        for field in ('summary', 'conclusion'):
            if isinstance(node.get(field), str):
                detail[field] = node[field][:512]
                if len(node[field]) > 512:
                    detail[field + 'Truncated'] = True
        detail['hasNotes'] = isinstance(node.get('notes'), str) and bool(node['notes'])
        if node_id and isinstance(node.get('notes'), str):
            detail['notes'] = node['notes']
        local_nodes.append(detail)
    pending = [record for record in records if record['state'] != 'synced']
    return project, records, pending, local_nodes


def context(client, args):
    workspace = Path.cwd() / '.exp-observer-runs'
    key = hashlib.sha256(json.dumps([client.url, args.project, args.node], ensure_ascii=False).encode('utf-8')).hexdigest()
    cache_path = workspace / 'context' / (key + '.json')
    project, records, pending, local_nodes = local_context(workspace / 'outbox', client, args.project, args.node)
    try:
        route = client.project_route(args.project) + '/context'
        if args.node:
            route += '?' + urlencode({'node': args.node})
        result = client.request(route)
    except (ClientError, OSError, ValueError) as exc:
        cached = None
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        has_pending = bool(pending or (project and project['state'] != 'synced'))
        rejected = isinstance(exc, ClientError) and exc.status is not None
        pending_project = rejected and exc.code == 'not_found' and 'Experiment not found.' in str(exc) and has_pending
        result = {'projectId': args.project, 'availability': 'pending' if pending_project else ('error' if rejected else 'unavailable'),
                  'pending': has_pending,
                  'cachedRemote': cached, 'localProject': project, 'localNodes': local_nodes, 'localRecords': records[-20:],
                  'localPending': pending[-20:], 'localRecordCount': len(records), 'localPendingCount': len(pending),
                  'recordingWarnings': [str(exc)]}
        if rejected:
            result['remoteError'] = {'code': exc.code, 'status': exc.status, 'message': str(exc)}
            if not pending_project:
                result['error'] = str(exc)
        emit(result)
        return 1 if rejected and not pending_project else 0
    fetched_at = stamp()
    try:
        ensure_directory(cache_path.parent)
        save_task(cache_path, {'cachedAt': fetched_at, 'nodeId': args.node, 'context': result})
    except OSError as exc:
        result.setdefault('recordingWarnings', []).append(f'Context cache unavailable: {exc}')
    result.update({'availability': 'available', 'pending': bool(pending), 'fetchedAt': fetched_at})
    if pending:
        result['localPending'] = pending[-20:]
        result['localPendingCount'] = len(pending)
        pending_ids = {record.get('nodeId') for record in pending}
        result['localPendingNodes'] = [node for node in local_nodes if node['id'] in pending_ids]
    emit(result)
    return 0


def task_identity(client, args, intent):
    request_id = getattr(args, 'request_id', None) or 'capture-' + uuid4().hex
    key = hashlib.sha256(json.dumps([client.url, args.project, request_id], ensure_ascii=False).encode('utf-8')).hexdigest()[:32]
    path = Path.cwd() / '.exp-observer-runs' / 'outbox' / (key + '.json')
    task = {'version': 1, 'taskId': key, 'requestId': request_id, 'url': client.url,
            'projectId': args.project, 'intent': intent, 'state': 'preparing',
            'nodeId': args.node or 'node-' + key, 'runId': 'run-' + key,
            'captureRoot': str(capture_root(args.project)), 'artifacts': [], 'recordingWarnings': []}
    return path, task


def load_existing(path, task, *, frozen_notes=False):
    if not path.exists():
        return None
    existing = json.loads(path.read_text(encoding='utf-8'))
    defaults = {'conclusion': None, 'independent': False, 'relation': 'leads_to', 'after': None,
                'kind': None, 'notes': None, 'notesFile': None}
    expected = defaults | task['intent']
    if frozen_notes:
        retained_notes = existing.get('intent', {}).get('notes')
        if not isinstance(retained_notes, str):
            raise ClientError('The durable capture has no frozen analysis for this retry.', code='queue_identity_conflict')
        expected['notes'] = retained_notes
    if (defaults | existing.get('intent', {})) != expected:
        raise ClientError('request-id was already used for different work; use a new request-id.')
    return existing


def ancestor_outboxes(outbox, queue_root=None):
    """Only the current folder and its ancestors; never inspect sibling research."""
    directory = Path(outbox).parent.parent.resolve()
    boundary = Path(queue_root).resolve() if queue_root is not None else None
    if boundary is not None and directory != boundary and boundary not in directory.parents:
        return
    for ancestor in (directory, *directory.parents):
        yield ancestor / '.exp-observer-runs' / 'outbox'
        if ancestor == boundary:
            break


def local_nodes(client, outbox, project_id, exclude=None):
    nodes = {}
    for directory in ancestor_outboxes(outbox, client.queue_root):
        try:
            paths = list(directory.glob('*.json'))
        except OSError:
            continue
        for path in paths:
            if path == exclude:
                continue
            try:
                task = read_queue_task(path)
                if (task['url'] != client.url or task['projectId'] != project_id
                        or task['state'] not in ('ready', 'synced') or task.get('kind') == 'project'):
                    continue
                at = task.get('capturedAt') or task.get('finishedAt') or task.get('startedAt') or ''
                for operation in task.get('operations', []):
                    if operation.get('op') not in ('node.add', 'node.update'):
                        continue
                    data = operation['data']
                    entry = {'id': data['id'], 'title': data.get('title', ''), 'at': at}
                    if entry['id'] not in nodes or entry['at'] > nodes[entry['id']]['at']:
                        nodes[entry['id']] = entry
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
    return sorted(nodes.values(), key=lambda node: (node['at'], node['id']))


def capture_project_plan(outbox, url, project_id, queue_root=None):
    plans = []
    for directory in ancestor_outboxes(outbox, queue_root):
        path = project_plan_path(directory, url, project_id)
        try:
            if queue_root is not None and not path.resolve().is_relative_to(queue_root):
                continue
            plan = read_queue_task(path)
            if (plan.get('kind') == 'project' and plan['url'] == url and plan['projectId'] == project_id
                    and isinstance(plan.get('project'), dict) and plan['project'].get('id') == project_id):
                plans.append((bool(plan.get('implicit')), plan.get('preparedAt', ''), str(path), path, plan))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if plans:
        _, _, _, path, plan = min(plans, key=lambda entry: entry[:3])
        return path, plan
    return prepare_project(outbox, url,
        {'id': project_id, 'name': project_id, 'description': '', 'sourceRoots': []}, implicit=True)


def capture_relationship(client, args, path, task):
    """Record order is observed chronology, never an invented scientific cause."""
    if not args.after and (args.node or args.independent):
        return
    nodes = local_nodes(client, path.parent, task['projectId'], exclude=path)
    source = args.after
    if source:
        matches = [node for node in nodes if node['title'] == source]
        if len(matches) == 1:
            source = matches[0]['id']
        elif len(matches) > 1:
            task['recordingWarnings'].append('Relationship title is ambiguous; the finding is retained without that relationship.')
            return
        elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', source):
            task['recordingWarnings'].append('Relationship title was not found locally; the finding is retained without that relationship.')
            return
        relation, label = args.relation, ''
    else:
        candidates = [node for node in nodes if node['id'] != task['nodeId']]
        if not candidates:
            return
        source = candidates[-1]['id']
        relation, label = 'recorded_after', '记录顺序'
    if source == task['nodeId']:
        return
    task['operations'].append({'op': 'edge.add', 'data': {
        'id': 'edge-' + task['taskId'], 'source': source, 'target': task['nodeId'],
        'relation': relation, 'label': label, 'basis': 'observed'}})


def file_digest(path):
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def stage_artifact(task, source, title, target):
    source = Path(source)
    try:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise OSError('Evidence is missing or is not a regular file')
        if source != target:
            shutil.copyfile(source, target)
        # Flush snapshots before persisting the task that refers to them.
        with target.open('r+b') as stream:
            os.fsync(stream.fileno())
        sync_directory(target.parent)
        sha256, size = file_digest(target)
        index = len(task['artifacts'])
        task['artifacts'].append({'id': f'artifact-{task["taskId"]}-{index}', 'path': str(target),
                                  'title': title, 'nodeId': task['nodeId'], 'runId': task['runId'],
                                  'sha256': sha256, 'bytes': size, 'capturedAt': stamp()})
    except (OSError, ValueError, RuntimeError) as exc:
        task['recordingWarnings'].append(f'Evidence {source}: {exc}')


def merge_source_root(client, task):
    """CAS merge avoids losing roots added concurrently by another agent."""
    for attempt in range(4):
        project = client.project(task['projectId'])
        roots = project.get('sourceRoots', [])
        if task['captureRoot'] in roots:
            return
        operations = [{'op': 'project.update', 'data': {'sourceRoots': roots + [task['captureRoot']]}}]
        fingerprint = hashlib.sha256(json.dumps(operations, sort_keys=True).encode()).hexdigest()[:24]
        try:
            client.apply(task['projectId'], operations, project['revision'], f'roots-{fingerprint}-{project["revision"]}')
            return
        except ClientError as exc:
            if 'revision_conflict:' not in str(exc) or attempt == 3:
                raise


def sync_task(client, path, task):
    # A background worker may have acknowledged the frozen task since this
    # caller read it. The atomic on-disk receipt is authoritative, even offline.
    current = read_queue_task(path)
    identity = ('url', 'projectId', 'taskId', 'requestId', 'nodeId', 'runId', 'intent')
    if current['url'] != client.url or any(current.get(key) != task.get(key) for key in identity):
        raise ClientError('The durable queue identity differs from this capture; refusing to submit or overwrite it.', code='queue_identity_conflict')
    task = current
    if task['state'] == 'synced':
        return task_result(task)
    if task['state'] != 'ready':
        return task_result(task, ['Capture was interrupted before its outcome was saved; sync never reruns commands.'])
    warnings = []
    try:
        if client.queue_root is not None:
            local_plan = project_plan_path(path.parent, client.url, task['projectId'])
            for staged in [task['captureRoot'], local_plan, local_plan.with_suffix('.lock'),
                           *[artifact['path'] for artifact in task['artifacts']]]:
                resolved = Path(staged).resolve()
                if resolved != client.queue_root and client.queue_root not in resolved.parents:
                    raise ClientError('Queued evidence is outside the connected research directory.', code='path_not_allowed')
        plan_path, plan = capture_project_plan(path.parent, client.url, task['projectId'], client.queue_root)
        if client.queue_root is not None:
            for candidate in (plan_path, plan_path.with_suffix('.lock')):
                resolved = candidate.resolve()
                if resolved != client.queue_root and client.queue_root not in resolved.parents:
                    raise ClientError('Project preparation is outside the connected research directory.', code='path_not_allowed')
        with task_lock(plan_path):
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            ensure_project(client, plan_path, plan)
        # All operations (including timestamps) are frozen before the first send.
        client.apply(task['projectId'], task['operations'], request_id='capture-' + task['taskId'])
        if task['artifacts']:
            merge_source_root(client, task)
            project = client.project(task['projectId'])
            registered = {a['id']: a for a in project['artifacts']}
            for artifact in task['artifacts']:
                expected = dict(artifact)
                expected['nodeId'] = project.get('nodeAliases', {}).get(artifact['nodeId'], artifact['nodeId'])
                existing = registered.get(artifact['id'])
                if existing:
                    if any(existing.get(key) != expected[key] for key in ('sha256', 'bytes', 'nodeId', 'runId')):
                        raise ClientError('Registered evidence differs from this capture: ' + artifact['id'])
                    continue
                snapshot = Path(artifact['path'])
                if file_digest(snapshot) != (artifact['sha256'], artifact['bytes']):
                    raise ClientError('Staged evidence changed; original files will not be reread: ' + str(snapshot))
                retained = client.request(client.project_route(task['projectId']) + '/artifacts', artifact)
                if any(retained.get(key) != expected[key] for key in ('id', 'sha256', 'bytes', 'nodeId', 'runId')):
                    raise ClientError('Retained evidence differs from this capture: ' + artifact['id'])
        task['state'] = 'synced'
        save_task(path, task)
    except (ClientError, OSError, ValueError) as exc:
        task['state'] = 'ready'
        warnings.append(str(exc))
    return task_result(task, warnings)


def task_result(task, warnings=()):
    result = {'projectId': task['projectId'], 'nodeId': task['nodeId'], 'runId': task['runId'],
              'requestId': task['requestId'], 'status': task.get('status', 'pending'),
              'pending': task['state'] != 'synced', 'artifactIds': [a['id'] for a in task['artifacts']] if task['state'] == 'synced' else []}
    for field in ('exitCode', 'wallTimeMs', 'startedAt', 'finishedAt', 'capturedAt'):
        if field in task:
            result[field] = task[field]
    if task['intent']['command'] == 'execute' and task.get('captureAvailable', True):
        directory = Path(task['captureRoot']) / task['taskId']
        result['stdoutPath'] = str(directory / 'stdout.txt')
        result['stderrPath'] = str(directory / 'stderr.txt')
    combined = task['recordingWarnings'] + list(warnings)
    if combined:
        result['recordingWarnings'] = combined
    return result


def record(client, args):
    notes = args.notes
    notes_error = None
    if args.notes_file is not None:
        if args.notes_file == '-':
            notes = sys.stdin.read()
        else:
            try:
                with Path(args.notes_file).open('r', encoding='utf-8-sig', newline='') as stream:
                    notes = stream.read()
            except OSError as exc:
                notes_error = exc
    metrics, metrics_warning = {}, None
    if args.metrics_file:
        try:
            metrics = json.loads(Path(args.metrics_file).read_text(encoding='utf-8-sig'))
            if not isinstance(metrics, dict):
                metrics = {'result': metrics}
            json.dumps(metrics, allow_nan=False)
        except (OSError, ValueError) as exc:
            metrics = {}
            metrics_warning = f'Metrics could not be decoded; retaining the original file as evidence when available: {exc}'
    intent = {'command': 'record', **{key: getattr(args, key) for key in
              ('title', 'summary', 'conclusion', 'kind', 'node', 'after', 'relation', 'independent', 'parent', 'status', 'artifact')},
              'notes': notes, 'notesFile': args.notes_file,
              'metrics': metrics, 'hasMetrics': args.metrics_file is not None and metrics_warning is None,
              'metricsFile': args.metrics_file}
    path, task = task_identity(client, args, intent)
    # Missing/unreadable source text must not prevent a stable request from
    # returning or delivering its existing frozen analysis. New work still fails.
    if notes_error is not None and (not args.request_id or not path.is_file()):
        raise notes_error
    if not intent['hasMetrics']:
        task['runId'] = None
    with task_lock(path):
        existing = load_existing(path, task, frozen_notes=notes_error is not None)
        if existing:
            emit(sync_task(client, path, existing))
            return 0
        if notes_error is not None:
            raise notes_error
        directory = Path(task['captureRoot']) / task['taskId']
        ensure_directory(directory)
        at = stamp()
        task.update({'capturedAt': at, 'status': 'recorded'})
        if metrics_warning:
            task['recordingWarnings'].append(metrics_warning)
        node = {'id': task['nodeId'], 'title': args.title}
        if args.conclusion is not None:
            node['conclusion'] = args.conclusion
        if notes is not None:
            node['notes'] = notes
        if args.kind is not None:
            node['kind'] = args.kind
        for option, field in (('summary', 'summary'), ('parent', 'parentId'), ('status', 'status')):
            if getattr(args, option) is not None:
                node[field] = getattr(args, option)
        if not args.node:
            node.setdefault('status', 'active')
            node.setdefault('kind', 'finding')
            node['createdAt'] = at
        task['operations'] = [{'op': 'node.update' if args.node else 'node.add', 'data': node}]
        capture_relationship(client, args, path, task)
        if intent['hasMetrics']:
            task['operations'].append({'op': 'run.add', 'data': {'id': task['runId'], 'nodeId': task['nodeId'],
                'title': args.title, 'status': 'completed', 'startedAt': None, 'finishedAt': None, 'capturedAt': at,
                'metrics': metrics, 'origin': 'observed', 'configuration': {'capturedExternalResult': True}}})
        persist_task(path, task)
        artifacts = list(args.artifact)
        if metrics_warning and args.metrics_file not in artifacts:
            artifacts.append(args.metrics_file)
        for index, requested in enumerate(artifacts):
            stage_artifact(task, requested, Path(requested).name, directory / (str(index) + '-' + Path(requested).name))
        task['state'] = 'ready'
        persist_task(path, task)
        emit(sync_task(client, path, task))
    return 0


def file_signature(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def drain_outbox(client, outbox, project_id=None, stop_event=None, acknowledged=None):
    """Submit frozen tasks only. This function never starts a subprocess."""
    results = []
    candidates = []
    for path in Path(outbox).glob('*.json'):
        if stop_event is not None and stop_event.is_set():
            break
        try:
            signature = file_signature(path)
            if acknowledged is not None and acknowledged.get(str(path)) == signature:
                continue
            task = read_queue_task(path)
            if task['url'] != client.url or (project_id and task['projectId'] != project_id):
                continue
            if task['state'] == 'synced':
                if acknowledged is not None:
                    acknowledged[str(path)] = signature
                continue
            priority = 0 if task.get('kind') == 'project' else 1
            at = task.get('capturedAt') or task.get('startedAt') or task.get('preparedAt') or ''
            candidates.append(((priority, at, path.name), path))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            results.append({'task': path.name, 'pending': True, 'recordingWarnings': [str(exc)]})
    for _, path in sorted(candidates):
        if stop_event is not None and stop_event.is_set():
            break
        try:
            with task_lock(path):
                task = read_queue_task(path)
                if task['url'] != client.url or (project_id and task['projectId'] != project_id):
                    continue
                if task['state'] == 'synced':
                    continue
                result = sync_project(client, path, task) if task.get('kind') == 'project' else sync_task(client, path, task)
                results.append(result)
                if not result['pending'] and acknowledged is not None:
                    acknowledged[str(path)] = file_signature(path)
        except (ClientError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            results.append({'task': path.name, 'pending': True, 'recordingWarnings': [str(exc)]})
    return results


def sync(client, args):
    outbox = Path.cwd() / '.exp-observer-runs' / 'outbox'
    results = drain_outbox(client, outbox, args.project)
    pending = sum(bool(result['pending']) for result in results)
    emit({'records': results, 'pending': pending})
    return 1 if pending else 0


def status(client, args):
    """Read atomic local receipts only; never contact the server or advance work."""
    outbox = Path.cwd() / '.exp-observer-runs' / 'outbox'
    records, plans, warnings = [], [], []
    seen = set()
    for directory in ancestor_outboxes(outbox, client.queue_root):
        try:
            paths = sorted(directory.glob('*.json'))
        except OSError as exc:
            warnings.append(f'{directory}: {exc}')
            continue
        for path in paths:
            try:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                task = read_queue_task(path)
                if task['url'] != client.url or task['projectId'] != args.project:
                    continue
                if task.get('kind') == 'project':
                    plans.append({'state': task['state'], 'preparedAt': task.get('preparedAt')})
                else:
                    records.append({**task_result(task), 'state': task['state']})
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                warnings.append(f'{path}: {exc}')
    records.sort(key=lambda record: str(record.get('capturedAt') or record.get('finishedAt') or record.get('startedAt') or ''))
    pending_records = [record for record in records if record['pending']]
    has_records = bool(records or plans)
    pending = bool(pending_records or any(plan['state'] != 'synced' for plan in plans))
    result = {'projectId': args.project, 'source': 'local', 'checkedAt': stamp(),
              'scope': 'current_directory_and_ancestors', 'transportChecked': False,
              'deliveryState': 'partial' if warnings else ('pending' if pending else ('synced' if has_records else 'unknown')),
              'pending': True if pending else (None if warnings or not has_records else False),
              'recordCount': len(records), 'syncedCount': len(records) - len(pending_records),
              'pendingCount': len(pending_records),
              'incompleteCount': sum(record['state'] not in ('ready', 'synced') for record in records),
              'records': records[-20:], 'pendingRecords': pending_records[-20:], 'projectPlans': plans}
    if len(records) > 20:
        result['recordsTruncated'] = True
    if len(pending_records) > 20:
        result['pendingRecordsTruncated'] = True
    if warnings:
        result.update({'localReadWarnings': warnings[:20], 'warningCount': len(warnings)})
    emit(result)
    return 0


def run_command(command, stdout, stderr):
    started = time.monotonic()
    process, error, cancelled = None, None, False
    try:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, shell=False)
        exit_code = process.wait()
    except KeyboardInterrupt:
        cancelled = True
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        exit_code = 130
    except OSError as exc:
        error, exit_code = str(exc), 127
        if stderr:
            try:
                stderr.write((error + '\n').encode('utf-8'))
            except TypeError:
                stderr.write(error + '\n')
    # Python uses negative return codes for signals; expose the conventional shell code.
    exit_code = 128 - exit_code if exit_code < 0 else exit_code
    return {'exitCode': exit_code, 'wallTimeMs': round((time.monotonic() - started) * 1000, 3),
            'status': 'cancelled' if cancelled else ('completed' if exit_code == 0 else 'failed')}, error


def execute(client, args):
    command = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    if not command:
        raise ClientError('execute requires -- COMMAND [ARG ...].')
    intent = {'command': 'execute', 'argv': command, 'cwd': str(Path.cwd()), 'node': args.node,
              'title': args.title, 'artifact': args.artifact, 'after': args.after,
              'relation': args.relation, 'independent': args.independent}
    path, task = task_identity(client, args, intent)
    with ExitStack() as stack:
        durable = True
        # A lock/reuse conflict must never execute the same stable request twice.
        try:
            stack.enter_context(task_lock(path))
        except OSError as exc:
            durable = False
            task['recordingWarnings'].append('Local outbox unavailable: ' + str(exc))
        existing = load_existing(path, task)
        if existing:
            emit(sync_task(client, path, existing))
            return existing.get('exitCode', 1)
        directory = Path(task['captureRoot']) / task['taskId']
        stdout = stderr = None
        try:
            ensure_directory(directory)
            stdout = stack.enter_context((directory / 'stdout.txt').open('wb'))
            stderr = stack.enter_context((directory / 'stderr.txt').open('wb'))
        except OSError as exc:
            durable = False
            task['captureAvailable'] = False
            task['recordingWarnings'].append('Local capture unavailable: ' + str(exc))
            if stdout:
                stdout.close()
            stdout = stderr = None
        task.update({'state': 'running', 'startedAt': stamp()})
        if durable:
            try:
                persist_task(path, task)
            except OSError as exc:
                durable = False
                task['recordingWarnings'].append('Local outbox unavailable: ' + str(exc))
        # If recording storage fails, send command output to stderr and still run it once.
        outcome, error = run_command(command, stdout or sys.stderr, stderr or sys.stderr)
        if stdout:
            stdout.close()
        if stderr:
            stderr.close()
        task.update(outcome, finishedAt=stamp())
        task['operations'] = [{'op': 'run.add', 'data': {'id': task['runId'], 'nodeId': task['nodeId'],
            'title': args.title, 'status': task['status'], 'startedAt': task['startedAt'], 'finishedAt': task['finishedAt'],
            'metrics': {key: task[key] for key in ('exitCode', 'wallTimeMs')}, 'origin': 'observed',
            'configuration': {'command': command, 'cwd': str(Path.cwd()), 'artifactPaths': args.artifact},
            'events': [{'id': 'start-' + task['taskId'], 'type': 'started', 'message': 'Command started', 'at': task['startedAt']},
                       {'id': 'finish-' + task['taskId'], 'type': 'finished', 'message': error or f'Process exited with code {task["exitCode"]}',
                        'at': task['finishedAt'], 'exitCode': task['exitCode'], 'elapsedMs': task['wallTimeMs']}]}}]
        if args.node is None:
            node = {'id': task['nodeId'], 'title': args.title, 'createdAt': task['startedAt'],
                    'status': 'paused' if task['status'] == 'cancelled' else task['status']}
            if task['status'] == 'cancelled':
                node['pauseReason'] = 'Command interrupted'
            task['operations'].insert(0, {'op': 'node.add', 'data': node})
        capture_relationship(client, args, path, task)
        if durable:
            for filename, title in (('stdout.txt', 'Standard output'), ('stderr.txt', 'Standard error')):
                stage_artifact(task, directory / filename, title, directory / filename)
            for index, requested in enumerate(args.artifact):
                stage_artifact(task, requested, Path(requested).name, directory / (str(index) + '-' + Path(requested).name))
            task['state'] = 'ready'
            try:
                persist_task(path, task)
                result = sync_task(client, path, task)
            except OSError as exc:
                result = task_result(task, ['Could not persist command outcome: ' + str(exc)])
        else:
            result = task_result(task, ['No durable record is available for sync.'])
        emit(result)
        return task['exitCode']


def check(client, project_id):
    p = client.project(project_id)
    errors, warnings = [], []
    for artifact in p['artifacts']:
        if artifact.get('origin') == 'observed':
            try:
                metadata = client.request(client.project_route(project_id) + '/artifacts/' + quote(artifact['id'], safe='') + '/metadata')
                if not metadata.get('verified') or metadata.get('sha256') != artifact['sha256'] or metadata.get('bytes') != artifact['bytes']:
                    errors.append(f'Evidence mismatch: {artifact["id"]}')
            except ClientError as exc:
                errors.append(f'{artifact["id"]}: {exc}')
    for run in p['runs']:
        if run['status'] == 'running':
            warnings.append(f'Run still marked running: {run["id"]}')
        if run.get('origin') == 'observed' and run['status'] in ('completed', 'failed') and not run.get('artifactIds'):
            warnings.append(f'Run has no registered evidence: {run["id"]}')
    emit({'ok': not errors, 'projectId': project_id, 'revision': p['revision'], 'errors': errors, 'warnings': warnings,
          'counts': {key: len(p[key]) for key in ('nodes', 'runs', 'artifacts', 'assessments', 'decisions')}})
    return 1 if errors else 0


def main(argv=None):
    # JSON and evidence text use UTF-8 even when Windows pipes use a legacy code page.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8-sig' if stream is sys.stdin else 'utf-8',
                               errors='backslashreplace' if stream is sys.stderr else 'strict')
    args = parser().parse_args(argv)
    client = Client(args.url, timeout=2 if args.command in ('init', 'context', 'record', 'execute', 'sync') else 30)
    try:
        if args.command == 'projects':
            result = client.request('/api/projects')
        elif args.command == 'init':
            return init(client, args)
        elif args.command == 'context':
            return context(client, args)
        elif args.command == 'observe':
            if args.observation_action == 'start':
                observation_id = 'observation-' + (hashlib.sha256(args.request_id.encode()).hexdigest()[:24] if args.request_id else uuid4().hex[:16])
                data = {'id': observation_id, 'nodeId': args.node, 'title': args.title}
            else:
                observation_id = args.id
                data = {'id': observation_id}
                for option, field in (('input_tokens', 'inputTokens'), ('output_tokens', 'outputTokens'), ('usage_source', 'usageSource'), ('usage_ref', 'usageRef')):
                    value = getattr(args, option)
                    if value is not None:
                        data[field] = value
            project = client.apply(args.project, [{'op': 'observation.' + args.observation_action, 'data': data}], request_id=args.request_id)
            observation = next(o for o in project['observations'] if o['id'] == observation_id)
            result = {'projectId': project['id'], 'observationId': observation_id, 'revision': project['revision'],
                      **{field: observation.get(field) for field in ('nodeId', 'status', 'startedAt', 'finishedAt', 'durationMs', 'inputTokens', 'outputTokens', 'usageSource', 'usageRef')}}
        elif args.command == 'apply':
            content = Path(args.file).read_text(encoding='utf-8-sig') if args.file else sys.stdin.read()
            value = json.loads(content)
            body = {'operations': value} if isinstance(value, list) else value
            if not isinstance(body, dict):
                raise ClientError('apply requires an operations array or batch object.')
            if args.expected_revision is not None:
                body['expectedRevision'] = args.expected_revision
            if args.request_id:
                body['requestId'] = args.request_id
            body.setdefault('requestId', 'req-' + uuid4().hex)
            result = client.request(client.project_route(args.project) + '/batch', body)
            # Incremental writes return a small acknowledgement; export is available for the complete graph.
            result = {'projectId': result['id'], 'revision': result['revision'], 'requestId': body['requestId'],
                      'counts': {key: len(result[key]) for key in ('nodes', 'edges', 'runs', 'artifacts', 'assessments', 'decisions')}}
        elif args.command == 'artifact':
            artifacts = [client.request(client.project_route(args.project) + '/artifacts', {'path': str(Path(path).expanduser().resolve()), 'title': args.title,
                                                                                           'nodeId': args.node, 'runId': args.run}) for path in args.path]
            result = artifacts[0] if len(artifacts) == 1 else {'artifacts': artifacts}
        elif args.command == 'export':
            result = client.project(args.project)
            if args.output:
                output = Path(args.output).expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                result = {'projectId': args.project, 'output': str(output), 'revision': result['revision']}
        elif args.command == 'read':
            if args.offset < 0 or not 1 <= args.limit <= 1048576:
                raise ClientError('Read offset must be nonnegative and limit must be 1–1048576 bytes.')
            route = client.project_route(args.project) + '/artifacts/' + quote(args.artifact, safe='') + '/content?'
            content = client.request(route + urlencode({'offset': args.offset, 'limit': args.limit}), raw=True)
            if args.output:
                output = Path(args.output).expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(content)
                result = {'projectId': args.project, 'artifactId': args.artifact, 'output': str(output),
                          'offset': args.offset, 'bytes': len(content)}
            else:
                sys.stdout.write(content.decode('utf-8', errors='replace'))
                return 0
        elif args.command == 'check':
            return check(client, args.project)
        elif args.command == 'execute':
            return execute(client, args)
        elif args.command == 'record':
            return record(client, args)
        elif args.command == 'sync':
            return sync(client, args)
        elif args.command == 'status':
            return status(client, args)
        emit(result)
        return 0
    except (ClientError, ValueError, OSError) as exc:
        emit({'error': str(exc)}, sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
