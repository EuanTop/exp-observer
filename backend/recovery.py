"""Recover registered local capture queues without executing research commands."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import threading


def load_client():
    # Load the application's own portable client, never a script from a registry entry.
    path = Path(__file__).resolve().parents[1] / 'skills' / 'exp-observer' / 'scripts' / 'exp_observer.py'
    spec = importlib.util.spec_from_file_location('_exp_observer_recovery_client', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Recovery:
    def __init__(self, url, state_dir=None, interval=2):
        self.cli = load_client()
        self.url = url.rstrip('/')
        self.origin = self.cli.loopback_origin(self.url)
        self.state_dir = Path(state_dir) if state_dir is not None else self.cli.state_directory()
        self.interval = interval
        self.stopped = threading.Event()
        self.thread = None
        self.last_results = []
        self.acknowledged = {}

    def drain_once(self):
        results = []
        if self.origin is None:
            return results
        for registration in sorted((self.state_dir / 'outboxes').glob('*.json')):
            if self.stopped.is_set():
                break
            try:
                entry = json.loads(registration.read_text(encoding='utf-8'))
                if not isinstance(entry, dict):
                    raise ValueError('Recovery registration must be an object.')
                if entry.get('version') != 1 or self.cli.loopback_origin(entry['url']) != self.origin:
                    continue
                outbox = Path(entry['outbox'])
                if not outbox.is_absolute() or not outbox.is_dir():
                    continue
                # localhost is an alias of this bound IPv4 service. Connect directly
                # to our own origin while retaining the queue's original URL identity.
                client = self.cli.Client(entry['url'], timeout=1, transport_url=self.url, local_only=True)
                results.extend(self.cli.drain_outbox(client, outbox, stop_event=self.stopped, acknowledged=self.acknowledged))
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                results.append({'registryEntry': registration.name, 'pending': True, 'recordingWarnings': [str(exc)]})
        self.last_results = results
        return results

    def _run(self):
        while not self.stopped.is_set():
            try:
                self.drain_once()
            except Exception as exc:
                # Recovery failure must never take down the application or its HTTP service.
                self.last_results = [{'pending': True, 'recordingWarnings': [str(exc)]}]
            self.stopped.wait(self.interval)

    def start(self):
        if self.origin is not None and self.thread is None:
            self.thread = threading.Thread(target=self._run, name='ExpObserver recovery', daemon=True)
            self.thread.start()
        return self

    def stop(self):
        self.stopped.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)