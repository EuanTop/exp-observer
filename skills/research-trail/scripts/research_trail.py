#!/usr/bin/env python3
"""Standalone Research Trail client: explicit experiment IDs, incremental writes, no model dependency."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
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
    def __init__(self, url):
        self.url = url.rstrip('/')

    def request(self, route, body=None, raw=False):
        data = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        request = Request(self.url + route, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=30) as response:
                content = response.read()
                return content if raw else json.loads(content)
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read())
                raise ClientError(f'{detail.get("code", exc.code)}: {detail.get("error", exc.reason)}') from exc
            except (ValueError, UnicodeError):
                raise ClientError(f'HTTP {exc.code}: {exc.reason}') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ClientError(f'Cannot reach Research Trail at {self.url}: {exc.reason if isinstance(exc, URLError) else exc}') from exc

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
    root = argparse.ArgumentParser(description='Maintain independent Research Trail experiment records.')
    root.add_argument('--url', default=os.environ.get('RESEARCH_TRAIL_URL') or os.environ.get('GTRACK_URL', 'http://127.0.0.1:4317'))
    commands = root.add_subparsers(dest='command', required=True)
    commands.add_parser('projects', help='List experiments')
    init = commands.add_parser('init', help='Create an experiment')
    init.add_argument('--name', required=True)
    init.add_argument('--id')
    init.add_argument('--description', default='')
    init.add_argument('--source-root', action='append', default=[])
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
            cmd.add_argument('--artifact', action='append', default=[], help='Capture a result file after execution; repeat for multiple files')
            cmd.add_argument('argv', nargs=argparse.REMAINDER)
    return root


def execute(client, args):
    command = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    if not command:
        raise ClientError('execute requires -- COMMAND [ARG ...].')
    project = client.project(args.project)
    if not any(n['id'] == args.node for n in project['nodes']):
        raise ClientError('Selected node does not exist.')
    run_id = 'run-' + uuid4().hex[:16]
    capture_root = (Path.cwd() / '.gtrack-runs' / project['id']).resolve()
    capture_dir = capture_root / run_id
    capture_dir.mkdir(parents=True, exist_ok=False)
    roots = project.get('sourceRoots', [])
    if str(capture_root) not in roots:
        project = client.apply(args.project, [{'op': 'project.update', 'data': {'sourceRoots': roots + [str(capture_root)]}}], project['revision'])
    run = {'id': run_id, 'nodeId': args.node, 'title': args.title, 'status': 'running',
           'configuration': {'command': command, 'cwd': str(Path.cwd()), 'artifactPaths': args.artifact}, 'startedAt': stamp(),
           'origin': 'observed', 'events': [{'id': 'start-' + run_id, 'type': 'started', 'message': 'Command started', 'at': stamp()}]}
    client.apply(args.project, [{'op': 'run.add', 'data': run}], project['revision'], 'start-' + run_id)
    started = time.monotonic()
    exit_code, error, cancelled, process = None, None, False, None
    stdout_path, stderr_path = capture_dir / 'stdout.txt', capture_dir / 'stderr.txt'
    with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
        try:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, shell=False)
            exit_code = process.wait()
        except KeyboardInterrupt:
            cancelled = True
            if process:
                process.terminate()
                try:
                    exit_code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    exit_code = process.wait()
        except OSError as exc:
            error = str(exc)
            stderr.write((error + '\n').encode())
            exit_code = 127
    elapsed = round((time.monotonic() - started) * 1000, 3)
    status = 'cancelled' if cancelled else ('completed' if exit_code == 0 else 'failed')
    # End state is persisted before evidence copying, so a registration error never leaves a finished process marked running.
    client.apply(args.project, [
        {'op': 'run.update', 'data': {'id': run_id, 'status': status, 'finishedAt': stamp(), 'metrics': {'wallTimeMs': elapsed, 'exitCode': exit_code}}},
        {'op': 'run.event', 'data': {'runId': run_id, 'event': {'type': 'finished', 'message': error or f'Process exited with code {exit_code}', 'exitCode': exit_code, 'elapsedMs': elapsed}}},
    ], request_id='finish-' + run_id)
    evidence = []
    for path, title in ((stdout_path, 'Standard output'), (stderr_path, 'Standard error')):
        evidence.append(client.request(client.project_route(args.project) + '/artifacts', {'path': str(path), 'title': title, 'nodeId': args.node, 'runId': run_id}))
    evidence_errors = []
    for index, requested in enumerate(args.artifact):
        source = Path(requested).expanduser().resolve()
        try:
            if not source.is_file():
                raise OSError('Result file does not exist or is not a regular file')
            # Stage only the requested bytes under the already scoped capture root.
            # Never grant the server access to the result file's entire parent directory.
            result_dir = capture_dir / 'results'
            result_dir.mkdir(exist_ok=True)
            staged = result_dir / f'{index + 1}-{source.name}'
            shutil.copyfile(source, staged)
            evidence.append(client.request(client.project_route(args.project) + '/artifacts', {'path': str(staged), 'title': source.name, 'nodeId': args.node, 'runId': run_id}))
        except (OSError, ClientError) as exc:
            evidence_errors.append({'path': str(source), 'error': str(exc)})
    result = {'projectId': args.project, 'runId': run_id, 'status': status, 'exitCode': exit_code,
              'wallTimeMs': elapsed, 'artifactIds': [a['id'] for a in evidence]}
    if evidence_errors:
        result['evidenceErrors'] = evidence_errors
        client.apply(args.project, [{'op': 'run.event', 'data': {'runId': run_id, 'event': {
            'type': 'evidence_error', 'message': 'One or more requested result files could not be captured', 'errors': evidence_errors}}}])
    emit(result)
    if evidence_errors and exit_code == 0:
        return 1
    return 130 if cancelled else (0 if exit_code == 0 else min(max(exit_code or 1, 1), 125))


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
    args = parser().parse_args(argv)
    client = Client(args.url)
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
            content = Path(args.file).read_text(encoding='utf-8') if args.file else sys.stdin.read()
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
        emit(result)
        return 0
    except (ClientError, ValueError, OSError) as exc:
        emit({'error': str(exc)}, sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
