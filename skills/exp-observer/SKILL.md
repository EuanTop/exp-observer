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

Keep the returned ID across conversations. This works offline; `event --project ID` can also prepare a missing project without `init`.

## Record at natural boundaries

Use `event` to retain actual research changes in the research's own wording. The client manages identities and references; no node numbering or predetermined script-to-finding mapping is needed.

```sh
python3 <skill>/scripts/exp_observer.py event --project ID --question "What affects confirmation time?" --finding "Navigation backtracking offsets part of the gain"
```

`--question` alone opens a meaningful question as active; optional `--reason` explains why it matters. Its exact title or a retained ID reuses that question, including across ancestor queues and retained context. Titles are not matched approximately. Findings need no prior opening call: the same invocation can retain both a new question and its first finding.

Use `--finding`, `--correction` or `--direction` for a substantive discovery, corrected judgment or changed direction. Each is a separate ordinary node linked to the stated question; earlier findings remain intact. `--after "Earlier finding title"` relates a change to a retained finding, defaulting to `revises` for a correction, `leads_to` for a direction or `related_to` for a finding; `--relation supports` can explicitly state support. No causal relationships are inferred from prose or recording order.

Retain different discoveries even when one script produced them. Repeat measurements of the same question reuse its identity; routine steps need no event. Use `event --question "Exact question" --status completed` or `paused` for actual question status. Do not invent stages, fill a node quota or create completion-only findings.

## Keep analysis in the experiment

When using Observer, the default home for conclusions and analysis is the platform's native `summary`, `conclusion` and `notes` fields. Do not also create `REPORT.md`, a summary-style README or a separate conclusion report unless the user explicitly asks for that document. Scripts, original data and images remain local evidence.

Use `event --notes TEXT` for full reasoning, comparisons and limitations. `--notes-file PATH` loads existing UTF-8 analysis verbatim; `--notes-file -` reads stdin. Notes belong to the supplied change, or to the question when no change is supplied. They supplement the visible finding rather than hiding distinct discoveries in a shared script node. Omitted notes preserve existing notes.

Attach existing JSON with `--metrics-file results.json --artifact results.json`. Nested values are preserved; other root types use `result`. Files stay unchanged.

For an existing command you want captured:

```sh
python3 <skill>/scripts/exp_observer.py execute --project ID --title "Actual command" -- python3 experiment.py
```

This captures timing, exit code and stdout/stderr independently of future findings. Add `--artifact PATH` for results. `event --evidence "Actual command"` links an actual finding to that captured evidence; several findings can reuse it. For repeated measurements, `execute --question "Exact question" --title "Actual measurement" -- COMMAND...` retains another run of the same question. Never rerun work just to split its findings.

The older `record` entry remains available for direct edits. Its `--node` option replaces supplied fields on that node; use `event` for a new finding or correction.

## Let recording recover separately

Call the client even offline: result files alone do not queue records. `init`, `event`, `record` and `execute` save locally; the application reads connected research directories, including new experiment subdirectories. No global-directory write is needed. Pending means saved locally, awaiting registration. Continue without polling.

The command's exit status describes the experiment; `pending` and `recordingWarnings` describe recording. If the host blocks client execution or local saving fails, continue and report recording unavailable; do not claim it was queued.

A workspace network denial is an expected local-queue mode. Do not request a sandbox exception, relax permissions or retry network access just to register observations. Continue the research and use the final local receipt to describe delivery.

Recovery never reruns experiments or rereads changed source evidence. Do not reformat outputs, repeat experiments or diagnose the platform merely to complete a record. Manual `sync` is optional recovery.

Before your final brief result, call `status --project ID` once from the research working directory. It reads current local queue receipts without HTTP or polling. Background recovery may have replaced an earlier pending receipt with `synced`; use this latest `deliveryState`, not an old `pending` response, when describing registration. Say registered for `synced`, or saved locally awaiting background reception for `pending`. This does not test HTTP reachability: a past client connection error is not evidence that the service is down, and historical warnings do not make an acknowledged record pending. Respect the reported local scope; unknown or partial status does not confirm registration. A synced receipt confirms registration rather than scientific success.

Label synthetic data honestly and leave unavailable usage counters unknown.

The [record reference](references/records.md) covers native analysis, optional edits, assessments and evidence reads.
