"""Read native Codex counters scoped by durable Observer capture receipts.

No chat is bound to an experiment. Each matched recording checkpoint supplies a
work window; overlapping/multiple-node checkpoints remain project-unassigned.
Only counters and receipt identities survive parsing, never transcript prose.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .host_usage import observer_origin, timestamp, cli_calls

UUID = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
FIELDS = {'input_tokens': 'inputTokens', 'output_tokens': 'outputTokens',
          'cached_input_tokens': 'cacheReadTokens', 'cache_write_input_tokens': 'cacheWriteTokens'}


def json_objects(value, depth=0):
    """Decode structured tool envelopes and JSON lines, not quoted prose."""
    if depth > 8:
        return
    if isinstance(value, dict):
        yield value
        for key in ('output', 'text', 'value', 'content'):
            if key in value:
                yield from json_objects(value[key], depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from json_objects(item, depth + 1)
    elif isinstance(value, str):
        for line in value.splitlines():
            try:
                parsed = json.loads(line)
            except (ValueError, TypeError):
                continue
            yield from json_objects(parsed, depth + 1)



def tool_invocations(payload):
    name = payload.get('name', '').removeprefix('functions.')
    raw = payload.get('arguments') or payload.get('input') or ''
    if name in ('exec_command', 'write_stdin'):
        try:
            args = json.loads(raw)
            return [(name, args)] if isinstance(args, dict) else []
        except (ValueError, TypeError):
            return []
    if name != 'exec':
        return []
    # Tokenize rather than matching prose inside strings; never evaluate JS.
    token = re.compile(r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//[^\n]*|/\*[\s\S]*?\*/|[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|[^\s])''')
    tokens = token.findall(raw)
    calls = []
    for i in range(len(tokens) - 8):
        if tokens[i:i + 2] != ['tools', '.'] or tokens[i + 2] not in ('exec_command', 'write_stdin') or tokens[i + 3:i + 5] != ['(', '{']:
            continue
        j, args = i + 5, {}
        while j + 2 < len(tokens) and tokens[j] != '}':
            key, colon, value = tokens[j:j + 3]
            if colon != ':':
                break
            try:
                literal = json.loads(value)
            except ValueError:
                break
            args[key.strip('"')] = literal
            j += 3
            if tokens[j:j + 1] == [',']:
                j += 1
            else:
                break
        calls.append((tokens[i + 2], args))
    return calls


def recorded_cli_projects(payload):
    commands = [args.get('cmd', '') for name, args in tool_invocations(payload) if name == 'exec_command']
    found = set()
    for command in commands:
        # Heredoc bodies can contain arbitrary code. They never prove an
        # invocation; literal CLI lines outside those bodies can still do so.
        delimiter = None
        for line in command.splitlines():
            if delimiter:
                if line.strip() == delimiter:
                    delimiter = None
                continue
            heredoc = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)", line)
            if heredoc:
                delimiter = heredoc.group(1)
            project_flag = re.search(r"--project(?:=|\s+)[\"']?[A-Za-z0-9][A-Za-z0-9_.-]*[\"']?", line)
            if project_flag:
                # Analysis text after the identity may legitimately contain
                # Markdown backticks; it is not shell syntax used for identity.
                found.update(cli_calls(line[:project_flag.end()]))
    return found

class CodexSessionAdapter:
    direct_attribution = True
    source = 'codex-session'

    def __init__(self, roots=None, *, url='http://127.0.0.1:4317'):
        homes = roots if roots is not None else [os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))]
        self.roots = tuple(dict.fromkeys(Path(home).expanduser().resolve() / 'sessions' for home in homes))
        self.url = url
        self.outboxes = ()
        self.cache = {}
        self.discovered = {}
        self.warnings = []

    def captures(self, projects):
        by_id = {p['id']: p for p in projects}
        tasks = {}
        for directory in self.outboxes:
            owner = Path(directory).parent.parent
            for path in Path(directory).glob('*.json'):
                try:
                    if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                        continue
                    task = json.loads(path.read_text(encoding='utf-8'))
                    project = by_id.get(task.get('projectId'))
                    if not project or task.get('state') != 'synced' or task.get('version') != 1:
                        continue
                    if observer_origin(task.get('url')) != observer_origin(self.url):
                        continue
                    if str(owner) not in project.get('_usageRoots', []):
                        continue
                    if task.get('intent', {}).get('command') not in ('event', 'record', 'execute'):
                        continue
                    if task.get('nodeId') not in {n['id'] for n in project['nodes']}:
                        continue
                    timestamp(task.get('capturedAt') or task['startedAt'])
                    tasks[(task['projectId'], task['requestId'], task['nodeId'])] = task
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return tasks

    def paths(self, tasks):
        # Explicit host hints make new captures cheap. Legacy captures discover
        # only their recording dates, and still require an exact output receipt.
        days, hints, legacy = set(), set(), False
        for task in tasks.values():
            day = datetime.fromtimestamp(timestamp(task.get('capturedAt') or task['startedAt']), timezone.utc)
            days.update((day + timedelta(days=d)).strftime('%Y/%m/%d') for d in (-1, 0, 1))
            hint = task.get('hostUsage', {}).get('threadId')
            if isinstance(hint, str) and UUID.fullmatch(hint):
                hints.add(hint)
            else:
                legacy = True
        found = set()
        for root in self.roots:
            for day in sorted(days):
                directory = root / day
                for path in directory.glob('rollout-*.jsonl'):
                    if (legacy or any(hint in path.name for hint in hints)) and not path.is_symlink() and path.resolve().is_relative_to(root):
                        found.add(path)
        return sorted(found)

    def parse(self, path):
        stat = path.stat()
        key = (stat.st_size, stat.st_mtime_ns)
        cached = self.cache.get(path)
        if cached and cached[0] == key:
            return cached[1]
        if stat.st_size > 64 * 1024 * 1024:
            return []
        turns, current, session, model, provider = [], None, None, 'unknown', 'unknown'
        calls, polls, sessions = {}, {}, {}
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                if len(line) > 4 * 1024 * 1024:
                    continue
                try:
                    event = json.loads(line)
                    payload = event.get('payload') or {}
                    kind, at = event.get('type'), event.get('timestamp')
                    timestamp(at)
                    if kind == 'session_meta':
                        session = payload.get('id')
                        provider = payload.get('model_provider') or 'unknown'
                    if kind == 'turn_context':
                        model = payload.get('model') or model
                    if kind == 'event_msg' and payload.get('type') == 'task_started':
                        current = {'start': at, 'end': None, 'raw': [], 'fallback': [], 'anchors': [], 'model': model}
                        turns.append(current)
                    if current is None:
                        continue
                    if kind == 'turn_context':
                        current['model'] = model
                    if kind == 'event_msg' and payload.get('type') == 'task_complete':
                        current['end'] = at
                    if kind == 'token_usage_record' and payload.get('response_id'):
                        current['raw'].append((at, payload['response_id'], payload.get('usage', {}), model))
                    if kind == 'event_msg' and payload.get('type') == 'token_count':
                        info = payload.get('info') or {}
                        current['fallback'].append((at, info.get('total_token_usage'), info.get('last_token_usage'), model))
                    if kind == 'response_item' and payload.get('type') in ('function_call', 'custom_tool_call'):
                        call_id = payload.get('call_id')
                        calls[call_id] = recorded_cli_projects(payload)
                        polls[call_id] = [args.get('session_id') for name, args in tool_invocations(payload) if name == 'write_stdin']
                    if kind == 'response_item' and payload.get('type') in ('function_call_output', 'custom_tool_call_output'):
                        call_id = payload.get('call_id')
                        actual = set(calls.get(call_id, set()))
                        for session_id in polls.get(call_id, []):
                            actual.update(sessions.get(session_id, set()))
                        for receipt in json_objects(payload.get('output')):
                            if type(receipt.get('session_id')) is int and actual:
                                sessions[receipt['session_id']] = actual
                            if {'projectId', 'requestId', 'nodeId'} <= receipt.keys() and (observer_origin(self.url), receipt['projectId']) in actual:
                                current['anchors'].append((at, {k: receipt[k] for k in ('projectId', 'requestId', 'nodeId')}))
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue
        value = (session, provider, turns)
        self.cache[path] = key, value
        while len(self.cache) > 128:
            del self.cache[next(iter(self.cache))]
        return value

    def read(self, projects):
        self.warnings = []
        tasks = self.captures(projects)
        if not tasks or observer_origin(self.url) is None:
            return {}
        result, seen = defaultdict(list), set()
        unresolved = {key: task for key, task in tasks.items() if key not in self.discovered}
        paths = {path for key, path in self.discovered.items() if key in tasks}
        paths.update(self.paths(unresolved))
        for path in sorted(paths):
            try:
                parsed = self.parse(path)
                if not parsed:
                    continue
                session, provider, turns = parsed
                if not isinstance(session, str) or not UUID.fullmatch(session):
                    continue
                previous_total = None
                for turn in turns:
                    last_total = previous_total
                    if turn['fallback'] and isinstance(turn['fallback'][-1][1], dict):
                        previous_total = turn['fallback'][-1][1]
                    anchors = []
                    for at, receipt in turn['anchors']:
                        key = tuple(receipt.get(k) for k in ('projectId', 'requestId', 'nodeId'))
                        if key in tasks:
                            self.discovered[key] = path
                            anchors.append((at, key[0], key[2]))
                        else:
                            # Another experiment/unknown checkpoint is a barrier,
                            # never charge its work to the last known experiment.
                            anchors.append((at, None, None))
                    if not any(project_id for _, project_id, _ in anchors):
                        continue
                    grouped = []
                    for at in sorted({a[0] for a in anchors}):
                        group = {(p, n) for t, p, n in anchors if t == at}
                        ids = {p for p, _ in group}
                        grouped.append((at, next(iter(ids)) if len(ids) == 1 else None,
                                        next(iter(group))[1] if len(group) == 1 else None))
                    measured = turn['raw']
                    if not measured:
                        # A closing turn fixes whether this format has native
                        # response records; never import a transient UI event
                        # and later add its native counterpart a second time.
                        if not turn['end']:
                            continue
                        measured = []
                        for index, (at, total, last, version) in enumerate(turn['fallback']):
                            if not isinstance(total, dict):
                                continue
                            if last_total is None:
                                delta = last
                            elif total == last_total:
                                continue
                            elif all(type(total.get(k)) is int and type(last_total.get(k)) is int
                                     and total[k] >= last_total[k] for k in ('input_tokens', 'output_tokens')):
                                delta = {k: total[k] - last_total[k] for k in FIELDS
                                         if type(total.get(k)) is int and type(last_total.get(k)) is int}
                            else:
                                # Compaction/reset: only an explicit last record
                                # can identify this inference, never clamp totals.
                                delta = last
                            last_total = total
                            measured.append((at, f'{turn["start"]}:{index}', delta, version))
                    for at, ref, usage, version in measured:
                        source_ref = f'{session}:{ref}'
                        if source_ref in seen or not isinstance(usage, dict):
                            continue
                        if not all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens')):
                            continue
                        checkpoint = next((a for a in grouped if a[0] >= at), None)
                        if checkpoint is None:
                            # Retain final interpretation after the last capture,
                            # but do not pretend its precise node is known.
                            if not turn['end']:
                                continue
                            checkpoint = (turn['end'], grouped[-1][1], None)
                        _, project_id, node_id = checkpoint
                        if project_id is None:
                            continue
                        # A switch of experiment delimits ownership; the first
                        # response after a switch is ambiguous and stays out.
                        previous = [a for a in grouped if a[0] < at]
                        if previous and previous[-1][1] != project_id:
                            continue
                        record = {'id': 'usage-' + hashlib.sha256(source_ref.encode()).hexdigest()[:32],
                                  'source': self.source, 'sourceRef': source_ref, 'agentId': session,
                                  'provider': provider, 'model': version, 'startedAt': at, 'finishedAt': at,
                                  'nodeId': node_id, 'scope': 'agent', 'tokenSemantics': 'input-includes-cache',
                                  'attribution': 'recorded-work-window' if node_id else 'project-unassigned'}
                        for key, field in FIELDS.items():
                            value = usage.get(key)
                            record[field] = value if type(value) is int and value >= 0 else None
                        result[project_id].append(record)
                        seen.add(source_ref)
            except (OSError, ValueError, TypeError):
                self.warnings.append({'source': self.source, 'pending': True,
                                      'recordingWarnings': ['A Codex usage log could not be read.']})
        return dict(result)
