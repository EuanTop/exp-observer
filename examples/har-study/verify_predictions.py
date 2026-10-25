#!/usr/bin/env python3
"""Recompute the published HAR test scores from retained predictions; no ML packages needed."""
from __future__ import annotations

from collections import defaultdict
import csv
import json
import math
from pathlib import Path


def verify(root=None):
    root = Path(root or Path(__file__).parent)
    metrics = json.loads((root / 'evidence/final-metrics.json').read_text(encoding='utf-8'))
    rows = defaultdict(dict)
    with (root / 'evidence/test-predictions.csv').open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            key = int(row['row'])
            model = row['model']
            if key in rows[model]:
                raise ValueError(f'Duplicate test row: {model}/{key}')
            rows[model][key] = (int(row['subject']), int(row['y']), int(row['pred']))
    if set(rows) != set(metrics['models']):
        raise ValueError('Prediction models do not match the published results.')
    reference = None
    results = {}
    for model, predictions in rows.items():
        if set(predictions) != set(range(metrics['test_n'])):
            raise ValueError(f'Missing or unexpected test rows: {model}')
        truth = {key: value[:2] for key, value in predictions.items()}
        if reference is not None and truth != reference:
            raise ValueError('Models were evaluated on different test labels or participants.')
        reference = truth
        confusion = [[0] * 6 for _ in range(6)]
        for _, actual, predicted in predictions.values():
            if actual not in range(1, 7) or predicted not in range(1, 7):
                raise ValueError('Unexpected activity label.')
            confusion[actual - 1][predicted - 1] += 1
        accuracy = sum(confusion[i][i] for i in range(6)) / len(predictions)
        f1 = sum(2 * confusion[i][i] / (sum(confusion[i]) + sum(row[i] for row in confusion)) for i in range(6)) / 6
        published = metrics['models'][model]
        if confusion != published['confusion'] or not math.isclose(accuracy, published['accuracy'], abs_tol=1e-12) or not math.isclose(f1, published['macro_f1'], abs_tol=1e-12):
            raise ValueError(f'Recomputed scores differ from published results: {model}')
        results[model] = {'accuracy': accuracy, 'macro_f1': f1, 'test_rows': len(predictions)}
    return results


if __name__ == '__main__':
    for name, result in verify().items():
        print(f'{name}: accuracy {result["accuracy"]:.4%}, macro-F1 {result["macro_f1"]:.4%} ({result["test_rows"]} retained predictions)')
