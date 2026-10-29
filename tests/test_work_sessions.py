"""Conversation focus leases do not change scientific records or execute work."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.server import Server
from backend.store import Store, StoreError
from backend import work_sessions as focus


class WorkSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root)
        self.store.create_project({'id': 'study', 'name': 'Study'})
        self.store.create_project({'id': 'other', 'name': 'Other'})
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'n', 'title': 'Question'}}]})
        self.when = datetime(2026, 10, 29, 1, tzinfo=timezone.utc)
        patched = patch.object(focus, 'clock', side_effect=lambda: self.when)
        patched.start()
        self.addCleanup(patched.stop)

    def body(self, owner='owner-a', lease='lease-a', sequence=0, action='start', **extra):
        return {'ownerId': owner, 'leaseId': lease, 'sequence': sequence, 'action': action,
                'observedAt': focus.stamp(self.when), **extra}

    def change(self, **kwargs):
        return focus.update(self.store, 'study', self.body(**kwargs))['session']

    def code(self, code, body, project='study'):
        with self.assertRaises(StoreError) as caught:
            focus.update(self.store, project, body)
        self.assertEqual(caught.exception.code, code)

    def test_multiple_conversations_durable_without_history_churn(self):
        before = self.store.get_project('study')
        history = self.store.history('study')
        with ThreadPoolExecutor(2) as executor:
            list(executor.map(lambda pair: self.change(owner=pair[0], lease=pair[1], nodeIds=['n']),
                              [('a', 'a'), ('b', 'b')]))
        reloaded = Store(self.root)
        sessions = focus.get(reloaded, 'study')['sessions']
        self.assertEqual({item['ownerId'] for item in sessions}, {'a', 'b'})
        self.assertTrue(all(item['state'] == 'active' for item in sessions))
        self.assertEqual(self.store.get_project('study'), before)
        self.assertEqual(self.store.history('study'), history)
        focus.update(self.store, 'other', self.body(owner='a', lease='a'))
        self.assertEqual(len(focus.get(self.store, 'other')['sessions']), 1)

    def test_sequence_retry_conflict_and_ended_tombstone(self):
        body = self.body(nodeIds=['n'])
        first = focus.update(self.store, 'study', body)
        self.assertEqual(focus.update(self.store, 'study', body), first)
        self.code('focus_conflict', body | {'nodeIds': []})
        self.when += timedelta(seconds=1)
        self.change(sequence=2, action='heartbeat')
        self.code('stale_focus', self.body(sequence=1, action='heartbeat'))
        ended = self.body(sequence=3, action='end')
        self.assertEqual(focus.update(self.store, 'study', ended)['session']['state'], 'ended')
        self.assertEqual(focus.update(self.store, 'study', ended)['session']['state'], 'ended')
        self.code('focus_ended', self.body(sequence=4, action='heartbeat'))
        self.assertEqual(focus.get(Store(self.root), 'study')['sessions'][0]['state'], 'ended')

    def test_new_lease_supersedes_only_its_owner_and_old_messages_cannot_end_it(self):
        old = self.body(nodeIds=['n'])
        focus.update(self.store, 'study', old)
        self.change(owner='b', lease='b')
        self.when += timedelta(seconds=1)
        self.change(lease='new')
        self.code('focus_ended', self.body(sequence=1, action='end'))
        self.code('focus_ended', self.body(sequence=2, action='heartbeat'))
        self.code('stale_focus', old | {'leaseId': 'delayed-old-start'})
        states = {item['leaseId']: item['state'] for item in focus.get(self.store, 'study')['sessions']}
        self.assertEqual(states, {'new': 'active', 'lease-a': 'ended', 'b': 'active'})

    def test_delayed_observation_does_not_renew_at_receive_time(self):
        delayed = self.body(ttlSeconds=60)
        self.when += timedelta(seconds=61)
        session = focus.update(self.store, 'study', delayed)['session']
        self.assertEqual(session['state'], 'stale')
        heartbeat = self.body(sequence=1, action='heartbeat', ttlSeconds=60)
        self.when += timedelta(seconds=61)
        self.assertEqual(focus.update(self.store, 'study', heartbeat)['session']['state'], 'stale')
        self.code('invalid_focus', self.body(owner='future', observedAt=focus.stamp(self.when + timedelta(minutes=2))))
        self.code('stale_focus', heartbeat | {'sequence': 2, 'observedAt': delayed['observedAt']})

    def test_node_validation_aliases_deletion_and_project_isolation(self):
        self.code('invalid_reference', self.body(nodeIds=['missing']))
        self.code('invalid_reference', self.body(nodeIds=['n']), project='other')
        self.change(nodeIds=['n'])
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {'id': 'replacement'}},
                                                  {'op': 'node.merge', 'data': {'id': 'n', 'target': 'replacement'}}]})
        self.assertEqual(focus.get(self.store, 'study')['sessions'][0]['nodeIds'], ['replacement'])
        self.store.batch('study', {'operations': [{'op': 'node.delete', 'data': {'id': 'replacement'}}]})
        self.assertEqual(focus.get(self.store, 'study')['sessions'][0]['nodeIds'], [])
        self.assertEqual(self.change(action='end', sequence=1)['state'], 'ended')
        for change in ({'sequence': True}, {'ttlSeconds': 59}, {'ttlSeconds': 3601}, {'nodeIds': 'n'}, {'label': 1}):
            self.code('invalid_focus', self.body(**change))

    def test_unknown_end_tombstone_prevents_delayed_start_without_ending_other_work(self):
        self.change(lease='current', nodeIds=['n'])
        before = self.store.get_project('study')
        ended = self.body(lease='offline', action='end', sequence=5, nodeIds=['not-yet-created'])
        result = focus.update(self.store, 'study', ended)
        self.assertEqual(result['session']['state'], 'ended')
        self.assertEqual(result['session']['nodeIds'], [])
        self.assertEqual(focus.update(self.store, 'study', ended), result)
        self.code('stale_focus', self.body(lease='offline', sequence=0))
        self.code('focus_ended', self.body(lease='offline', sequence=6))
        self.code('focus_ended', self.body(lease='offline', action='heartbeat', sequence=7))
        sessions = {item['leaseId']: item for item in focus.get(Store(self.root), 'study')['sessions']}
        self.assertEqual(sessions['current']['state'], 'active')
        self.assertEqual(sessions['current']['nodeIds'], ['n'])
        self.assertEqual(self.store.get_project('study'), before)

    def test_focus_reads_only_metadata_and_node_ids(self):
        self.change(nodeIds=['n'])
        with patch.object(self.store, '_load', side_effect=AssertionError('Focus must not load full project')):
            self.assertEqual(focus.get(self.store, 'study')['sessions'][0]['nodeIds'], ['n'])
            self.change(action='heartbeat', sequence=1, nodeIds=['n'])

    def test_http_contract_and_origin_security(self):
        server = Server(('127.0.0.1', 0), self.store)
        self.addCleanup(server.server_close)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/api/projects/study/focus'
        data = json.dumps(self.body(nodeIds=['n'])).encode()
        with urlopen(Request(url, data=data, headers={'Content-Type': 'application/json'})) as result:
            self.assertEqual(json.load(result)['session']['nodeIds'], ['n'])
        with urlopen(url) as result:
            self.assertEqual(json.load(result)['sessions'][0]['state'], 'active')
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(url, data=data, headers={'Origin': 'https://evil.example'}))
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        with self.assertRaises(HTTPError) as caught:
            urlopen(url.replace('/study/', '/missing/'))
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()
