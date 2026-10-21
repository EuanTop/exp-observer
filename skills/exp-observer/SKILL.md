---
name: exp-observer
description: Observe research in a local ExpObserver experiment with brief updates, original results and retained evidence. Use when asked to track or resume an experiment. Recording supports the user's work and does not prescribe the research process.
---

# ExpObserver

Work on the user's research task with their objective, methods, budget and deliverables. ExpObserver records that work. Choose research directions from the task and evidence; the platform adds no experimental phases, required measurements or scientific review steps.

Use `scripts/exp_observer.py` relative to this Skill with Python 3.10+. Examples use `python3`; on Windows use `py -3` or the installed interpreter. The default address is `http://127.0.0.1:4317`; `EXP_OBSERVER_URL` or global `--url URL` selects another server.

## Read just enough to resume

Use `context --project ID` once when joining an experiment, or `context --project ID --node NODE` for a particular branch. Use `projects` if its ID is unknown. Experiments persist across conversations; each operation names its project explicitly.

## Record at natural boundaries

When the research already produces a result, changes direction or reaches a decision, leave a brief data update. Reuse the relevant record when convenient. Take its title and optional summary from facts already established. Recording is optional for routine intermediate steps.

```sh
python3 <skill>/scripts/exp_observer.py record --project ID --title "Observed result" --summary "Evidence and implication" --metrics-file results.json --artifact results.json
```

`record` supplies IDs and run/evidence references. `--node NODE` updates an existing record; `--after NODE` records an actual research continuation; `--parent NODE` groups related records. Omit options you do not need. Use `--status completed` when that work is complete. The client handles retry bookkeeping.

Pass original JSON results, including nested objects, arrays, nulls and booleans. Object roots are stored directly; other roots are stored under `result`. Experimental output files remain unchanged.

For an existing command you want captured:

```sh
python3 <skill>/scripts/exp_observer.py execute --project ID --node NODE --title "Actual command" --artifact results.json -- python3 experiment.py
```

This captures command timing, exit code, stdout/stderr and requested files without extra model calls. Select commands from the research task. Optional step timers and actual host token counters are available in the reference when useful; measuring them is not a condition for continuing research.

## Let recording recover separately

`record` and `execute` preserve pending records and staged evidence under `.exp-observer-runs/outbox` when registration fails. The command's exit status describes the experiment; `recordingWarnings` and `pending` describe recording. At a convenient boundary, use:

```sh
python3 <skill>/scripts/exp_observer.py sync
```

Sync retries registration with stable identities and captured bytes; it never reruns the experiment. Continue the research while a recording issue is pending and mention it briefly when relevant. Avoid reformatting experimental outputs, repeating experiments or diagnosing the observation platform merely to complete a record.

Keep observations factual. Attach existing evidence when available, label synthetic data honestly, and leave unavailable usage counters unknown. Follow the user's requested deliverables.

The [record reference](references/records.md) covers optional low-level edits, assessment revisions, timers and evidence reads. Use it only when those operations are needed.
