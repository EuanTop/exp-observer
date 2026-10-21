---
name: exp-observer
description: Maintain an ExpObserver experiment during agent-led research, including exploratory branches, observations, evidence and decisions. Use when working with an ExpObserver project or asked to track, resume, compare or inspect experiments. Experiments are independent of conversations.
---

# ExpObserver

Maintain a useful research record while doing the research. Choose the next question, method and depth from the user's objective, current evidence and existing budget; ExpObserver does not prescribe a fixed experimental pipeline. It does not grant additional budget or override a pause request.

Use the bundled standard-library client at `scripts/exp_observer.py`, relative to this directory. `EXP_OBSERVER_URL` defaults to `http://127.0.0.1:4317`; global `--url` overrides it. No model key is needed.

The client runs on Windows, macOS and Linux with Python 3.10+. Examples below use `python3`; on Windows use `py -3` or a supported `python`, quote paths containing spaces, and use PowerShell syntax rather than Unix shell continuations. The interface's client command selects the server's actual Python executable and shell syntax.

Use **ExpObserver** as the product name and `exp-observer` as the repository and Skill name.

## Restore only the relevant context

Start or resume with `context --project ID`; prefer `--node NODE` for a local question. If the project is unknown, use `projects`. Scoped context includes descendants, touching relationships, and decision-referenced runs, effective assessments and evidence. Read the evidence needed for the next judgment rather than loading the entire export.

Select the project and relevant node explicitly on each operation. Multiple agents and conversations can contribute to one experiment. Do not create a conversation registry, session binding or global current-experiment pointer.

## Make the research readable in the graph

- **Give every investigation a clear entry.** Before substantive research begins, create a visible node with `kind: start`. Its title states the research question; its `summary` states scope, inputs and the first action. Place it within the relevant research container when there is one. On resume, reuse the existing entry rather than adding a start for each conversation. For older records missing an entry, label any later organizational addition honestly; do not invent past execution or timing.
- **Connect work as it advances.** Link the start to the first work node, and connect subsequent work to the preceding question, observation or result with meaningful directed relationships. The graph must let a reader follow entry → investigation → evidence → conclusion, including real branches, revisits and pauses. Containment alone does not express progression. Labels explain why the next step follows; use `basis: observed` only for retained evidence and `hypothesis` for an untested lead. This requirement applies even to a small study; it does not require a fixed research pipeline or artificial stages.
- **Put findings on the node itself.** When evidence supports a result, update the node `title` to state the finding or decision, rather than only the activity or a generic label such as “Conclusions and recommendations.” The `summary` (the node overview) begins with the answer, then gives the decisive evidence, implication or recommended action, and applicable limits. Keep it concise and understandable on the card; put detail in `notes` and link actual runs, assessments, artifacts and decisions. An uncertain or negative result should state that uncertainty or negative finding directly.
- **Keep conclusions in the platform.** Do not generate a separate conclusion/report Markdown, PDF, Word or other document by default. Do not replace an answer with “see REPORT.md” or “the conclusion is in a document.” The title and overview must be self-contained. Scripts, raw data, measurements and visual evidence may remain files attached to the relevant node. Generate a standalone written deliverable only when the user explicitly requests one, and still keep the conclusion visible on its node.

## Observe and act as the work develops

- Follow useful leads within the authorized goal. Add a branch when a new question changes what you will investigate; put related alternatives inside a container when this improves readability. Any kind of node may contain children. Containment and semantic relationships are independent.
- Preserve a short reason for a pivot and its supporting observation. Untried ideas stay `proposed`. Work currently being investigated is `active`. When parking work already started, set it `paused` and record `pauseReason`, `resumeWhen` and the remaining `nextAction`; introducing a different branch does not complete or exclude the old one.
- Distinguish outcomes. `completed` means the research unit is finished, including a useful negative result. `rejected` means deliberately excluded, with a reason. `failed` means an execution error prevented completion. A failed run does not automatically invalidate its hypothesis or fail the whole parent branch.
- At meaningful milestones, inspect whether the evidence still supports the current conclusion: changed inputs, inconsistent evaluation boundaries, counterexamples, missing outputs or an untested dependency can change the next useful experiment. Resolve what the evidence allows, record uncertainty where it remains, and leave a concrete next action. Do not rerun merely to populate the interface.
- Mark a node `importance: critical` when it changes the main conclusion, exposes a decisive counterexample or evaluation flaw, or records a pivotal decision. Explain the impact in `importanceReason` and link actual evidence through its runs/artifacts/decisions. Importance is independent of status and kind; do not mark every result or decision critical.

These are decision criteria, not mandatory stages. Write concise research reasons and checkable observations at useful points, not every tool call or a transcript of internal deliberation. Do not invoke another model just to narrate routine work.

## Capture facts cheaply

```sh
python3 <skill>/scripts/exp_observer.py context --project ID --node NODE
python3 <skill>/scripts/exp_observer.py execute --project ID --node NODE --title "Experiment title" --artifact results.json -- python3 experiment.py
python3 <skill>/scripts/exp_observer.py apply --project ID --file changes.json --expected-revision N --request-id stable-operation-id
python3 <skill>/scripts/exp_observer.py read --project ID --artifact ARTIFACT_ID
python3 <skill>/scripts/exp_observer.py check --project ID
```

`execute` actually runs the command and records lifecycle, measured wall time, exit code and stdout/stderr evidence with no extra model calls. Repeat `--artifact PATH` to retain result files. Existing outputs can be registered together with `artifact --path FILE1 FILE2`; registration computes hashes and retains copies. `read --offset N --limit N` returns a verified byte window. Capture is explicit, not an implicit host hook.

For research beyond command execution—reading, analysis, comparison or decisions—use `observe start --project ID --node NODE` and `observe finish --project ID --id OBSERVATION_ID` around a meaningful work interval. The server measures elapsed time; starting a timer does not change the node's research state. At finish, supply `--input-tokens` / `--output-tokens` only from actual runtime or provider counters, with `--usage-source` and preferably a unique `--usage-ref`. Record each usage delta once at the most specific node; do not copy a conversation's cumulative total onto several nodes. Unavailable counters stay unknown, never estimated or zero-filled. Containers aggregate their descendants and merge overlapping timing intervals. See the reference for details.

Read [the record reference](references/records.md) when constructing writes, assessments or state transitions. `apply` accepts an operations array or `{operations,expectedRevision,requestId}` from a file or stdin and returns a compact acknowledgement. Batch related changes; do not edit the SQLite database directly. For a new experiment use `init --name NAME --id ID --source-root /absolute/study/directory` (a native absolute directory on the current host).

## Preserve the evidence trail

Use the revision returned by context. On conflict, re-read affected records and reconcile. Reuse the same request ID for an uncertain retry. Revise an assessment of existing output through `supersedes` on the same run/rubric; a changed interpretation is not a new measurement. Preserve previous decisions, failed attempts and bounded conclusions. Mark synthetic records `origin: mock`, actual observations `observed`; do not invent execution or missing inputs.

Before handing work over, inspect the graph's content as well as its structure: a visible start leads through meaningful connections to the findings; conclusion titles and overviews contain the actual answer and limits; completed work has no stale “installing” or “testing” descriptions; branch states and next actions are accurate. Run `check` for structural/evidence problems. Passing that command does not establish scientific validity or verify these narrative requirements.
