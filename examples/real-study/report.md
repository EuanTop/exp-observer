# Exact search: query speed and index lifetime

This example shows how a research decision can change without rerunning an experiment. An agent compared three local exact-search implementations, retained their outputs, and revised its initial choice after considering index construction. A second agent later continued the same experiment from its recorded evidence.

The repository includes the reproducible script and these reports. Generated measurements and the original workspace are kept separately from source control.

## Reproduce the study

From this directory, using Python 3.10+ with SQLite FTS5 enabled:

```sh
python3 study.py fixture
python3 study.py linear
python3 study.py inverted
python3 study.py fts5
```

`fixture` generates deterministic input. Each implementation writes a result JSON, a per-query latency CSV and an output JSON in this directory. These generated files are ignored by Git. New timings will depend on the machine and load.

To record a new investigation in ExpObserver, create a project and candidate nodes through the [Skill](../../skills/exp-observer/SKILL.md), run these commands with `execute`, and retain the resulting files using `--artifact` or bulk `artifact` registration.

## Recorded observations

![Recorded comparison of Python inverted-index and SQLite FTS5 runs in the application](../../docs/screenshots/comparison.png)

*The comparison view shows recorded measurements and their assessments.*

| Implementation | Fresh build median, ms (3 samples) | 48-query batch median, ms (5 batches) | One explicit update, ms |
|---|---:|---:|---:|
| Repeated linear scan | 0.446 | 798.352 | 0.021 |
| Python inverted index | 79.392 | 0.501 | 0.088 |
| SQLite FTS5 | 20.386 | 2.593 | 0.305 |

The original run checked 720 initial queries and 144 queries after updates against a stored reference. All equality assertions passed. Output files retain the final initial batch and the updated batch: 288 answer lists across the three implementations. Earlier batches retain timings and assertion outcomes rather than separate full answer archives.

The inverted index had the fastest queries. For a short-lived index, construction changed the choice: the model **build median + five batch medians** gave 33.353 ms for FTS5 and 81.898 ms for the inverted index. The revised decision retained FTS5 for that finite workload, kept the inverted index as the long-lived-query candidate, and retained the linear scan as a correctness reference.

Those totals combine existing measurements; they are not an independently measured end-to-end run. The estimated crossover of about 28.2 batches is workload-specific. The [continuation review](continuation-review.md) further limits its interpretation.

## Input and measurement boundaries

The fixed seed is `20261020`. The corpus contains 6,000 documents, each with 36 sampled terms from an 800-term vocabulary, plus some shared terms and mixed letter case. The 48 queries cover one-to-three-term AND matching, repeated terms, case differences, absent terms and an update-specific term.

The supported semantics are exact whole-token AND matching over ASCII alphanumeric terms separated by whitespace, returning sorted document IDs. The stored reference uses prepared token sets. Python candidates use case folding and whitespace splitting; FTS5 uses an ASCII tokenizer and explicit AND queries. The subsequent reviewer independently checked normalization on the retained input.

Build samples create three independent fresh instances. A fourth instance performs five batches in fixed order. Query batches include matching, answer materialization and sorting; they exclude fixture reading, construction and reference validation. SQLite uses an in-memory database. There is no explicit query warm-up, so “warm” fields in the output mean the index was already constructed.

## Updates and interpretation

The update deletes two documents, replaces one and inserts twenty. Before explicit propagation, each implementation's old snapshot differs from the updated reference on three queries. After applying updates, all implementations agree on all 48 queries. This is snapshot behavior, not an algorithm failure.

The study covers one machine, one fixed corpus and query order, three build samples and five query batches. It does not establish confidence intervals, persistent-storage cost, memory use, Unicode tokenization or a universal speedup. The simple linear baseline deliberately re-tokenizes documents on each query.

## What the graph records

The graph preserves candidate branches, execution evidence, an initial query-speed decision, a critical cost-review finding and the revised decision. Re-evaluation uses the same underlying runs. Independent continuation adds its review and a proposed warm-up/lifecycle branch, preserving earlier interpretations.
