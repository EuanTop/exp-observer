"""Optional host adapters import measured inference records, never estimates.

The collection/Store interface is host independent. Happy's SQLite tables are an
internal, version-checked adapter, not a public API contract. No credentials,
provider context, or environment values are read here.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import time
from urllib.parse import urlsplit

from .store import StoreError


def iso_time(milliseconds):
    if type(milliseconds) is not int or milliseconds < 0:
        raise ValueError('Host usage requires measured millisecond timestamps.')
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('Timezone required')
    return parsed.timestamp()


def cli_calls(command):
    """Recognize actual top-level CLI argv; never match quoted prose/code.

    Unsupported shell constructs remain unbound. In particular, Python -c,
    shell wrappers, here-documents, substitutions and diagnostic snippets cannot
    become a research-agent binding merely by mentioning a project ID.
    """
    if not isinstance(command, str):
        return set()
    windows = os.name == 'nt' or bool(re.search(r'[A-Za-z]:[\\/]|\b(?:python[\d.]*|py)\.exe\b', command, re.I))
    command = re.sub(r'`\r?\n', ' ', command) if windows else command.replace('\\\n', ' ')
    if any(part in command for part in ('<<', '$(', '`')):
        return set()
    lexer = shlex.shlex(command, posix=not windows, punctuation_chars='\n;&|<>()')
    lexer.whitespace = ' \t\r'
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return set()
    statements, current = [], []
    for token in tokens:
        if token and all(char in '\n;&|' for char in token):
            statements.append(current)
            current = []
        else:
            current.append(token)
    statements.append(current)
    calls = set()
    for args in statements:
        args = [arg.strip('"\'') if windows else arg for arg in args]
        if not args:
            continue
        executable = args.pop(0).replace('\\', '/').rsplit('/', 1)[-1]
        if re.fullmatch(r'(?:python(?:\d+(?:\.\d+)*)?|py)(?:\.exe)?', executable, re.I):
            while args:
                flag = args[0]
                if flag in ('-u', '-B', '-E', '-I', '-s', '-S', '-P', '-q', '-O', '-OO', '-b', '-bb') or re.fullmatch(r'-3(?:\.\d+)?', flag):
                    args.pop(0)
                elif flag in ('-X', '-W') and len(args) >= 2 and not args[1].startswith('-'):
                    del args[:2]
                elif flag.startswith(('-X', '-W')) and len(flag) > 2:
                    args.pop(0)
                else:
                    break
            if not args or args.pop(0).replace('\\', '/').rsplit('/', 1)[-1].lower() != 'exp_observer.py':
                continue
        elif executable != 'exp_observer.py':
            continue
        url = 'http://127.0.0.1:4317'
        if args[:1] == ['--url']:
            if len(args) < 2:
                continue
            url = args[1]
            args = args[2:]
        elif args and args[0].startswith('--url='):
            url = args.pop(0).partition('=')[2]
        if not args or args.pop(0) not in ('execute', 'record', 'event'):
            continue
        args = args[:args.index('--')] if '--' in args else args
        supplied = []
        for index, arg in enumerate(args):
            if arg == '--project' and index + 1 < len(args):
                supplied.append(args[index + 1])
            elif arg.startswith('--project='):
                supplied.append(arg.partition('=')[2])
        if len(supplied) == 1 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', supplied[0]):
            calls.add((observer_origin(url), supplied[0]))
    return calls


def cli_projects(command, *, url=None):
    return {project_id for origin, project_id in cli_calls(command)
            if url is None or origin == observer_origin(url)}


def in_source_roots(directory, project):
    if not isinstance(directory, str) or not Path(directory).is_absolute():
        return False
    try:
        directory = Path(directory).resolve(strict=True)
        return directory.is_dir() and any(directory.is_relative_to(Path(root).resolve(strict=True))
                                         for root in project.get('_usageRoots', project.get('sourceRoots', [])))
    except (OSError, RuntimeError, ValueError):
        return False


class HappySQLiteAdapter:
    """Read only finished inference rows for an explicitly bound agent itself.

    Public Happy usage endpoints aggregate lifetime subtrees or whole runs; they
    cannot supply historical per-inference attribution. This optional adapter
    preserves the four raw host fields without claiming cache billing semantics.
    """
    def __init__(self, database=None, *, url='http://127.0.0.1:4317'):
        self.database = Path(database) if database is not None else Path.home() / '.happy' / 'agent' / 'agent.sqlite'
        self.source = 'happy-sqlite:' + hashlib.sha256(str(self.database.absolute()).encode()).hexdigest()[:16]
        self.url = url

    def read(self, projects):
        if observer_origin(self.url) is None or not self.database.exists():
            return {}
        with closing(sqlite3.connect(self.database.absolute().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.execute('PRAGMA query_only = ON')
            # Bindings and inference rows must describe the same host snapshot.
            db.execute('BEGIN')
            # Querying named columns also checks the internal adapter schema.
            db.execute('SELECT agent_id, record_id, kind, run_id, record_json, finished_at FROM happy_agent_usage_records LIMIT 0')
            db.execute('SELECT agent_id, record_id, role, run_id, message_json, tool_calls FROM happy_agent_module_history LIMIT 0')
            candidates = set()
            for project in projects:
                rows = db.execute("SELECT agent_id, message_json FROM happy_agent_module_history "
                                  "WHERE tool_calls > 0 AND role IN ('assistant', 'agent') "
                                  "AND message_json LIKE '%exp_observer.py%' AND message_json LIKE ?",
                                  ('%' + project['id'] + '%',))
                for agent_id, encoded in rows:
                    for block in json.loads(encoded).get('blocks', []):
                        if block.get('type') != 'tool_call' or block.get('name') not in ('exec_command', 'functions.exec_command'):
                            continue
                        args = block.get('arguments', {})
                        if project['id'] in cli_projects(args.get('cmd'), url=self.url) and in_source_roots(args.get('workdir'), project):
                            candidates.add(agent_id)
            bound = {}
            for agent_id in candidates:
                called, matching = set(), set()
                for encoded, in db.execute("SELECT message_json FROM happy_agent_module_history WHERE agent_id = ? "
                                           "AND tool_calls > 0 AND role IN ('assistant', 'agent') "
                                           "AND message_json LIKE '%exp_observer.py%'", (agent_id,)):
                    for block in json.loads(encoded).get('blocks', []):
                        if block.get('type') != 'tool_call' or block.get('name') not in ('exec_command', 'functions.exec_command'):
                            continue
                        args = block.get('arguments', {})
                        called.update(cli_calls(args.get('cmd')))
                        ids = cli_projects(args.get('cmd'), url=self.url)
                        matching.update((observer_origin(self.url), p['id']) for p in projects
                                        if p['id'] in ids and in_source_roots(args.get('workdir'), p))
                if len(called) == len(matching) == 1 and called == matching:
                    bound[agent_id] = next(iter(called))[1]
            result = defaultdict(list)
            for agent_id, project_id in bound.items():
                for record_id, run_id, encoded in db.execute("SELECT record_id, run_id, record_json FROM happy_agent_usage_records "
                                                            "WHERE agent_id = ? AND kind = 'inference' ORDER BY finished_at, record_id", (agent_id,)):
                    raw = json.loads(encoded)
                    if raw.get('id') != record_id or raw.get('agentId') != agent_id or raw.get('runId') != run_id or raw.get('kind') != 'inference':
                        raise ValueError('Host inference identity does not agree with its durable row.')
                    tokens = raw['tokens']
                    record = {'id': 'usage-' + hashlib.sha256((self.source + '/' + record_id).encode()).hexdigest()[:32],
                              'source': self.source, 'sourceRef': record_id, 'agentId': agent_id, 'hostRunId': run_id,
                              'provider': raw['provider'], 'model': raw['model'],
                              'startedAt': iso_time(raw['startedAt']), 'finishedAt': iso_time(raw['finishedAt']),
                              'nodeId': None, 'attribution': 'project-unassigned', 'scope': 'agent', 'tokenSemantics': 'host-reported'}
                    for source, target in (('input', 'inputTokens'), ('output', 'outputTokens'),
                                           ('cacheRead', 'cacheReadTokens'), ('cacheWrite', 'cacheWriteTokens')):
                        value = tokens.get(source)
                        if value is not None and (type(value) is not int or value < 0):
                            raise ValueError('Host token counters must be measured nonnegative integers.')
                        record[target] = value
                    result[project_id].append(record)
            return dict(result)


def observer_origin(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.password:
            return None
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            return None
        return 'http', parsed.port or 80
    except (TypeError, ValueError, AttributeError):
        return None


def native_outbox_roots(projects, outboxes, connected, url):
    """A synced native capture can prove a text-only project's source owner.

    This evidence is local to the current observer and its enrolled workspace;
    it never rewrites the project's evidence/sourceRoots metadata.
    """
    origin = observer_origin(url)
    result = defaultdict(set)
    if origin is None:
        return result
    by_id = {project['id']: project for project in projects}
    for supplied in outboxes:
        outbox = Path(supplied)
        owner = outbox.parent.parent
        try:
            if outbox.name != 'outbox' or outbox.parent.name != '.exp-observer-runs' or outbox.resolve(strict=True) != outbox:
                continue
            if not any(owner.is_relative_to(root) for root in connected):
                continue
            for path in outbox.glob('*.json'):
                try:
                    if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                        continue
                    task = json.loads(path.read_text(encoding='utf-8'))
                    project = by_id.get(task.get('projectId'))
                    if project is None or type(task.get('version')) is not int or task['version'] != 1 or task.get('state') != 'synced':
                        continue
                    if observer_origin(task.get('url')) != origin or task.get('intent', {}).get('command') not in ('record', 'execute', 'event'):
                        continue
                    expected = owner / '.exp-observer-runs' / project['id']
                    capture = Path(task.get('captureRoot', ''))
                    if capture != expected or capture.resolve(strict=True) != capture or not capture.is_dir():
                        continue
                    aliases = project.get('nodeAliases', {})
                    node_id = aliases.get(task.get('nodeId'), task.get('nodeId'))
                    if node_id not in {node['id'] for node in project['nodes']}:
                        continue
                    if not any(op.get('op') in ('node.add', 'node.update', 'node.ensure') and
                               aliases.get(op.get('data', {}).get('id'), op.get('data', {}).get('id')) == node_id
                               for op in task.get('operations', [])):
                        continue
                    result[project['id']].add(str(owner))
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    continue
        except (OSError, ValueError, RuntimeError):
            continue
    return result


def active_intervals(project, outboxes, url=None):
    """Use frozen capture times, never delayed server-application timestamps."""
    expected_origin = observer_origin(url)
    if expected_origin is None:
        return []
    events = defaultdict(list)
    aliases = project.get('nodeAliases', {})
    nodes = {node['id']: node for node in project['nodes']}
    for outbox in outboxes:
        outbox = Path(outbox)
        owner = outbox.parent.parent
        roots = project.get('_usageRoots', project.get('sourceRoots', []))
        if outbox.name != 'outbox' or outbox.parent.name != '.exp-observer-runs' or outbox.resolve(strict=True) != outbox:
            continue
        if not any(owner.is_relative_to(Path(root)) for root in roots):
            continue
        for path in outbox.glob('*.json'):
            if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                continue
            task = json.loads(path.read_text(encoding='utf-8'))
            if task.get('version') != 1 or task.get('projectId') != project['id'] or task.get('kind') == 'project' or task.get('state') not in ('ready', 'synced'):
                continue
            if observer_origin(task.get('url')) != expected_origin:
                continue
            intent = task.get('intent', {}).get('command')
            for operation in task.get('operations', []):
                data = operation.get('data', {})
                operation_kind = operation.get('op')
                if operation_kind not in ('node.add', 'node.update', 'node.ensure') or 'status' not in data:
                    continue
                original_id = data.get('id')
                if aliases.get(original_id, original_id) not in nodes:
                    continue
                # A completed execute capture does not prove the node was active
                # during model work before/after the subprocess. Do not invent it.
                at = task.get('capturedAt') if intent in ('record', 'event') else task.get('finishedAt') if intent == 'execute' else None
                if at is not None:
                    events[original_id].append((timestamp(at), operation_kind, data['status']))
    intervals = defaultdict(list)
    for original_id, transitions in events.items():
        node_id = aliases.get(original_id, original_id)
        start = None
        seen = False
        for at, operation_kind, status in sorted(set(transitions)):
            # Ensure creates once. Later ensures carry frozen creation defaults,
            # not evidence that an existing/completed question became active.
            if operation_kind == 'node.ensure' and seen:
                continue
            seen = True
            if status == 'active':
                if start is None:
                    start = at
            elif start is not None:
                if at > start:
                    intervals[node_id].append((start, at))
                start = None
        if start is not None and nodes[node_id]['status'] == 'active':
            intervals[node_id].append((start, float('inf')))
    # Reconstruct each original identity before folding aliases. Interleaving
    # another merged node's completion must not truncate an active interval.
    merged = []
    for node_id, spans in intervals.items():
        union = []
        for start, end in sorted(spans):
            if union and start <= union[-1][1]:
                union[-1] = (union[-1][0], max(union[-1][1], end))
            else:
                union.append((start, end))
        merged.extend((node_id, start, end) for start, end in union)
    return merged


def attribute(record, intervals):
    start, end = timestamp(record['startedAt']), timestamp(record['finishedAt'])
    overlaps = {node_id for node_id, a, b in intervals if a <= end and b >= start}
    contained = {node_id for node_id, a, b in intervals if a <= start and end <= b}
    if len(overlaps) == len(contained) == 1 and overlaps == contained:
        return {**record, 'nodeId': next(iter(contained)), 'attribution': 'unique-active-interval'}
    return {**record, 'nodeId': None, 'attribution': 'project-unassigned'}


class HostUsageImporter:
    def __init__(self, store, adapters=None, *, interval=5, url=None):
        self.store = store
        if adapters is None:
            from .execution_usage import CapturedUsageAdapter
            from .codex_usage import CodexSessionAdapter
            adapters = [HappySQLiteAdapter(url=url or 'http://127.0.0.1:4317'),
                        CodexSessionAdapter(url=url or 'http://127.0.0.1:4317'), CapturedUsageAdapter(store)]
        self.adapters = adapters
        self.interval = interval
        self.url = url
        self.next_poll = 0

    def status(self, project_id):
        return {'projectId': project_id, 'adapters': [dict(adapter.diagnostics[project_id])
                for adapter in self.adapters if project_id in getattr(adapter, 'diagnostics', {})]}

    def drain_once(self, outboxes=()):
        if time.monotonic() < self.next_poll:
            return []
        self.next_poll = time.monotonic() + self.interval
        projects = [self.store.get_project(p['id']) for p in self.store.list_projects()]
        if not projects:
            return []
        connected = [Path(w['path']) for w in self.store.list_workspaces()]
        native_roots = native_outbox_roots(projects, outboxes, connected, self.url)
        for project in projects:
            roots = sorted(native_roots[project['id']])
            for supplied in project.get('sourceRoots', []):
                path = Path(supplied)
                try:
                    if path.resolve(strict=True) != path or not path.is_dir():
                        continue
                    if path.name == project['id'] and path.parent.name == '.exp-observer-runs':
                        # Staged evidence roots are not the command cwd. The
                        # exact native layout proves its owner, but enrollment
                        # must authorize that owner before broadening the scope.
                        owner = path.parent.parent
                        if any(owner.is_relative_to(root) for root in connected):
                            roots.append(str(owner))
                    else:
                        roots.append(str(path))
                except (OSError, ValueError, RuntimeError):
                    continue
            project['_usageRoots'] = roots
        results = []
        for adapter in self.adapters:
            try:
                if hasattr(adapter, 'outboxes'):
                    adapter.outboxes = outboxes
                records = adapter.read(projects)
                results.extend(getattr(adapter, 'warnings', []))
                for project in projects:
                    if project['id'] not in records:
                        continue
                    # Recovery supplies only outboxes inside its connected roots.
                    if getattr(adapter, 'direct_attribution', False):
                        measured = records[project['id']]
                    else:
                        try:
                            intervals = active_intervals(project, outboxes, self.url)
                        except (OSError, ValueError, KeyError, TypeError, AttributeError):
                            intervals = []
                            results.append({'projectId': project['id'], 'source': adapter.source, 'pending': True,
                                            'recordingWarnings': ['Node activity evidence is unavailable; host usage remains unassigned.']})
                        measured = [attribute(r, intervals) for r in records[project['id']]]
                    result = self.store.import_usage_records(project['id'], measured)
                    if result['imported'] or result['updated']:
                        results.append({'projectId': project['id'], 'source': adapter.source, **result, 'pending': False})
            except (OSError, sqlite3.Error, StoreError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
                if hasattr(adapter, 'diagnostics'):
                    adapter.diagnostics = {p['id']: {**getattr(adapter, 'diagnostics', {}).get(p['id'], {}),
                        'source': adapter.source, 'state': 'error', 'message': str(exc)} for p in projects}
                results.append({'source': adapter.source, 'pending': True,
                                'recordingWarnings': ['Optional host usage import is unavailable: ' + str(exc)]})
        return results
