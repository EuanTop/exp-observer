---
name: exp-observer
description: Observe research in a local ExpObserver experiment with brief updates, original results and retained evidence. Use when asked to track or resume an experiment. Recording supports the user's work and does not prescribe the research process.
---

# ExpObserver

Follow the user's research objective, budget and deliverables. Choose methods from evidence; recording adds no research phases.

Use `scripts/exp_observer.py` relative to this Skill with Python 3.10+. Examples use `python3`; on Windows use `py -3` or the installed interpreter. The default address is `http://127.0.0.1:4317`; `EXP_OBSERVER_URL` or global `--url URL` selects another server.

## Join or begin an experiment

With an experiment ID, use `context --project ID` once. If unavailable, continue from research files and any dated cache; missing context does not mean an empty experiment. Keep the supplied ID.

For a new experiment without an ID, prepare it once:

```sh
python3 <skill>/scripts/exp_observer.py init --name "Research task"
```

Keep the returned ID across conversations. This works offline; `record --project ID` can also prepare a missing project without `init`.

## Record at natural boundaries

Briefly retain findings and changed judgments using existing results and wording. Routine steps need no separate record.

```sh
python3 <skill>/scripts/exp_observer.py record --project ID --title "Observed finding" --summary "Evidence and implication"
```

Use the finding as the title; `--conclusion TEXT` retains its precise conclusion. `--node NODE` revises existing work. Completion is `--status completed`, not a separate status-only finding. A batch comparison can remain one finding.

Record order is automatic and implies no causality. For an actual scientific relationship, use `--after "Earlier finding title" --relation supports` (or `refutes`, `revises`); exact local titles or IDs work.

Attach existing JSON with `--metrics-file results.json --artifact results.json`. Nested values are preserved; other root types use `result`. Files stay unchanged.

For an existing command you want captured:

```sh
python3 <skill>/scripts/exp_observer.py execute --project ID --title "Actual command" -- python3 experiment.py
```

This captures timing, exit code and stdout/stderr. Add `--artifact PATH` for result files or `--node NODE` for existing work. Record this command's finding against its returned `nodeId`, keeping result and execution together.

## Let recording recover separately

Call the client even offline: result files alone do not queue records. `init`, `record` and `execute` save locally; the application reads connected research directories, including new experiment subdirectories. No global-directory write is needed. Pending means saved locally, awaiting registration. Continue without polling.

The command's exit status describes the experiment; `pending` and `recordingWarnings` describe recording. If the host blocks client execution or local saving fails, continue and report recording unavailable; do not claim it was queued.

Recovery never reruns experiments or rereads changed source evidence. Do not reformat outputs, repeat experiments or diagnose the platform merely to complete a record. Manual `sync` is optional recovery.

Label synthetic data honestly and leave unavailable usage counters unknown.

The [record reference](references/records.md) covers optional edits, assessments, timing and evidence reads.
