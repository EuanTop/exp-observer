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

Use a short title for the question, work or finding. In the summary, briefly retain why the work mattered, what was tried or what changed, when known. Reuse the research's own wording; no fixed template is required. `--conclusion TEXT` retains a distinct conclusion when one exists; omitting it preserves any existing conclusion. `--kind TYPE` can identify a question, experiment, finding or decision naturally. `--node NODE` revises the same research question; completion is `--status completed`, not a separate status-only finding.

Retain substantially different research questions, findings and follow-up judgments separately, even when one script or batch produced them. Command boundaries do not define research units. Repeated measurements or added evidence for the same question can update its existing record; routine chatter needs no record. Do not invent phases or fill a node quota.

When turning to a substantially new research question, briefly retain that question and the reason for pursuing it as `active`. When evidence returns, update the same question's conclusion and actual status; mark finished work `completed` or deliberately parked work `paused` when appropriate. These are changes in the research itself, not check-ins before and after every tool call.

## Keep analysis in the experiment

When using Observer, the default home for conclusions and analysis is the platform's native `summary`, `conclusion` and `notes` fields. Do not also create `REPORT.md`, a summary-style README or a separate conclusion report unless the user explicitly asks for that document. Scripts, original data and images remain local evidence.

Use `record --notes TEXT` for full reasoning, comparisons and limitations. `--notes-file PATH` loads existing UTF-8 analysis verbatim into native node notes; `--notes-file -` reads stdin, so long analysis needs no separate report file. These options retain metadata, not an extra evidence attachment. Omitted notes preserve existing notes.

Record order is automatic and implies no causality. For an actual scientific relationship, use `--after "Earlier finding title" --relation supports` (or `refutes`, `revises`); exact local titles or IDs work.

Attach existing JSON with `--metrics-file results.json --artifact results.json`. Nested values are preserved; other root types use `result`. Files stay unchanged.

For an existing command you want captured:

```sh
python3 <skill>/scripts/exp_observer.py execute --project ID --title "Actual command" -- python3 experiment.py
```

This captures timing, exit code and stdout/stderr. Add `--artifact PATH` for result files or `--node NODE` for existing work. Update its returned `nodeId` for that same question's finding. If the command also answers distinct questions, record those separately using the existing outputs; never rerun it just to split the records.

## Let recording recover separately

Call the client even offline: result files alone do not queue records. `init`, `record` and `execute` save locally; the application reads connected research directories, including new experiment subdirectories. No global-directory write is needed. Pending means saved locally, awaiting registration. Continue without polling.

The command's exit status describes the experiment; `pending` and `recordingWarnings` describe recording. If the host blocks client execution or local saving fails, continue and report recording unavailable; do not claim it was queued.

A workspace network denial is an expected local-queue mode. Do not request a sandbox exception, relax permissions or retry network access just to register observations. Continue the research and use the final local receipt to describe delivery.

Recovery never reruns experiments or rereads changed source evidence. Do not reformat outputs, repeat experiments or diagnose the platform merely to complete a record. Manual `sync` is optional recovery.

Before your final brief result, call `status --project ID` once from the research working directory. It reads current local queue receipts without HTTP or polling. Background recovery may have replaced an earlier pending receipt with `synced`; use this latest `deliveryState`, not an old `pending` response, when describing registration. Say registered for `synced`, or saved locally awaiting background reception for `pending`. This does not test HTTP reachability: a past client connection error is not evidence that the service is down, and historical warnings do not make an acknowledged record pending. Respect the reported local scope; unknown or partial status does not confirm registration. A synced receipt confirms registration rather than scientific success.

Label synthetic data honestly and leave unavailable usage counters unknown.

The [record reference](references/records.md) covers native analysis, optional edits, assessments and evidence reads.
