#!/usr/bin/env python3
"""Load the portable English HAR example into a running ExpObserver."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request


def materialize(root=None):
    root = Path(root or Path(__file__).parent).resolve()
    project = json.loads((root / 'project.en.json').read_text(encoding='utf-8'))
    manifest = json.loads((root / 'provenance.json').read_text(encoding='utf-8'))
    for artifact in project['artifacts']:
        relative = artifact['path']
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or Path(relative).is_absolute():
            raise ValueError(f'Evidence must remain inside the example: {relative}')
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        expected = manifest['evidence_files'][relative]
        if digest != artifact['sha256'] or digest != expected['sha256'] or len(raw) != artifact['bytes'] or len(raw) != expected['bytes']:
            raise ValueError(f'Evidence checksum or size mismatch: {relative}')
        artifact['path'] = str(path)
    project['sourceRoots'] = [str(root)]
    return project


def metadata_only(project):
    """Evidence is registered separately so the platform retains verified copies."""
    metadata = copy.deepcopy(project)
    metadata['artifacts'] = []
    for run in metadata['runs']:
        run['artifactIds'] = []
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:4317')
    args = parser.parse_args()
    try:
        project = materialize()
        base = args.url.rstrip('/')

        def request(path, body=None):
            req = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode('utf-8'), {'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)

        existing = request('/api/projects')['projects']
        if any(item['id'] == project['id'] for item in existing):
            imported = request('/api/projects/' + project['id'])
        else:
            imported = request('/api/import', metadata_only(project))
        retained = {item['id']: item for item in imported['artifacts']}
        for artifact in project['artifacts']:
            if artifact['id'] in retained:
                item = retained[artifact['id']]
                if item['sha256'] != artifact['sha256'] or item['bytes'] != artifact['bytes']:
                    raise ValueError(f'Existing example has different evidence: {artifact["id"]}')
                continue
            request('/api/projects/' + imported['id'] + '/artifacts', artifact)
        print(f'English HAR example is ready: {imported["name"]}\nOpen {base} and select the English HAR study.')
    except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
        parser.exit(1, f'Cannot load example: {error}\nStart ExpObserver first. An interrupted import can be retried with the same command.\n')


if __name__ == '__main__':
    main()
