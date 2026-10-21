#!/usr/bin/env python3
"""Deterministic exact AND search study. Python stdlib only; real timings."""
import argparse
import csv
import hashlib
import json
import platform
import random
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPEATS = 5
BUILDS = 3


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def tokens(text):
    return set(text.casefold().split())


def reference(docs, queries):
    prepared = [(d['id'], tokens(d['text'])) for d in docs]
    return [sorted(i for i, ts in prepared if tokens(q) <= ts) for q in queries]


def updated(docs, change):
    result = {d['id']: d for d in docs}
    for i in change['delete']:
        result.pop(i)
    for d in change['upsert']:
        result[d['id']] = d
    return list(result.values())


def fixture():
    rng = random.Random(20261020)
    vocab = [f'term{i:04d}' for i in range(800)]
    docs = []
    for i in range(6000):
        words = [rng.choice(vocab) for _ in range(36)]
        if i % 2 == 0:
            words.append('shared')
        words = [w.upper() if rng.random() < .3 else w for w in words]
        docs.append({'id': i, 'text': ' '.join(words)})
    queries = ['shared', 'UNIQUEUPDATE', 'unknownterm', 'term0000 TERM0000']
    for _ in range(44):
        words = rng.sample(vocab, rng.choice([1, 2, 3]))
        queries.append(' '.join(w.upper() if rng.random() < .5 else w for w in words))
    change = {'delete': [1, 2], 'upsert': [{'id': 0, 'text': 'uniqueupdate term0000 SHARED'}] + [
        {'id': 6000 + i, 'text': f'UNIQUEUPDATE shared term{i:04d}'} for i in range(20)]}
    payload = {'seed': 20261020, 'documents': docs, 'queries': queries, 'update': change,
               'expected': reference(docs, queries), 'expectedUpdated': reference(updated(docs, change), queries)}
    save('fixture.json', payload)
    print(json.dumps({'documents': len(docs), 'queries': len(queries), 'updatedDocuments': len(updated(docs, change)),
                      'sha256': hashlib.sha256((ROOT / 'fixture.json').read_bytes()).hexdigest()}))


class Linear:
    def __init__(self, docs):
        self.docs = {d['id']: d['text'] for d in docs}

    def search(self, query):
        required = tokens(query)
        return sorted(i for i, text in self.docs.items() if required <= tokens(text))

    def update(self, change):
        for i in change['delete']:
            self.docs.pop(i)
        for d in change['upsert']:
            self.docs[d['id']] = d['text']

    def close(self):
        pass


class Inverted:
    def __init__(self, docs):
        self.docs, self.postings = {}, {}
        for d in docs:
            self.add(d)

    def add(self, d):
        ts = tokens(d['text'])
        self.docs[d['id']] = ts
        for term in ts:
            self.postings.setdefault(term, set()).add(d['id'])

    def search(self, query):
        lists = sorted((self.postings.get(t, set()) for t in tokens(query)), key=len)
        return sorted(set.intersection(*lists)) if lists else []

    def update(self, change):
        for i in set(change['delete']) | {d['id'] for d in change['upsert']}:
            for term in self.docs.pop(i, set()):
                self.postings[term].discard(i)
        for d in change['upsert']:
            self.add(d)

    def close(self):
        pass


class FTS:
    def __init__(self, docs):
        self.db = sqlite3.connect(':memory:')
        self.db.execute("CREATE VIRTUAL TABLE documents USING fts5(text, tokenize='ascii')")
        self.db.executemany('INSERT INTO documents(rowid,text) VALUES(?,?)', [(d['id'] + 1, d['text']) for d in docs])
        self.db.commit()

    def search(self, query):
        expression = ' AND '.join('"' + t.replace('"', '""') + '"' for t in sorted(tokens(query)))
        return [row[0] - 1 for row in self.db.execute('SELECT rowid FROM documents WHERE documents MATCH ? ORDER BY rowid', (expression,))]

    def update(self, change):
        with self.db:
            for i in set(change['delete']) | {d['id'] for d in change['upsert']}:
                self.db.execute('DELETE FROM documents WHERE rowid=?', (i + 1,))
            self.db.executemany('INSERT INTO documents(rowid,text) VALUES(?,?)', [(d['id'] + 1, d['text']) for d in change['upsert']])

    def close(self):
        self.db.close()


def measure(algorithm):
    raw = (ROOT / 'fixture.json').read_bytes()
    f = json.loads(raw)
    cls = {'linear': Linear, 'inverted': Inverted, 'fts5': FTS}[algorithm]
    cpu_start = time.process_time()
    builds = []
    for _ in range(BUILDS):
        start = time.perf_counter_ns()
        candidate = cls(f['documents'])
        builds.append((time.perf_counter_ns() - start) / 1e6)
        candidate.close()
    index = cls(f['documents'])
    batches, per_query, outputs = [], [], None
    for repeat in range(REPEATS):
        start = time.perf_counter_ns()
        answers = []
        for query in f['queries']:
            qstart = time.perf_counter_ns()
            answers.append(index.search(query))
            per_query.append({'repeat': repeat, 'query': query, 'latency_ms': (time.perf_counter_ns() - qstart) / 1e6})
        batches.append((time.perf_counter_ns() - start) / 1e6)
        assert answers == f['expected'], f'{algorithm}: inconsistent initial query outputs'
        outputs = answers
    stale = [index.search(q) for q in f['queries']]
    stale_mismatches = [i for i, (a,b) in enumerate(zip(stale, f['expectedUpdated'])) if a != b]
    start = time.perf_counter_ns()
    index.update(f['update'])
    update_ms = (time.perf_counter_ns() - start) / 1e6
    start = time.perf_counter_ns()
    after = [index.search(q) for q in f['queries']]
    after_batch_ms = (time.perf_counter_ns() - start) / 1e6
    assert after == f['expectedUpdated'], f'{algorithm}: inconsistent updated query outputs'
    index.close()
    result = {'algorithm': algorithm, 'fixtureSha256': hashlib.sha256(raw).hexdigest(),
              'environment': {'python': sys.version, 'sqlite': sqlite3.sqlite_version, 'platform': platform.platform()},
              'documentCount': len(f['documents']), 'queryCount': len(f['queries']), 'repeats': REPEATS,
              'buildSamplesMs': builds, 'buildMedianMs': statistics.median(builds),
              'warmBatchSamplesMs': batches, 'warmBatchMedianMs': statistics.median(batches),
              'warmMeanQueryMs': statistics.mean(batches)/len(f['queries']),
              'initialConsistent': True, 'initialOutputSha256': hashlib.sha256(json.dumps(outputs).encode()).hexdigest(),
              'staleQueriesDifferingFromUpdatedCorpus': stale_mismatches,
              'updateMs': update_ms, 'updatedBatchMs': after_batch_ms, 'updatedConsistent': True,
              'updatedOutputSha256': hashlib.sha256(json.dumps(after).encode()).hexdigest(),
              'cpuSeconds': time.process_time() - cpu_start,
              'definitions': {'build': 'fresh in-memory instance, ingest all 6000 documents; no fixture read or result verification',
                              'warmBatch': '48 queries on one fully built instance; includes matching, materialization and sorting',
                              'update': '2 deletes + 1 replacement + 20 inserts on the retained instance; SQLite commit included',
                              'semantics': 'casefold, whitespace-delimited whole ASCII alphanumeric tokens, set AND; sorted document IDs',
                              'stale': 'old snapshot compared with updated corpus truth before explicit propagation; not algorithm failure'}}
    save(f'{algorithm}.json', result)
    save(f'{algorithm}-outputs.json', {'initial': outputs, 'updated': after})
    with (ROOT / f'{algorithm}-latency.csv').open('w', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=['repeat', 'query', 'latency_ms'])
        writer.writeheader()
        writer.writerows(per_query)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['fixture', 'linear', 'inverted', 'fts5'])
    args = parser.parse_args()
    fixture() if args.mode == 'fixture' else measure(args.mode)
