"""Recover registered local capture queues without executing research commands."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from collections import defaultdict, deque
import stat
import threading
import time

SKIP_DIRECTORIES = {'.git', '.hg', '.svn', '.venv', 'venv', 'node_modules', '__pycache__', '.mypy_cache',
                    '.pytest_cache', '.cache', '.tox', '.nox', '.next', '.nuxt', '.turbo', 'dist', 'build',
                    'target', 'vendor', 'site-packages', 'coverage', '.exp-observer', '.exp-observer-runs'}


def scoped_path(path, root, allow_missing=False):
    """Check components without following a child symlink or Windows junction."""
    path, root = Path(path), Path(root)
    if not path.is_absolute():
        return False
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        return False
    try:
        if root.resolve() != root:
            return False
        current = root
        for part in (None, *path.relative_to(root).parts):
            if part is not None:
                current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                return allow_missing
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                return False
        return True
    except (OSError, ValueError, RuntimeError):
        return False


class WorkspaceDiscovery:
    """Retain tree progress and budget root-change probes alongside ordinary traversal."""
    def __init__(self, root, rescan_interval):
        self.root = root
        self.rescan_interval = rescan_interval
        self.queue = deque([root])
        self.cursor = None
        self.priority_cursor = None
        self.priority_turn = False
        self.root_mtime = None
        self.root_dirty = False
        self.next_scan = 0
        self.outboxes = set()

    def probe(self, directory):
        outbox = directory / '.exp-observer-runs' / 'outbox'
        if scoped_path(outbox, self.root) and outbox.is_dir():
            self.outboxes.add(outbox)

    def refresh_root(self):
        try:
            if not scoped_path(self.root, self.root):
                return
            modified = self.root.stat().st_mtime_ns
        except OSError:
            return
        if self.root_mtime is not None and modified != self.root_mtime:
            self.root_dirty = True
        self.root_mtime = modified

    def _child(self, entry):
        if entry.name.lower() not in SKIP_DIRECTORIES and entry.is_dir(follow_symlinks=False):
            info = entry.stat(follow_symlinks=False)
            if not getattr(info, 'st_file_attributes', 0) & 0x400:
                return Path(entry.path)
        return None

    def step(self):
        if self.priority_cursor is None and self.root_dirty:
            self.root_dirty = False
            if scoped_path(self.root, self.root):
                try:
                    self.priority_cursor = os.scandir(self.root)
                    self.priority_turn = False
                except OSError:
                    pass
            return True  # Opening a priority scan consumes the same budget as a tree scan.
        if self.priority_cursor is not None and self.priority_turn:
            self.priority_turn = False
            return self._priority_step()
        self.priority_turn = True
        progressed = self._tree_step()
        if not progressed and self.priority_cursor is not None:
            self.priority_turn = False
            return self._priority_step()
        return progressed

    def _priority_step(self):
        try:
            directory = self._child(next(self.priority_cursor))
            if directory is not None:
                self.probe(directory)
        except StopIteration:
            self.priority_cursor.close()
            self.priority_cursor = None
        except OSError:
            pass
        return True

    def _tree_step(self):
        if self.cursor is None:
            if not self.queue:
                if time.monotonic() < self.next_scan:
                    return False
                self.queue.append(self.root)
            directory = self.queue.popleft()
            if not scoped_path(directory, self.root):
                return True
            self.probe(directory)
            try:
                self.cursor = os.scandir(directory)
            except OSError:
                return True
            return True
        try:
            directory = self._child(next(self.cursor))
            if directory is not None:
                self.queue.append(directory)
        except StopIteration:
            self.cursor.close()
            self.cursor = None
            if not self.queue:
                self.next_scan = time.monotonic() + self.rescan_interval
        except OSError:
            pass
        return True

    def close(self):
        if self.cursor is not None:
            self.cursor.close()
            self.cursor = None
        if self.priority_cursor is not None:
            self.priority_cursor.close()
            self.priority_cursor = None


def load_client():
    # Load the application's own portable client, never a script from a registry entry.
    path = Path(__file__).resolve().parents[1] / 'skills' / 'exp-observer' / 'scripts' / 'exp_observer.py'
    spec = importlib.util.spec_from_file_location('_exp_observer_recovery_client', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Recovery:
    def __init__(self, url, state_dir=None, interval=2, *, store=None, discovery_budget=128, discovery_interval=None):
        self.cli = load_client()
        self.url = url.rstrip('/')
        self.origin = self.cli.loopback_origin(self.url)
        try:
            self.state_dir = Path(state_dir) if state_dir is not None else self.cli.state_directory()
        except (OSError, ValueError, RuntimeError):
            self.state_dir = None
        self.store = store
        self.interval = interval
        self.discovery_budget = discovery_budget
        self.discovery_interval = discovery_interval if discovery_interval is not None else max(interval * 5, 0.2)
        self.discovery = {}
        self.discovery_cursor = 0
        self.stopped = threading.Event()
        self.thread = None
        self.last_results = []
        self.acknowledged = {}
        self.project_plans = {}

    def _targets(self, results):
        targets, active, disabled = {}, [], []
        if self.store is not None:
            try:
                configuration = self.store.recovery_workspaces()
                active = [Path(entry['path']) for entry in configuration['workspaces']]
                disabled = [Path(root) for root in configuration['disabledRoots']]
            except Exception as exc:
                results.append({'pending': True, 'recordingWarnings': [str(exc)]})
        for root in set(self.discovery) - set(active):
            self.discovery.pop(root).close()
        for root in active:
            scanner = self.discovery.setdefault(root, WorkspaceDiscovery(root, self.discovery_interval))
            scanner.refresh_root()
            scanner.probe(root)  # A root init plan must be visible before any descendant's implicit plan.
        scanners = list(self.discovery.values())
        idle = 0
        for _ in range(self.discovery_budget):
            if not scanners or self.stopped.is_set():
                break
            scanner = scanners[self.discovery_cursor % len(scanners)]
            self.discovery_cursor += 1
            idle = 0 if scanner.step() else idle + 1
            if idle >= len(scanners):
                break
        for scanner in scanners:
            for outbox in list(scanner.outboxes):
                if scoped_path(outbox, scanner.root) and outbox.is_dir():
                    previous = targets.get(outbox)
                    targets[outbox] = scanner.root if previous is None else min((previous, scanner.root), key=lambda path: len(path.parts))
                else:
                    scanner.outboxes.discard(outbox)
        registrations = []
        if self.state_dir is not None:
            try:
                registrations = sorted((self.state_dir / 'outboxes').glob('*.json'))
            except OSError as exc:
                results.append({'pending': True, 'recordingWarnings': [str(exc)]})
        for registration in registrations:
            try:
                if registration.is_symlink():
                    continue
                entry = json.loads(registration.read_text(encoding='utf-8'))
                if not isinstance(entry, dict):
                    raise ValueError('Recovery registration must be an object.')
                if entry.get('version') != 1 or self.cli.loopback_origin(entry['url']) != self.origin:
                    continue
                outbox = Path(entry['outbox'])
                covered = [root for root in active if outbox.is_relative_to(root)]
                if not covered and any(outbox.is_relative_to(root) for root in disabled):
                    continue
                root = min(covered, key=lambda path: len(path.parts)) if covered else outbox.parent.parent
                if scoped_path(outbox, root) and outbox.is_dir():
                    targets.setdefault(outbox, root)
                    # Legacy registrations can reveal a child before its ancestor
                    # has been visited by incremental discovery. Probe only that chain.
                    if covered:
                        owner = outbox.parent.parent
                        for directory in (owner, *owner.parents):
                            if not directory.is_relative_to(root):
                                break
                            ancestor = directory / '.exp-observer-runs' / 'outbox'
                            if scoped_path(ancestor, root) and ancestor.is_dir():
                                targets.setdefault(ancestor, root)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                results.append({'registryEntry': registration.name, 'pending': True, 'recordingWarnings': [str(exc)]})
        return targets

    def _read_candidates(self, targets, results):
        candidates, seen = [], set()
        for outbox, root in sorted(targets.items(), key=lambda item: (len(item[0].parts), str(item[0]))):
            try:
                paths = outbox.glob('*.json')
                for path in paths:
                    if self.stopped.is_set():
                        break
                    try:
                        info = path.lstat()
                        if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                            continue
                        seen.add(str(path))
                        signature = (info.st_mtime_ns, info.st_size, info.st_ino)
                        if self.acknowledged.get(str(path)) == signature:
                            continue
                        if not scoped_path(path, root):
                            continue
                        self.project_plans.pop(str(path), None)
                        task = self.cli.read_queue_task(path)
                        if self.cli.loopback_origin(task['url']) != self.origin:
                            continue
                        item = (path, root, task)
                        if task.get('kind') == 'project':
                            self.project_plans[str(path)] = item
                        if task['state'] == 'synced':
                            self.acknowledged[str(path)] = signature
                        else:
                            candidates.append(item)
                    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                        results.append({'task': path.name, 'pending': True, 'recordingWarnings': [str(exc)]})
            except OSError as exc:
                results.append({'outbox': str(outbox), 'pending': True, 'recordingWarnings': [str(exc)]})
        for key in set(self.project_plans) - seen:
            self.project_plans.pop(key, None)
        return candidates

    def _validate_capture(self, path, root, task):
        if task.get('kind') == 'project':
            return
        capture = Path(task['captureRoot'])
        if not capture.is_relative_to(path.parent.parent) or not scoped_path(capture, root, allow_missing=True):
            raise ValueError('Capture directory is outside the enrolled or registered outbox scope.')
        plan_path = self.cli.project_plan_path(path.parent, task['url'], task['projectId'])
        if not all(scoped_path(candidate, root, allow_missing=True) for candidate in (plan_path, plan_path.with_suffix('.lock'))):
            raise ValueError('Project plan follows a symlink or leaves the workspace scope.')
        for artifact in task['artifacts']:
            evidence = Path(artifact['path'])
            if not evidence.is_relative_to(capture) or not scoped_path(evidence, root, allow_missing=True):
                raise ValueError('Staged evidence follows a symlink or leaves the workspace scope.')

    def _submit(self, item):
        path, root, previous = item
        try:
            if not scoped_path(path, root) or not scoped_path(path.with_suffix('.lock'), root, allow_missing=True):
                raise ValueError('Queued record follows a symlink or leaves the workspace scope.')
            with self.cli.task_lock(path):
                task = self.cli.read_queue_task(path)
                if self.cli.loopback_origin(task['url']) != self.origin or task['projectId'] != previous['projectId']:
                    raise ValueError('Queued record identity changed while recovery was processing it.')
                self._validate_capture(path, root, task)
                client = self.cli.Client(task['url'], timeout=1, transport_url=self.url, local_only=True, queue_root=root)
                # The application already resolves authoritative parent plans. The
                # standalone client's optional ancestor lookup must stay in this scope.
                result = self.cli.sync_project(client, path, task) if task.get('kind') == 'project' else self.cli.sync_task(client, path, task)
                if not result['pending']:
                    self.acknowledged[str(path)] = self.cli.file_signature(path)
                    if task.get('kind') == 'project':
                        self.project_plans[str(path)] = (path, root, task)
                return result
        except (self.cli.ClientError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            return {'task': path.name, 'projectId': previous['projectId'], 'pending': True, 'recordingWarnings': [str(exc)]}

    def _authoritative_plan(self, project_id):
        plans = [item for item in self.project_plans.values() if item[2]['projectId'] == project_id]
        explicit = [item for item in plans if not item[2].get('implicit')]
        plans = explicit or plans
        ancestors = [item for item in plans if not any(other[0].parent.parent.parent != item[0].parent.parent.parent
            and item[0].parent.parent.parent.is_relative_to(other[0].parent.parent.parent) for other in plans)]
        return min(ancestors, key=lambda item: (item[2].get('preparedAt', ''), str(item[0]))) if ancestors else None

    def drain_once(self):
        results = []
        if self.origin is None:
            return results
        candidates = self._read_candidates(self._targets(results), results)
        groups = defaultdict(list)
        for item in candidates:
            groups[item[2]['projectId']].append(item)
        for project_id, items in groups.items():
            if self.stopped.is_set():
                break
            authoritative = self._authoritative_plan(project_id)
            if authoritative is not None:
                result = self._submit(authoritative)
                results.append(result)
                if result['pending']:
                    continue
            for item in sorted(items, key=lambda item: (item[2].get('kind') != 'project',
                    item[2].get('capturedAt') or item[2].get('startedAt') or item[2].get('preparedAt') or '', str(item[0]))):
                if self.stopped.is_set():
                    break
                if authoritative is not None and item[0] == authoritative[0]:
                    continue
                results.append(self._submit(item))
        self.last_results = results
        return results

    def _run(self):
        try:
            while not self.stopped.is_set():
                try:
                    self.drain_once()
                except Exception as exc:
                    self.last_results = [{'pending': True, 'recordingWarnings': [str(exc)]}]
                self.stopped.wait(self.interval)
        finally:
            for scanner in self.discovery.values():
                scanner.close()

    def start(self):
        if self.origin is not None and self.thread is None:
            self.thread = threading.Thread(target=self._run, name='ExpObserver recovery', daemon=True)
            self.thread.start()
        return self

    def stop(self):
        self.stopped.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
        elif self.thread is None:
            for scanner in self.discovery.values():
                scanner.close()