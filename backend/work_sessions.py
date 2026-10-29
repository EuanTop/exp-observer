"""Durable, expiring conversation focus, separate from scientific graph history."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from .store import StoreError, canonical, object_value, valid_id


def clock():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError('Timezone required')
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise StoreError('observedAt must be an ISO timestamp with a timezone.', 'invalid_focus') from exc


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS work_sessions ('
               'project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, owner_id TEXT NOT NULL, lease_id TEXT NOT NULL, '
               'started_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, expires_at TEXT NOT NULL, '
               'ended INTEGER NOT NULL DEFAULT 0, sequence INTEGER NOT NULL, fingerprint TEXT NOT NULL, '
               'label TEXT NOT NULL, node_ids TEXT NOT NULL, revision INTEGER NOT NULL, '
               'PRIMARY KEY(project_id, owner_id, lease_id))')
    db.execute('CREATE INDEX IF NOT EXISTS work_sessions_project ON work_sessions(project_id, ended, last_seen_at)')


def _project(db, project_id):
    # Focus polls need only IDs and merge aliases, never large notes, evidence,
    # command output, usage records or reconstructable project history.
    row = db.execute('SELECT document FROM projects WHERE id=?', (valid_id(project_id),)).fetchone()
    if row is None:
        raise StoreError('Experiment not found.', 'not_found', 404)
    metadata = json.loads(row['document'])
    return {'nodeAliases': metadata.get('nodeAliases', {}),
            'nodes': [{'id': row['record_id']} for row in db.execute(
                "SELECT record_id FROM records WHERE project_id=? AND collection='nodes'", (project_id,))]}


def _session(row, project, checked):
    existing = {node['id'] for node in project['nodes']}
    aliases = project.get('nodeAliases', {})
    node_ids = list(dict.fromkeys(aliases.get(key, key) for key in json.loads(row['node_ids'])))
    return {'leaseId': row['lease_id'], 'ownerId': row['owner_id'], 'label': row['label'],
            'nodeIds': [key for key in node_ids if key in existing], 'startedAt': row['started_at'],
            'lastSeenAt': row['last_seen_at'], 'expiresAt': row['expires_at'],
            'state': 'ended' if row['ended'] else 'active' if parse_time(row['expires_at']) > checked else 'stale',
            'revision': row['revision']}


def get(store, project_id):
    with store._transaction() as db:
        project = _project(db, project_id)
        checked = clock()
        rows = db.execute('SELECT * FROM work_sessions WHERE project_id=? ORDER BY ended, last_seen_at DESC',
                          (project_id,)).fetchall()
        # Ended leases remain durable tombstones but need not fill the UI forever.
        active = [row for row in rows if not row['ended']]
        ended = [row for row in rows if row['ended']][:20]
        return {'projectId': project_id, 'checkedAt': stamp(checked),
                'sessions': [_session(row, project, checked) for row in active + ended]}


def update(store, project_id, body):
    object_value(body, 'Focus')
    if set(body) - {'action', 'ownerId', 'leaseId', 'nodeIds', 'label', 'ttlSeconds', 'observedAt', 'sequence'}:
        raise StoreError('Unknown focus fields.', 'invalid_focus')
    action = body.get('action')
    if action not in ('start', 'heartbeat', 'end'):
        raise StoreError('Focus action must be start, heartbeat or end.', 'invalid_focus')
    owner, lease = valid_id(body.get('ownerId')), valid_id(body.get('leaseId'))
    sequence = body.get('sequence')
    if type(sequence) is not int or sequence < 0:
        raise StoreError('Focus sequence must be a nonnegative integer.', 'invalid_focus')
    ttl = body.get('ttlSeconds', 900)
    if type(ttl) is not int or not 60 <= ttl <= 3600:
        raise StoreError('Focus ttlSeconds must be between 60 and 3600.', 'invalid_focus')
    observed = parse_time(body.get('observedAt'))
    checked = clock()
    if observed > checked + timedelta(seconds=60):
        raise StoreError('Focus observation is in the future.', 'invalid_focus')
    if 'label' in body and (not isinstance(body['label'], str) or len(body['label']) > 200):
        raise StoreError('Focus label must be at most 200 characters.', 'invalid_focus')
    if 'nodeIds' in body and (not isinstance(body['nodeIds'], list) or len(body['nodeIds']) > 100 or
                              any(not isinstance(key, str) for key in body['nodeIds'])):
        raise StoreError('Focus nodeIds must be an array of at most 100 node IDs.', 'invalid_focus')
    fingerprint = hashlib.sha256(canonical(body).encode()).hexdigest()
    with store._transaction(write=True) as db:
        project = _project(db, project_id)
        row = db.execute('SELECT * FROM work_sessions WHERE project_id=? AND owner_id=? AND lease_id=?',
                         (project_id, owner, lease)).fetchone()
        if row is not None:
            if sequence == row['sequence']:
                if fingerprint != row['fingerprint']:
                    raise StoreError('Focus sequence was already used for different content.', 'focus_conflict', 409)
                return {'projectId': project_id, 'checkedAt': stamp(checked), 'session': _session(row, project, checked)}
            if sequence < row['sequence']:
                raise StoreError('Focus sequence is older than the stored observation.', 'stale_focus', 409)
            if row['ended']:
                raise StoreError('This focus lease has ended; start a new lease.', 'focus_ended', 409)
            if action == 'start':
                raise StoreError('Use heartbeat to update an existing focus lease.', 'focus_conflict', 409)
            if observed < parse_time(row['last_seen_at']):
                raise StoreError('Focus observation is older than the stored observation.', 'stale_focus', 409)
        elif action == 'heartbeat':
            raise StoreError('Focus lease not found.', 'not_found', 404)
        elif action == 'start':
            latest = db.execute('SELECT * FROM work_sessions WHERE project_id=? AND owner_id=? '
                                'ORDER BY started_at DESC LIMIT 1', (project_id, owner)).fetchone()
            if latest and observed <= parse_time(latest['started_at']):
                raise StoreError('A newer focus lease already exists.', 'stale_focus', 409)
        aliases = project.get('nodeAliases', {})
        existing = {node['id'] for node in project['nodes']}
        node_ids = body.get('nodeIds', json.loads(row['node_ids']) if row else [])
        node_ids = list(dict.fromkeys(aliases.get(key, key) for key in node_ids))
        # End must still work after focused nodes were deleted. A heartbeat with
        # no explicit replacement drops deleted references instead of blocking cleanup.
        if action != 'end' and 'nodeIds' in body and any(key not in existing for key in node_ids):
            raise StoreError('Focused nodes must exist in this experiment.', 'invalid_reference')
        node_ids = [key for key in node_ids if key in existing]
        label = body.get('label', row['label'] if row else '')
        started = row['started_at'] if row else stamp(observed)
        revision = row['revision'] + 1 if row else 1
        if action == 'start':
            db.execute('UPDATE work_sessions SET ended=1, revision=revision+1 '
                       'WHERE project_id=? AND owner_id=? AND ended=0', (project_id, owner))
        db.execute('INSERT INTO work_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?) '
                   'ON CONFLICT(project_id,owner_id,lease_id) DO UPDATE SET '
                   'last_seen_at=excluded.last_seen_at, expires_at=excluded.expires_at, ended=excluded.ended, '
                   'sequence=excluded.sequence, fingerprint=excluded.fingerprint, label=excluded.label, '
                   'node_ids=excluded.node_ids, revision=excluded.revision',
                   (project_id, owner, lease, started, stamp(observed), stamp(observed + timedelta(seconds=ttl)),
                    int(action == 'end'), sequence, fingerprint, label, canonical(node_ids), revision))
        row = db.execute('SELECT * FROM work_sessions WHERE project_id=? AND owner_id=? AND lease_id=?',
                         (project_id, owner, lease)).fetchone()
        return {'projectId': project_id, 'checkedAt': stamp(checked), 'session': _session(row, project, checked)}
