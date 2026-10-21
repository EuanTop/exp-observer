---
name: exp-observer
description: Observe research in a local ExpObserver experiment with brief updates, original results and retained evidence. Use when asked to track or resume an experiment. Recording supports the user's work and does not prescribe the research process.
---

# ExpObserver

Follow the user's research objective, budget and deliverables. Choose methods and next steps from the task and evidence. ExpObserver retains findings and existing results without prescribing research steps.

Use `scripts/exp_observer.py` relative to this Skill with Python 3.10+. Examples use `python3`; on Windows use `py -3` or the installed interpreter. The default address is `http://127.0.0.1:4317`; `EXP_OBSERVER_URL` or global `--url URL` selects another server.

## Join or begin an experiment

With an experiment ID, use `context --project ID` once. If unavailable, continue from research files and any dated cache; missing context does not mean an empty experiment. Keep the supplied ID.

For a new experiment without an ID, prepare it once:

```sh
python3 <skill>/scripts/exp_observer.py init --name "Research task"
```

Keep the returned ID across conversations. This works offline; `record --project ID` can also prepare a missing project without `init`.

## Record at natural boundaries

When the work establishes a finding, changes a judgment or reaches a decision, briefly record the facts already established. Reuse existing results and wording. Routine intermediate steps need no separate record.

```sh
python3 <skill>/scripts/exp_observer.py record --project ID --title "Observed finding" --summary "Evidence and implication"
```

`record` supplies IDs and references. Keep a distinct finding separately; use `--node NODE` to revise the same finding. A batch comparison may remain one record. `--after NODE` optionally retains an actual continuation. Use `--status completed` when that work is complete. Record count is not a target; retain only supported relationships and chronology.

For an existing JSON result, add `--metrics-file results.json --artifact results.json`. Nested objects, arrays and nulls are accepted; non-object roots use `result`. Source files stay unchanged.

For an existing command you want captured:

```sh
python3 <skill>/scripts/exp_observer.py execute --project ID --title "Actual command" -- python3 experiment.py
```

This supplies a record ID and captures timing, exit code and stdout/stderr. Add `--artifact PATH` for result files, or `--node NODE` to attach an existing record.

## Let recording recover separately

Call the client even when offline: saving result files alone does not queue a record. `init`, `record` and `execute` save pending work locally; the application automatically retries registered queues when running. A pending receipt means saved locally, awaiting registration. Continue research without polling.

The command's exit status describes the experiment; `pending` and `recordingWarnings` describe recording. If the host blocks client execution or local saving fails, continue and report recording unavailable; do not claim it was queued.

Recovery never reruns experiments or rereads changed source evidence. Do not reformat outputs, repeat experiments or diagnose the platform merely to complete a record. Manual `sync` is optional recovery.

Label synthetic data honestly and leave unavailable usage counters unknown.

The [record reference](references/records.md) covers optional edits, assessments, timing and evidence reads.
