"""Measured response-task usage from retained execution evidence.

Version 1 of expObserverUsage declares per-invocation deltas, never conversation
totals. Only that explicit namespace/event or a complete Codex JSONL stream is
recognized; ordinary research metrics named tokens/usage are not counters here.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from .store import StoreError

COUNTERS = ('inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens')
MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
MAX_POLL_BYTES = 16 * 1024 * 1024


def _counter(value):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError('Execution usage counters must be measured nonnegative integers.')
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError(f'Execution usage requires an explicit {name}.')
    return value


def _bounds(run):
    start, finish = run.get('startedAt'), run.get('finishedAt')
    if start is None or finish is None:
        return None, None
    parsed = [datetime.fromisoformat(value.replace('Z', '+00:00')) for value in (start, finish)]
    if any(value.utcoffset() is None for value in parsed) or parsed[1] < parsed[0]:
        raise ValueError('Execution usage requires valid measured execution bounds.')
    return start, finish


def _declarations(value):
    """The versioned namespace declares sourceRef as the original invocation ID."""
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('Unsupported explicit execution usage protocol version.')
    records = value.get('records')
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError('Execution usage protocol requires a bounded records array.')
    result = []
    for item in records:
        if not isinstance(item, dict) or item.get('scope', 'execution') != 'execution' or item.get('counterKind', 'delta') != 'delta':
            raise ValueError('Execution usage protocol accepts only execution deltas.')
        record = {field: _text(item.get(field), field) for field in ('source', 'sourceRef', 'provider')}
        record['model'] = _text(item.get('model', 'unknown'), 'model')
        record.update({field: _counter(item.get(field)) for field in COUNTERS})
        if all(record[field] is None for field in COUNTERS):
            raise ValueError('Execution usage declaration contains no measured counters.')
        result.append(record)
    return result


def decode_evidence(raw):
    """Return explicit declarations and native Codex turns, without guessing layout."""
    text = raw.decode('utf-8-sig')
    try:
        document = json.loads(text)
    except ValueError:
        document = None
    if isinstance(document, dict) and 'expObserverUsage' in document:
        return _declarations(document['expObserverUsage']), []
    lines = [line for line in text.splitlines() if line.strip()]
    decoded, complete_jsonl = [], True
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            complete_jsonl = False
            continue
        if not isinstance(event, dict):
            complete_jsonl = False
            continue
        decoded.append(event)
    declarations = []
    for event in decoded:
        if event.get('type') == 'expobserver.usage.v1':
            # A stream event is one version-1 declaration, with an original
            # source/ref supplied by the executor rather than invented here.
            declarations.extend(_declarations({'version': 1, 'records': [event]}))
    if not complete_jsonl or not decoded or decoded[0].get('type') != 'thread.started':
        return declarations, []
    turns, thread, ordinal, waiting, seen = [], None, 0, False, set()
    for event in decoded:
        kind = event.get('type')
        if kind == 'thread.started':
            thread = _text(event.get('thread_id'), 'Codex thread ID')
            if thread in seen:
                raise ValueError('Repeated Codex thread headers need an explicit invocation identity.')
            seen.add(thread)
            ordinal, waiting = 0, False
        elif kind == 'turn.started':
            if waiting:
                raise ValueError('Overlapping Codex turns cannot be attributed from this stream.')
            ordinal += 1
            waiting = True
        elif kind == 'turn.failed':
            if not waiting:
                ordinal += 1
            waiting = False
        elif kind == 'turn.completed':
            if not waiting:
                ordinal += 1
            usage = event.get('usage')
            if not isinstance(usage, dict) or any(field not in usage for field in ('input_tokens', 'output_tokens')):
                raise ValueError('Codex completion has no measured native usage.')
            record = {'threadId': thread, 'turnOrdinal': ordinal, 'source': 'codex-cli', 'provider': 'codex',
                      'model': 'unknown', 'inputTokens': _counter(usage['input_tokens']),
                      'outputTokens': _counter(usage['output_tokens']),
                      'cacheReadTokens': _counter(usage.get('cached_input_tokens')),
                      'cacheWriteTokens': _counter(usage.get('cache_write_input_tokens'))}
            if record['inputTokens'] is None or record['outputTokens'] is None:
                raise ValueError('Codex completion requires measured input and output counters.')
            if 'reasoning_output_tokens' in usage:
                record['reasoningOutputTokens'] = _counter(usage['reasoning_output_tokens'])
            turns.append(record)
            waiting = False
        elif kind not in ('item.started', 'item.updated', 'item.completed', 'error'):
            # Unknown JSON/object wrappers are not evidence of a native stream.
            return declarations, []
    # An unfinished trailing turn does not invalidate earlier completed turns.
    return declarations, turns


class CapturedUsageAdapter:
    source = 'captured-execution'
    direct_attribution = True

    def __init__(self, store):
        self.store = store
        self.warnings = []
        self.cache = {}
        self.retry_after = {}

    def _warning(self, project_id, message):
        self.warnings.append({'projectId': project_id, 'source': self.source, 'pending': True,
                              'recordingWarnings': [message]})

    def _record(self, raw, run, artifact=None):
        source, ref = raw['source'], raw['sourceRef']
        start, finish = _bounds(run)
        record = {key: value for key, value in raw.items() if key not in ('threadId', 'turnOrdinal')}
        record.update(id='usage-' + hashlib.sha256(json.dumps([source, ref], separators=(',', ':')).encode()).hexdigest()[:32],
                      nodeId=run['nodeId'], executionRunId=run['id'], scope='execution',
                      attribution='captured-execution', timestampScope='execution',
                      tokenSemantics='runtime-reported', startedAt=start, finishedAt=finish)
        if artifact is not None:
            record.update(evidenceArtifactId=artifact['id'], evidenceSha256=artifact['sha256'])
        if record['model'] == 'unknown':
            record['modelSource'] = 'unreported'
        return record

    def read(self, projects):
        self.warnings = []
        output = {}
        remaining = MAX_POLL_BYTES
        retained = set()
        for project in projects:
            existing = {(r['source'], r['sourceRef']): r for r in project.get('usageRecords', [])}
            found, conflicts = {}, set()
            artifacts = {a['id']: a for a in project.get('artifacts', []) if a.get('origin') == 'observed'}
            node_ids = {node['id'] for node in project['nodes']}

            def collect(record):
                key = record['source'], record['sourceRef']
                if key in conflicts:
                    return
                old = found.get(key) or existing.get(key)
                if old is not None:
                    fields = (*COUNTERS, 'provider', 'model')
                    if any(old.get(field) != record.get(field) for field in fields):
                        found.pop(key, None)
                        conflicts.add(key)
                        self._warning(project['id'], 'Conflicting execution evidence reused a source/ref; counters were not changed.')
                        return
                    # Keep the original source identity/provenance on replay or
                    # when an explicit response is retained in another snapshot.
                    prior = dict(old)
                    if prior.get('nodeId') != record['nodeId']:
                        if key in found:
                            prior.update(nodeId=None, attribution='ambiguous-execution')
                        else:
                            prior.update(nodeId=record['nodeId'], attribution='captured-execution')
                    record = prior
                found[key] = record

            for run in project.get('runs', []):
                if run.get('origin') != 'observed' or run.get('nodeId') not in node_ids:
                    continue
                configuration = run.get('configuration', {})
                invoked = isinstance(configuration.get('command'), list) and bool(configuration['command']) and not configuration.get('capturedExternalResult')
                # Explicit protocol sourceRefs identify original invocations even
                # in retained external results. A raw Codex stream has no global
                # turn ID, so only a proven execution run may supply its identity.
                try:
                    namespace = run.get('metrics', {}).get('expObserverUsage')
                    if namespace is not None:
                        for declaration in _declarations(namespace):
                            collect(self._record(declaration, run))
                except (ValueError, TypeError, AttributeError, KeyError) as exc:
                    self._warning(project['id'], str(exc))
                for artifact_id in run.get('artifactIds', []):
                    artifact = artifacts.get(artifact_id)
                    if artifact is None or artifact.get('runId') != run['id']:
                        continue
                    media_type = artifact.get('mime', '').partition(';')[0]
                    suffix = Path(artifact.get('path', '')).suffix.lower()
                    if not (media_type.startswith('text/') or media_type in ('application/json', 'application/x-ndjson', 'application/jsonl')
                            or suffix in ('.json', '.jsonl', '.ndjson', '.txt', '.log')):
                        continue
                    size = artifact.get('bytes')
                    if type(size) is not int or not 0 <= size <= MAX_EVIDENCE_BYTES:
                        continue
                    key = project['id'], artifact_id, artifact.get('sha256'), size
                    retained.add(key)
                    if time.monotonic() < self.retry_after.get(key, 0):
                        continue
                    try:
                        if key not in self.cache:
                            if size > remaining:
                                continue
                            remaining -= size
                            # Store resolves the retained copy inside app data and
                            # verifies its registered digest; sourcePath is ignored.
                            raw, verified = self.store.artifact_content(project['id'], artifact_id)
                            self.cache[key] = decode_evidence(raw)
                        declarations, turns = self.cache[key]
                        for declaration in declarations:
                            collect(self._record(declaration, run, artifact))
                        if invoked:
                            for turn in turns:
                                turn = {**turn, 'sourceRef': json.dumps([project['id'], run['id'], turn['threadId'], turn['turnOrdinal']], separators=(',', ':'))}
                                collect(self._record(turn, run, artifact))
                    except (StoreError, OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError) as exc:
                        # Bad or temporarily unavailable files cannot consume
                        # every poll's byte budget and starve later evidence.
                        self.retry_after[key] = time.monotonic() + 30
                        self._warning(project['id'], 'Execution usage evidence could not be read: ' + str(exc))
            if found:
                output[project['id']] = list(found.values())
        for key in self.cache.keys() - retained:
            del self.cache[key]
        for key in self.retry_after.keys() - retained:
            del self.retry_after[key]
        return output