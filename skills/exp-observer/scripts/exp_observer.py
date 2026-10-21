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
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


class ClientError(Exception):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def emit(value, stream=sys.stdout):
    print(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False), file=stream)


class Client:
    def __init__(self, url, timeout=30):
        self.url = url.rstrip('/')
        self.timeout = timeout

    def request(self, route, body=None, raw=False):
        data = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        request = Request(self.url + route, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content = response.read()
                return content if raw else json.loads(content)
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read())
                raise ClientError(f'{detail.get("code", exc.code)}: {detail.get("error", exc.reason)}') from exc
            except (ValueError, UnicodeError):
                raise ClientError(f'HTTP {exc.code}: {exc.reason}') from exc
            finally:
                exc.close()
        except (URLError, TimeoutError, OSError) as exc:
            raise ClientError(f'Cannot reach ExpObserver at {self.url}: {exc.reason if isinstance(exc, URLError) else exc}') from exc

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
    record.add_argument('--node', help='Update this node; omit to create a node')
    record.add_argument('--after', help='Previous node connected by a leads_to relation')
    record.add_argument('--parent')
    record.add_argument('--status', default=None, help='Node status (default for new nodes: active)')
    record.add_argument('--metrics-file', help='UTF-8 JSON; nested objects are preserved and other root values use a result key')
    record.add_argument('--artifact', action='append', default=[])
    record.add_argument('--request-id', help='Stable identifier for retries of this record')
    sync = commands.add_parser('sync', help='Retry local pending records without executing experiments')
    sync.add_argument('--project', help='Only sync this project')
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
            cmd.add_argument('--node', required=command == 'execute')
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
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def task_lock(path):
    """An OS lock is released on process death, including on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
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
                raise ClientError('This local record is already being processed.') from exc
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ClientError('This local record is already being processed.') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def task_identity(client, args, intent):
    request_id = getattr(args, 'request_id', None) or 'capture-' + uuid4().hex
    key = hashlib.sha256(json.dumps([client.url, args.project, request_id], ensure_ascii=False).encode('utf-8')).hexdigest()[:32]
    path = Path.cwd() / '.exp-observer-runs' / 'outbox' / (key + '.json')
    task = {'version': 1, 'taskId': key, 'requestId': request_id, 'url': client.url,
            'projectId': args.project, 'intent': intent, 'state': 'preparing',
            'nodeId': args.node or 'node-' + key, 'runId': 'run-' + key,
            'captureRoot': str(capture_root(args.project)), 'artifacts': [], 'recordingWarnings': []}
    return path, task


def load_existing(path, task):
    if not path.exists():
        return None
    existing = json.loads(path.read_text(encoding='utf-8'))
    if existing.get('intent') != task['intent']:
        raise ClientError('request-id was already used for different work; use a new request-id.')
    return existing


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
    if task['state'] == 'synced':
        return task_result(task)
    if task['state'] != 'ready':
        return task_result(task, ['Capture was interrupted before its outcome was saved; sync never reruns commands.'])
    warnings = []
    try:
        # All operations (including timestamps) are frozen before the first send.
        client.apply(task['projectId'], task['operations'], request_id='capture-' + task['taskId'])
        if task['artifacts']:
            merge_source_root(client, task)
            project = client.project(task['projectId'])
            registered = {a['id']: a for a in project['artifacts']}
            for artifact in task['artifacts']:
                existing = registered.get(artifact['id'])
                if existing:
                    if any(existing.get(key) != artifact[key] for key in ('sha256', 'bytes', 'nodeId', 'runId')):
                        raise ClientError('Registered evidence differs from this capture: ' + artifact['id'])
                    continue
                snapshot = Path(artifact['path'])
                if file_digest(snapshot) != (artifact['sha256'], artifact['bytes']):
                    raise ClientError('Staged evidence changed; original files will not be reread: ' + str(snapshot))
                retained = client.request(client.project_route(task['projectId']) + '/artifacts', artifact)
                if any(retained.get(key) != artifact[key] for key in ('id', 'sha256', 'bytes', 'nodeId', 'runId')):
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
              ('title', 'summary', 'node', 'after', 'parent', 'status', 'artifact')},
              'metrics': metrics, 'hasMetrics': args.metrics_file is not None and metrics_warning is None,
              'metricsFile': args.metrics_file}
    path, task = task_identity(client, args, intent)
    if not intent['hasMetrics']:
        task['runId'] = None
    with task_lock(path):
        existing = load_existing(path, task)
        if existing:
            emit(sync_task(client, path, existing))
            return 0
        directory = Path(task['captureRoot']) / task['taskId']
        directory.mkdir(parents=True, exist_ok=True)
        at = stamp()
        task.update({'capturedAt': at, 'status': 'recorded'})
        if metrics_warning:
            task['recordingWarnings'].append(metrics_warning)
        node = {'id': task['nodeId'], 'title': args.title}
        for option, field in (('summary', 'summary'), ('parent', 'parentId'), ('status', 'status')):
            if getattr(args, option) is not None:
                node[field] = getattr(args, option)
        if not args.node:
            node.setdefault('status', 'active')
            node['createdAt'] = at
        task['operations'] = [{'op': 'node.update' if args.node else 'node.add', 'data': node}]
        if args.after:
            task['operations'].append({'op': 'edge.add', 'data': {'id': 'edge-' + task['taskId'],
                'source': args.after, 'target': task['nodeId'], 'relation': 'leads_to', 'basis': 'observed'}})
        if intent['hasMetrics']:
            task['operations'].append({'op': 'run.add', 'data': {'id': task['runId'], 'nodeId': task['nodeId'],
                'title': args.title, 'status': 'completed', 'startedAt': None, 'finishedAt': None, 'capturedAt': at,
                'metrics': metrics, 'origin': 'observed', 'configuration': {'capturedExternalResult': True}}})
        save_task(path, task)
        artifacts = list(args.artifact)
        if metrics_warning and args.metrics_file not in artifacts:
            artifacts.append(args.metrics_file)
        for index, requested in enumerate(artifacts):
            stage_artifact(task, requested, Path(requested).name, directory / (str(index) + '-' + Path(requested).name))
        task['state'] = 'ready'
        save_task(path, task)
        emit(sync_task(client, path, task))
    return 0


def sync(client, args):
    results = []
    outbox = Path.cwd() / '.exp-observer-runs' / 'outbox'
    for path in sorted(outbox.glob('*.json')):
        try:
            with task_lock(path):
                task = json.loads(path.read_text(encoding='utf-8'))
                if task['url'] != client.url or (args.project and task['projectId'] != args.project):
                    continue
                if task['state'] == 'synced':
                    continue
                results.append(sync_task(client, path, task))
        except (ClientError, OSError, ValueError, KeyError) as exc:
            results.append({'task': path.name, 'pending': True, 'recordingWarnings': [str(exc)]})
    pending = sum(bool(result['pending']) for result in results)
    emit({'records': results, 'pending': pending})
    return 1 if pending else 0


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
              'title': args.title, 'artifact': args.artifact}
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
            directory.mkdir(parents=True, exist_ok=True)
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
                save_task(path, task)
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
        task['operations'] = [{'op': 'run.add', 'data': {'id': task['runId'], 'nodeId': args.node,
            'title': args.title, 'status': task['status'], 'startedAt': task['startedAt'], 'finishedAt': task['finishedAt'],
            'metrics': {key: task[key] for key in ('exitCode', 'wallTimeMs')}, 'origin': 'observed',
            'configuration': {'command': command, 'cwd': str(Path.cwd()), 'artifactPaths': args.artifact},
            'events': [{'id': 'start-' + task['taskId'], 'type': 'started', 'message': 'Command started', 'at': task['startedAt']},
                       {'id': 'finish-' + task['taskId'], 'type': 'finished', 'message': error or f'Process exited with code {task["exitCode"]}',
                        'at': task['finishedAt'], 'exitCode': task['exitCode'], 'elapsedMs': task['wallTimeMs']}]}}]
        if durable:
            for filename, title in (('stdout.txt', 'Standard output'), ('stderr.txt', 'Standard error')):
                stage_artifact(task, directory / filename, title, directory / filename)
            for index, requested in enumerate(args.artifact):
                stage_artifact(task, requested, Path(requested).name, directory / (str(index) + '-' + Path(requested).name))
            task['state'] = 'ready'
            try:
                save_task(path, task)
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
    client = Client(args.url, timeout=2 if args.command in ('record', 'execute', 'sync') else 30)
    try:
        if args.command == 'projects':
            result = client.request('/api/projects')
        elif args.command == 'init':
            body = {'name': args.name, 'description': args.description,
                    'sourceRoots': [str(Path(root).expanduser().resolve()) for root in args.source_root]}
            if args.id:
                body['id'] = args.id
            result = client.request('/api/projects', body)
        elif args.command == 'context':
            route = client.project_route(args.project) + '/context'
            if args.node:
                route += '?' + urlencode({'node': args.node})
            result = client.request(route)
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
        emit(result)
        return 0
    except (ClientError, ValueError, OSError) as exc:
        emit({'error': str(exc)}, sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
