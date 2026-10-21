#!/usr/bin/env python3
"""Measure local recording overhead in a disposable experiment; no model calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.server import Server  # noqa: E402
from backend.store import Store  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='gtrack-overhead-') as folder:
        store = Store(Path(folder) / 'data')
        store.create_project({'id': 'measurement', 'name': 'Disposable overhead measurement'})
        store.batch('measurement', {'operations': [{'op': 'node.add', 'data': {
            'id': 'capture', 'title': 'Capture', 'kind': 'experiment', 'status': 'active',
            'parentId': None, 'position': {'x': 0, 'y': 0}, 'summary': '', 'notes': '',
            'nextAction': '', 'tags': [], 'collapsed': False}}]})
        server = Server(('127.0.0.1', 0), store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        command = [sys.executable, '-c', 'print("retained output")']
        wrapped = [sys.executable, str(ROOT / 'skills/research-trail/scripts/research_trail.py'), '--url', url,
                   'execute', '--project', 'measurement', '--node', 'capture', '--title',
                   'Measured capture', '--', *command]
        results = {'directMs': [], 'recordedMs': []}
        try:
            for _ in range(7):
                for key, argv in [('directMs', command), ('recordedMs', wrapped)]:
                    started = time.perf_counter()
                    subprocess.run(argv, cwd=folder, check=True, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE)
                    results[key].append(round((time.perf_counter() - started) * 1000, 3))
            project = store.get_project('measurement')
            summary = {
                'scope': 'Seven interleaved local subprocess trials; disposable small project; Python print command.',
                'modelCallsForRecording': 0,
                'samples': results,
                'medianDirectMs': round(statistics.median(results['directMs']), 3),
                'medianRecordedMs': round(statistics.median(results['recordedMs']), 3),
                'runsRetained': len(project['runs']),
                'artifactsRetained': len(project['artifacts']),
                'finalRevision': project['revision'],
            }
            summary['medianDeltaMs'] = round(summary['medianRecordedMs'] - summary['medianDirectMs'], 3)
            text = json.dumps(summary, ensure_ascii=False, indent=2) + '\n'
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text, encoding='utf-8')
            print(text, end='')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
