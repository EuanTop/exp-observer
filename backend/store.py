"""Atomic, process-safe JSON records. No conversation state is stored."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4


class StoreError(Exception):
    def __init__(self, message, code='invalid_request', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def uid(prefix):
    return f'{prefix}-{uuid4().hex[:12]}'


def canonical(data):
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StoreError('Record must contain finite JSON values.') from exc


def object_value(value, name):
    if not isinstance(value, dict):
        raise StoreError(f'{name} must be an object.')
    return value


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise StoreError('IDs must use 1–128 letters, numbers, dots, underscores or hyphens.', 'invalid_id')
    return value


def identity(path):
    if not hasattr(path, 'read'):
        with open(path, 'rb') as source:
            return identity(source)
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: path.read(1024 * 1024), b''):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


class Store:
    def __init__(self, data_dir):
        self.root = Path(data_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lock(self):
        with open(self.root / '.lock', 'a+b') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _dir(self, project_id):
        return self.root / valid_id(project_id)

    def _load(self, project_id):
        path = self._dir(project_id) / 'state.json'
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise StoreError('Experiment not found.', 'not_found', 404)
        except (OSError, ValueError) as exc:
            raise StoreError('Experiment file could not be read.', 'storage_error', 500) from exc

    def _save(self, bundle):
        folder = self._dir(bundle['project']['id'])
        folder.mkdir(parents=True, exist_ok=True)
        encoded = (canonical(bundle) + '\n').encode('utf-8')
        handle, temporary = tempfile.mkstemp(prefix='.state-', dir=folder)
        try:
            with os.fdopen(handle, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, folder / 'state.json')
            directory_fd = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _operation_metadata(self, operations):
        result = []
        for operation in operations:
            data = operation.get('data', {})
            item = {'op': operation['op']}
            record_id = data.get('id') or data.get('runId')
            if record_id:
                item['recordId'] = record_id
            if operation['op'] == 'project.restore':
                item['restoredRevision'] = data['revision']
            result.append(item)
        return result

    def _record(self, bundle, project, operations, request_id=None, fingerprint=None):
        project['revision'] = bundle['project']['revision'] + 1
        project['updatedAt'] = now()
        metadata = self._operation_metadata(operations)
        project['activity'] = copy.deepcopy(bundle['project'].get('activity', [])) + [
            {'id': uid('activity'), 'at': project['updatedAt'], 'revision': project['revision'], 'operations': metadata}]
        bundle['project'] = project
        entry = {'revision': project['revision'], 'at': project['updatedAt'],
                 'operations': metadata, 'snapshot': copy.deepcopy(project)}
        if request_id:
            entry.update({'requestId': request_id, 'fingerprint': fingerprint})
        bundle['history'].append(entry)
        return project

    def _new_bundle(self, project, operation):
        return {'project': project, 'history': [{'revision': project['revision'], 'at': project['updatedAt'],
                'operations': [operation], 'snapshot': copy.deepcopy(project)}], 'requests': {}}

    def list_projects(self):
        with self._lock():
            result = []
            for path in sorted(self.root.glob('*/state.json')):
                p = self._load(path.parent.name)['project']
                result.append({k: p.get(k, '') for k in ('id', 'name', 'description', 'revision', 'updatedAt')}
                              | {'nodeCount': len(p['nodes'])})
            return sorted(result, key=lambda p: p['updatedAt'], reverse=True)

    def get_project(self, project_id):
        with self._lock():
            return copy.deepcopy(self._load(project_id)['project'])

    def create_project(self, data):
        object_value(data, 'Project')
        project_id = valid_id(data.get('id') or uid('study'))
        if not isinstance(data.get('name'), str) or not data['name'].strip():
            raise StoreError('Experiment name is required.')
        with self._lock():
            if (self._dir(project_id) / 'state.json').exists():
                raise StoreError('Experiment ID already exists.', 'conflict', 409)
            stamp = now()
            p = {'id': project_id, 'name': data['name'].strip(), 'description': data.get('description', ''),
                 'revision': 1, 'createdAt': stamp, 'updatedAt': stamp, 'sourceRoots': [],
                 **{key: [] for key in ('nodes', 'edges', 'runs', 'artifacts', 'assessments', 'decisions', 'observations', 'activity')}}
            if 'sourceRoots' in data:
                p['sourceRoots'] = data['sourceRoots']
            self._validate(p)
            self._save(self._new_bundle(p, {'op': 'project.create'}))
            return copy.deepcopy(p)

    def import_project(self, project):
        p = copy.deepcopy(object_value(project, 'Project'))
        self._validate(p)
        with self._lock():
            base = p['id']
            while (self._dir(p['id']) / 'state.json').exists():
                p['id'] = f'{base[:100]}-{uuid4().hex[:8]}'
            p['revision'] = 1
            p.setdefault('createdAt', now())
            p['updatedAt'] = now()
            p.setdefault('activity', [])
            self._save(self._new_bundle(p, {'op': 'project.import'}))
            return copy.deepcopy(p)

    def _expected(self, p, body):
        if 'expectedRevision' in body and (type(body['expectedRevision']) is not int or body['expectedRevision'] < 1):
            raise StoreError('expectedRevision must be a positive integer.')
        if 'expectedRevision' in body and body['expectedRevision'] != p['revision']:
            raise StoreError(f'Experiment changed: expected revision {body["expectedRevision"]}, current {p["revision"]}. Read it again and reapply your changes.', 'revision_conflict', 409)

    def batch(self, project_id, body):
        object_value(body, 'Batch')
        operations = body.get('operations')
        if not isinstance(operations, list) or not operations:
            raise StoreError('operations must be a nonempty array.')
        request_id = body.get('requestId')
        if request_id is not None:
            valid_id(request_id)
        encoded_operations = canonical(operations)
        fingerprint = hashlib.sha256(encoded_operations.encode('utf-8')).hexdigest()
        with self._lock():
            bundle = self._load(project_id)
            previous = bundle['requests'].get(request_id) if request_id else None
            if request_id and previous is None:
                previous = next((h for h in bundle['history'] if h.get('requestId') == request_id), None)
            if previous is not None:
                if previous['fingerprint'] not in (fingerprint, encoded_operations):
                    raise StoreError('requestId was already used for different operations.', 'idempotency_conflict', 409)
                if 'result' in previous:
                    return copy.deepcopy(previous['result'])
                return copy.deepcopy(next(h['snapshot'] for h in bundle['history'] if h['revision'] == previous['revision']))
            self._expected(bundle['project'], body)
            p = copy.deepcopy(bundle['project'])
            for operation in operations:
                object_value(operation, 'Operation')
                self._apply(p, operation.get('op'), copy.deepcopy(object_value(operation.get('data', {}), 'Operation data')))
            self._validate(p)
            self._record(bundle, p, operations, request_id, fingerprint)
            if request_id:
                bundle['requests'][request_id] = {'fingerprint': fingerprint, 'revision': p['revision']}
                if len(bundle['requests']) > 256:
                    recent = sorted(bundle['requests'].items(), key=lambda item: item[1].get('revision', 0), reverse=True)[:256]
                    bundle['requests'] = dict(recent)
            self._save(bundle)
            return copy.deepcopy(p)

    def _find(self, p, collection, key):
        for item in p.get(collection, []):
            if item['id'] == key:
                return item
        raise StoreError(f'{collection.rstrip("s").capitalize()} not found: {key}', 'not_found', 404)

    def _apply(self, p, op, d):
        stamp = now()
        if op == 'project.update':
            for key, value in d.items():
                if key not in {'id', 'revision', 'createdAt', 'updatedAt', 'nodes', 'edges', 'runs', 'artifacts', 'assessments', 'decisions', 'observations', 'activity'}:
                    p[key] = value
            return
        if op == 'node.delete':
            self._find(p, 'nodes', d.get('id'))
            remove = {d['id']}
            while True:
                more = {n['id'] for n in p['nodes'] if n.get('parentId') in remove}
                if more <= remove:
                    break
                remove.update(more)
            p['nodes'] = [n for n in p['nodes'] if n['id'] not in remove]
            p['edges'] = [e for e in p['edges'] if e['source'] not in remove and e['target'] not in remove]
            run_ids = {r['id'] for r in p['runs'] if r.get('nodeId') in remove}
            artifact_ids = {a['id'] for a in p['artifacts'] if a.get('nodeId') in remove or a.get('runId') in run_ids}
            p['runs'] = [r for r in p['runs'] if r['id'] not in run_ids]
            p['artifacts'] = [a for a in p['artifacts'] if a['id'] not in artifact_ids]
            p['assessments'] = [a for a in p['assessments'] if a['runId'] not in run_ids]
            p['decisions'] = [a for a in p['decisions'] if a.get('nodeId') not in remove]
            if 'observations' in p:
                p['observations'] = [o for o in p['observations'] if o.get('nodeId') not in remove]
            for item in p['runs'] + p['assessments'] + p['decisions']:
                if 'artifactIds' in item:
                    item['artifactIds'] = [key for key in item['artifactIds'] if key not in artifact_ids]
                if 'runIds' in item:
                    item['runIds'] = [key for key in item['runIds'] if key not in run_ids]
            return
        if op == 'run.event':
            run = self._find(p, 'runs', d.get('runId'))
            event = object_value(d.get('event'), 'Event')
            event.setdefault('id', uid('event'))
            event.setdefault('at', stamp)
            if any(e['id'] == event['id'] for e in run['events']):
                raise StoreError('Event ID already exists.', 'conflict', 409)
            run['events'].append(event)
            return
        if op == 'observation.start':
            observation_id = valid_id(d.get('id') or uid('observation'))
            observations = p.setdefault('observations', [])
            if any(o['id'] == observation_id for o in observations):
                raise StoreError('Observation ID already exists.', 'conflict', 409)
            observations.append({'id': observation_id, 'nodeId': d.get('nodeId'), 'title': d.get('title', ''),
                                 'status': 'running', 'startedAt': stamp, 'finishedAt': None, 'durationMs': None,
                                 'inputTokens': None, 'outputTokens': None, 'usageSource': '', 'usageRef': '', 'origin': 'observed'})
            return
        if op == 'observation.finish':
            observation = self._find(p, 'observations', d.get('id'))
            if observation['status'] != 'running':
                raise StoreError('Observation has already finished.', 'observation_finished', 409)
            for field in ('inputTokens', 'outputTokens'):
                if field in d:
                    if type(d[field]) is not int or d[field] < 0:
                        raise StoreError('Token counters must be nonnegative integers.', 'invalid_token_counter')
                    observation[field] = d[field]
            for field in ('usageSource', 'usageRef'):
                if field in d:
                    observation[field] = d[field]
            elapsed = (self._observation_time(stamp) - self._observation_time(observation['startedAt'])).total_seconds() * 1000
            if elapsed < 0:
                raise StoreError('System clock is earlier than the observation start; finish cannot record a negative interval.', 'invalid_observation_duration', 409)
            observation.update({'status': 'finished', 'finishedAt': stamp, 'durationMs': round(elapsed, 3)})
            return
        collection_map = {'node': 'nodes', 'edge': 'edges', 'run': 'runs', 'assessment': 'assessments',
                          'decision': 'decisions', 'artifact': 'artifacts'}
        if not isinstance(op, str) or '.' not in op:
            raise StoreError('Unknown operation.')
        kind, action = op.split('.', 1)
        collection = collection_map.get(kind)
        allowed = {'node': {'add', 'update'}, 'edge': {'add', 'update', 'delete'}, 'run': {'add', 'update'},
                   'assessment': {'add'}, 'decision': {'add'}, 'artifact': {'add'}}
        if collection is None or action not in allowed[kind]:
            raise StoreError(f'Unknown operation: {op}')
        if action == 'delete':
            self._find(p, collection, d.get('id'))
            p[collection] = [item for item in p[collection] if item['id'] != d['id']]
            return
        if action == 'update':
            existing = self._find(p, collection, d.get('id'))
            existing.update(d)
            if kind == 'node':
                existing['updatedAt'] = stamp
            return
        d.setdefault('id', uid(kind))
        valid_id(d['id'])
        if any(item['id'] == d['id'] for item in p[collection]):
            raise StoreError(f'{kind} ID already exists.', 'conflict', 409)
        defaults = {
            'node': {'title': 'Untitled', 'kind': 'experiment', 'status': 'proposed', 'parentId': None,
                     'summary': '', 'notes': '', 'nextAction': '', 'tags': [], 'position': {'x': 0, 'y': 0},
                     'importance': 'normal', 'importanceReason': '', 'pauseReason': '', 'resumeWhen': '',
                     'collapsed': False, 'createdAt': stamp, 'updatedAt': stamp},
            'edge': {'relation': 'leads_to', 'label': '', 'basis': 'unknown'},
            'run': {'title': 'Run', 'status': 'running', 'configuration': {}, 'metrics': {}, 'startedAt': stamp,
                    'finishedAt': None, 'events': [], 'artifactIds': [], 'origin': 'observed'},
            'assessment': {'metrics': {}, 'conclusion': '', 'limitations': '', 'artifactIds': [], 'supersedes': None, 'createdAt': stamp},
            'decision': {'title': 'Decision', 'conclusion': '', 'scope': '', 'nextAction': '', 'runIds': [], 'artifactIds': [], 'createdAt': stamp},
            'artifact': {'nodeId': None, 'runId': None, 'title': 'Evidence', 'path': '', 'sha256': '', 'bytes': 0,
                         'mime': 'text/plain', 'createdAt': stamp, 'origin': 'mock'},
        }
        if kind == 'artifact' and d.get('origin', 'mock') != 'mock':
            raise StoreError('Observed evidence must be registered from a real file.', 'registration_required')
        p[collection].append(defaults[kind] | d)

    def _validate(self, p):
        object_value(p, 'Project')
        canonical(p)
        valid_id(p.get('id'))
        if not isinstance(p.get('name'), str) or not p['name'].strip():
            raise StoreError('Experiment name is required.')
        if not isinstance(p.get('description', ''), str) or not isinstance(p.get('activity', []), list):
            raise StoreError('Project description must be text and activity must be an array.')
        roots = p.get('sourceRoots', [])
        if not isinstance(roots, list) or any(not isinstance(r, str) or not Path(r).is_absolute() for r in roots):
            raise StoreError('sourceRoots must contain absolute directory paths.')
        groups = {}
        for collection in ('nodes', 'edges', 'runs', 'artifacts', 'assessments', 'decisions', 'observations'):
            items = p.get(collection, [] if collection == 'observations' else None)
            if not isinstance(items, list):
                raise StoreError(f'{collection} must be an array.')
            group = {}
            for item in items:
                object_value(item, collection)
                key = valid_id(item.get('id'))
                if key in group:
                    raise StoreError(f'Duplicate {collection} ID: {key}')
                group[key] = item
            groups[collection] = group
        def ref(value, collection, optional=False):
            if optional and value is None:
                return
            if not isinstance(value, str) or value not in groups[collection]:
                raise StoreError(f'Unknown {collection} reference: {value}', 'invalid_reference')
        def refs(values, collection):
            if not isinstance(values, list):
                raise StoreError(f'{collection} references must be an array.')
            for value in values:
                ref(value, collection)
        for node in p['nodes']:
            ref(node.get('parentId'), 'nodes', True)
        for node in p['nodes']:
            for field in ('title', 'kind', 'status', 'summary', 'notes', 'nextAction', 'importanceReason', 'pauseReason', 'resumeWhen'):
                if not isinstance(node.get(field, ''), str):
                    raise StoreError(f'Node {field} must be text.')
            if node.get('importance', 'normal') not in ('normal', 'critical'):
                raise StoreError('Node importance must be normal or critical.')
            if not isinstance(node.get('tags', []), list) or any(not isinstance(tag, str) for tag in node.get('tags', [])):
                raise StoreError('Node tags must be an array of text values.')
            if type(node.get('collapsed', False)) is not bool:
                raise StoreError('Node collapsed must be a boolean.')
            seen, current = {node['id']}, node.get('parentId')
            while current is not None:
                if current in seen:
                    raise StoreError('Node containment cannot contain a cycle.', 'containment_cycle')
                seen.add(current)
                current = groups['nodes'][current].get('parentId')
            pos = node.get('position', {})
            if not isinstance(pos, dict) or any(type(pos.get(axis)) not in (int, float) or not math.isfinite(pos[axis]) for axis in ('x', 'y')):
                raise StoreError('Node position requires finite x and y coordinates.')
        for edge in p['edges']:
            ref(edge.get('source'), 'nodes')
            ref(edge.get('target'), 'nodes')
            if edge['source'] == edge['target']:
                raise StoreError('A node cannot connect to itself.', 'self_edge')
            if edge.get('basis', 'unknown') not in ('observed', 'hypothesis', 'unknown'):
                raise StoreError('Unknown edge basis.')
        for run in p['runs']:
            ref(run.get('nodeId'), 'nodes')
            if not isinstance(run.get('title', ''), str) or not isinstance(run.get('status'), str):
                raise StoreError('Run title and status must be text.')
            self._metrics(run.get('metrics', {}))
            object_value(run.get('configuration', {}), 'Run configuration')
            refs(run.get('artifactIds', []), 'artifacts')
            if run.get('origin') not in ('mock', 'observed'):
                raise StoreError('Run origin must be mock or observed.')
            events = run.get('events', [])
            if not isinstance(events, list):
                raise StoreError('Run events must be an array.')
            event_ids = set()
            for event in events:
                object_value(event, 'Event')
                valid_id(event.get('id'))
                if event['id'] in event_ids:
                    raise StoreError('Duplicate event ID.')
                event_ids.add(event['id'])
        for artifact in p['artifacts']:
            ref(artifact.get('nodeId'), 'nodes', True)
            ref(artifact.get('runId'), 'runs', True)
            if artifact.get('origin') not in ('mock', 'observed'):
                raise StoreError('Artifact origin must be mock or observed.')
            if not isinstance(artifact.get('path', ''), str) or not isinstance(artifact.get('title', ''), str):
                raise StoreError('Artifact path and title must be text.')
            if artifact.get('origin') == 'observed':
                if not re.fullmatch(r'[a-f0-9]{64}', str(artifact.get('sha256', ''))) or type(artifact.get('bytes')) is not int or artifact['bytes'] < 0:
                    raise StoreError('Observed artifacts require a valid SHA-256 and byte count.')
        superseded = set()
        for assessment in p['assessments']:
            ref(assessment.get('runId'), 'runs')
            self._metrics(assessment.get('metrics', {}))
            refs(assessment.get('artifactIds', []), 'artifacts')
            if not isinstance(assessment.get('rubric'), str) or not assessment['rubric']:
                raise StoreError('Assessment rubric is required.')
            previous = assessment.get('supersedes')
            if previous:
                ref(previous, 'assessments')
                old = groups['assessments'][previous]
                if old['runId'] != assessment['runId'] or old['rubric'] != assessment['rubric']:
                    raise StoreError('A revised assessment must use the same run and rubric.', 'invalid_supersession')
                if previous in superseded:
                    raise StoreError('Assessment already has a revision; supersede its current revision.', 'revision_conflict', 409)
                superseded.add(previous)
                seen = {assessment['id']}
                while previous:
                    if previous in seen:
                        raise StoreError('Assessment revisions cannot contain a cycle.')
                    seen.add(previous)
                    previous = groups['assessments'][previous].get('supersedes')
        for decision in p['decisions']:
            ref(decision.get('nodeId'), 'nodes')
            refs(decision.get('runIds', []), 'runs')
            refs(decision.get('artifactIds', []), 'artifacts')
        usage_refs = set()
        for observation in p.get('observations', []):
            ref(observation.get('nodeId'), 'nodes')
            if observation.get('origin') not in ('observed', 'mock') or observation.get('status') not in ('running', 'finished'):
                raise StoreError('Observations require observed or mock origin and running or finished status.')
            if not isinstance(observation.get('title'), str):
                raise StoreError('Observation title must be text.')
            started = self._observation_time(observation.get('startedAt'))
            duration = observation.get('durationMs')
            if observation['status'] == 'running':
                if observation.get('finishedAt') is not None or duration is not None:
                    raise StoreError('Running observations cannot have finish time or duration.')
            else:
                finished = self._observation_time(observation.get('finishedAt'))
                if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                    raise StoreError('Finished observations require a nonnegative finite duration.')
                elapsed = (finished - started).total_seconds() * 1000
                if elapsed < 0 or abs(duration - elapsed) > 1:
                    raise StoreError('Observation duration must agree with a nonnegative start/finish interval within 1 ms.', 'invalid_observation_duration')
            source, usage_ref = observation.get('usageSource', ''), observation.get('usageRef', '')
            if not isinstance(source, str) or not isinstance(usage_ref, str):
                raise StoreError('Usage source and reference must be text.')
            for field in ('inputTokens', 'outputTokens'):
                value = observation.get(field)
                if value is not None and (type(value) is not int or value < 0):
                    raise StoreError('Token counters must be nonnegative integers or unknown.', 'invalid_token_counter')
                if value is not None and not source.strip():
                    raise StoreError('Supplied token counters require a runtime or provider usage source.', 'usage_source_required')
            if usage_ref:
                if not source.strip():
                    raise StoreError('Usage references require a usage source.', 'usage_source_required')
                key = (source.strip(), usage_ref.strip())
                if key in usage_refs:
                    raise StoreError('This usage source and reference were already recorded on another observation.', 'duplicate_usage_ref', 409)
                usage_refs.add(key)

    def _observation_time(self, value):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.utcoffset() is None:
                raise ValueError('Timezone required')
            return parsed
        except (AttributeError, TypeError, ValueError) as exc:
            raise StoreError('Observation times must be ISO timestamps with a timezone.') from exc

    def _metrics(self, metrics):
        object_value(metrics, 'Metrics')
        if any(type(value) not in (int, float, str, bool) for value in metrics.values()):
            raise StoreError('Metrics must contain numbers, strings or booleans.')

    def register_artifact(self, project_id, body):
        object_value(body, 'Artifact')
        if not isinstance(body.get('path'), str) or not body['path']:
            raise StoreError('Artifact path is required.')
        source = Path(body['path']).expanduser().resolve()
        with self._lock():
            bundle = self._load(project_id)
            self._expected(bundle['project'], body)
            p = copy.deepcopy(bundle['project'])
            allowed = [self._dir(project_id).resolve()] + [Path(root).resolve() for root in p.get('sourceRoots', [])]
            if not any(source.is_relative_to(root) for root in allowed):
                raise StoreError('Source file is outside this experiment’s source roots.', 'path_not_allowed', 403)
            if not source.is_file():
                raise StoreError('Source file does not exist.', 'not_found', 404)
            artifact_id = valid_id(body.get('id') or uid('artifact'))
            if any(a['id'] == artifact_id for a in p['artifacts']):
                raise StoreError('Artifact ID already exists.', 'conflict', 409)
            destination_dir = self._dir(project_id) / 'evidence'
            destination_dir.mkdir(exist_ok=True)
            suffix = source.suffix[:20] if re.fullmatch(r'\.[A-Za-z0-9_-]{1,19}', source.suffix) else ''
            destination = destination_dir / f'{artifact_id}{suffix}'
            fd, temporary = tempfile.mkstemp(prefix='.evidence-', dir=destination_dir)
            try:
                digest, size = hashlib.sha256(), 0
                with os.fdopen(fd, 'wb') as target, open(source, 'rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        target.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                artifact = {'id': artifact_id, 'nodeId': body.get('nodeId'), 'runId': body.get('runId'),
                            'title': body.get('title') or source.name, 'path': str(destination),
                            'sourcePath': str(source), 'sha256': digest.hexdigest(), 'bytes': size,
                            'mime': mimetypes.guess_type(source.name)[0] or 'application/octet-stream',
                            'createdAt': now(), 'origin': 'observed'}
                p['artifacts'].append(artifact)
                if artifact['runId']:
                    self._find(p, 'runs', artifact['runId']).setdefault('artifactIds', []).append(artifact_id)
                self._validate(p)
                os.replace(temporary, destination)
                self._record(bundle, p, [{'op': 'artifact.register', 'data': {'id': artifact_id, 'title': artifact['title']}}])
                try:
                    self._save(bundle)
                except Exception:
                    destination.unlink(missing_ok=True)
                    raise
                return copy.deepcopy(artifact)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def _artifact_location(self, project_id, project, artifact):
        evidence = (self._dir(project_id) / 'evidence').resolve()
        recorded = Path(artifact.get('path', ''))
        if artifact.get('origin') == 'observed':
            # The retained copy is addressed inside the current data directory.
            # An absolute path from an export is never followed outside it.
            basename = recorded.name
            if not re.fullmatch(re.escape(artifact['id']) + r'(\.[A-Za-z0-9_-]{1,19})?', basename):
                basename = artifact['id']
            path = (evidence / basename).resolve()
            if not path.is_relative_to(evidence):
                raise StoreError('This evidence has no registered local copy.', 'evidence_unavailable', 404)
            return path
        path = recorded.resolve()
        allowed_mock = artifact.get('origin') == 'mock' and any(
            path.is_relative_to(Path(root).resolve()) for root in project.get('sourceRoots', []))
        if not path.is_relative_to(evidence) and not allowed_mock:
            raise StoreError('This evidence has no registered local copy.', 'evidence_unavailable', 404)
        return path

    def _verify_evidence(self, stream, artifact):
        sha256, size = identity(stream)
        if sha256 != artifact.get('sha256') or size != artifact.get('bytes'):
            raise StoreError('Evidence content changed after registration.', 'evidence_changed', 409)

    def artifact_metadata(self, project_id, artifact_id):
        with self._lock():
            p = self._load(project_id)['project']
            artifact = self._find(p, 'artifacts', artifact_id)
            path = self._artifact_location(project_id, p, artifact)
            try:
                with path.open('rb') as stream:
                    self._verify_evidence(stream, artifact)
            except OSError as exc:
                raise StoreError('Evidence file is missing.', 'evidence_missing', 404) from exc
            return copy.deepcopy(artifact) | {'path': str(path), 'verified': True}

    def artifact_content(self, project_id, artifact_id, offset=None, limit=None):
        bounded = offset is not None or limit is not None
        if bounded:
            offset = 0 if offset is None else offset
            limit = 262144 if limit is None else limit
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1024 * 1024:
                raise StoreError('Preview offset must be nonnegative and limit must be 1–1048576 bytes.', 'invalid_preview_range')
        with self._lock():
            p = self._load(project_id)['project']
            artifact = self._find(p, 'artifacts', artifact_id)
            path = self._artifact_location(project_id, p, artifact)
            try:
                with path.open('rb') as stream:
                    self._verify_evidence(stream, artifact)
                    stream.seek(offset if bounded else 0)
                    raw = stream.read(limit) if bounded else stream.read()
            except OSError as exc:
                raise StoreError('Evidence file is missing.', 'evidence_missing', 404) from exc
            return raw, copy.deepcopy(artifact)

    def history(self, project_id):
        with self._lock():
            return [{key: copy.deepcopy(value) for key, value in entry.items() if key != 'snapshot'}
                    for entry in self._load(project_id)['history']]

    def restore(self, project_id, body):
        object_value(body, 'Restore')
        if 'expectedRevision' not in body:
            raise StoreError('expectedRevision is required for restore.')
        with self._lock():
            bundle = self._load(project_id)
            self._expected(bundle['project'], body)
            match = next((h for h in bundle['history'] if h['revision'] == body.get('revision')), None)
            if match is None:
                raise StoreError('Revision not found.', 'not_found', 404)
            p = copy.deepcopy(match['snapshot'])
            self._validate(p)
            self._record(bundle, p, [{'op': 'project.restore', 'data': {'revision': body['revision']}}])
            self._save(bundle)
            return copy.deepcopy(p)

    def context(self, project_id, node_id=None):
        p = self.get_project(project_id)
        nodes = p['nodes']
        if node_id:
            self._find(p, 'nodes', node_id)
            selected = {node_id}
            while True:
                more = {n['id'] for n in nodes if n.get('parentId') in selected}
                if more <= selected:
                    break
                selected.update(more)
            nodes = [n for n in nodes if n['id'] in selected]
        else:
            selected = {n['id'] for n in nodes}
        decisions = [d for d in p['decisions'] if d['nodeId'] in selected]
        referenced_runs = {run_id for decision in decisions for run_id in decision.get('runIds', [])}
        runs = [r for r in p['runs'] if r.get('nodeId') in selected or r['id'] in referenced_runs]
        superseded = {a.get('supersedes') for a in p['assessments'] if a.get('supersedes')}
        run_ids = {r['id'] for r in runs}
        assessments = [a for a in p['assessments'] if a['runId'] in run_ids and a['id'] not in superseded]
        artifact_ids = {artifact_id for record in runs + decisions + assessments for artifact_id in record.get('artifactIds', [])}
        artifacts = [a for a in p['artifacts'] if a['id'] in artifact_ids or a.get('nodeId') in selected or a.get('runId') in run_ids]
        edges = [e for e in p['edges'] if e['source'] in selected or e['target'] in selected]
        boundary_ids = ({r['nodeId'] for r in runs} | {e[endpoint] for e in edges for endpoint in ('source', 'target')}) - selected
        def compact(records, fields):
            return [{key: record.get(key) for key in fields} for record in records]
        return {'projectId': p['id'], 'name': p['name'], 'revision': p['revision'], 'description': p['description'],
                'nodes': [{k: n.get(k) for k in ('id', 'title', 'kind', 'status', 'parentId', 'summary', 'nextAction', 'importance', 'importanceReason', 'pauseReason', 'resumeWhen')} for n in nodes],
                'boundaryNodes': compact([n for n in p['nodes'] if n['id'] in boundary_ids], ('id', 'title', 'kind', 'status', 'importance')),
                'edges': edges,
                'runs': [{k: r.get(k) for k in ('id', 'nodeId', 'title', 'status', 'metrics', 'artifactIds', 'origin')} for r in runs],
                'assessments': compact(assessments, ('id', 'runId', 'rubric', 'metrics', 'conclusion', 'limitations', 'artifactIds', 'supersedes', 'createdAt')),
                'decisions': compact(decisions, ('id', 'nodeId', 'title', 'conclusion', 'scope', 'nextAction', 'runIds', 'artifactIds', 'createdAt')),
                'artifacts': compact(artifacts, ('id', 'nodeId', 'runId', 'title', 'path', 'sha256', 'bytes', 'mime', 'createdAt', 'origin')),
                'observations': compact([o for o in p.get('observations', []) if o['nodeId'] in selected],
                                        ('id', 'nodeId', 'title', 'status', 'startedAt', 'finishedAt', 'durationMs', 'inputTokens', 'outputTokens', 'usageSource', 'usageRef', 'origin')),
                'counts': {key: len(p.get(key, [])) for key in ('nodes', 'runs', 'artifacts', 'assessments', 'observations')},
                'warnings': [f'Run {r["id"]} is {r["status"]}.' for r in runs if r['status'] in ('running', 'failed', 'invalid')]}
