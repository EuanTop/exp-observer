# Record reference

For routine recording, prefer the semantic entry:

```sh
python3 <skill>/scripts/exp_observer.py event --project ID --question "Is the measurement boundary complete?" --finding "Verification contributes to delivery time"
python3 <skill>/scripts/exp_observer.py event --project ID --question "Is the measurement boundary complete?" --correction "Include verification in delivery time" --after "Verification contributes to delivery time"
```

`event --question TEXT` retains an active question; optional `--reason` supplies context. The question can be a retained ID or exact title from this directory, its ancestor queues or a previously fetched compact context. An unseen title receives a stable identity derived from URL, project and the title with surrounding whitespace removed. Internal whitespace and case remain significant; ambiguous titles require an existing ID. There is no approximate matching or lookup inferred from analysis prose.

One optional `--finding TEXT`, `--correction TEXT` or `--direction TEXT` creates a separate ordinary node with that actual change as its title and conclusion. It is linked to the question by `has_finding`, `has_correction` or `has_direction`; these associations claim no scientific causality. Neither question nor event is wrapped in a parent container. Existing questions and earlier findings retain their metadata. Only an explicit `--status` changes question status; supplied notes without a change update that question's native analysis.

`--after ID_OR_EXACT_TITLE` states a relationship to an earlier finding: defaults are `related_to` for a finding, `revises` for a correction and `leads_to` for a direction. `--relation supports` or another explicit relation overrides that meaning. Repeated `--evidence ID_OR_EXACT_TITLE` adds `supports` links from captured evidence to this event. Exact titles resolve locally or from retained context; missing or ambiguous optional relationship titles produce warnings while retaining the finding without those links. Explicit IDs are validated at delivery. No order-only edges are added by `event`.

A single captured execution can support several discoveries. Use its exact title in `--evidence` for each actual change, without rerunning it. Repeated measurements use `execute --question "Exact question" --title "Actual measurement" -- COMMAND...`; this adds a run to the same question, without creating a discovery. Existing JSON can be captured with `event --question "Exact question" --metrics-file result.json`. No per-tool start/finish events, fixed phases or node quotas are required.

IDs, evidence references and idempotent delivery are handled by the client. `--request-id` reuses the frozen event when retrying the same call; changed findings, reasons, references or analysis conflict with an existing request ID. Offline directories can independently retain the same question: atomic `node.ensure` creates it once while preserving existing metadata, together with each distinct event's frozen operations. Recovery performs no reclassification or source reread. Receipts expose `questionId`, `nodeId` and `eventType`.

The older `record --title TITLE` still creates a node; `record --node NODE` replaces only the fields supplied. Use it for deliberate edits, rather than a new discovery. `--conclusion`, `--kind`, `--parent` and explicit relationships remain available. New legacy records keep their automatic `recorded_after` connection unless `--independent` is supplied; this means recording order, not causality.

Keep conclusions and analysis in native platform fields by default. Do not create an additional `REPORT.md`, summary README or conclusion report unless the user explicitly requests a document. `event --notes TEXT` retains full analysis in `node.notes`. `--notes-file PATH` loads existing UTF-8 text, preserving its line breaks; `--notes-file -` reads stdin without requiring a new file. For example, in a POSIX shell:

```sh
python3 <skill>/scripts/exp_observer.py event --project ID --question "Research question" --finding "Actual discovery" --notes-file - <<'ANALYSIS'
Retain the actual reasoning, alternatives and limitations here.
ANALYSIS
```

Notes are frozen metadata in the queued operation; they are not automatically attached as evidence. Omit notes to preserve the previous value, or supply an empty value to clear it. Reusing a request ID with changed notes or type is a conflict; use a new request ID for a deliberate revision. Background recovery and `sync` use the frozen notes without rereading the source analysis file. Repeating `event` or `record` validates the supplied intent: if its notes file is missing or unreadable, the same explicit request ID, file path and other arguments can reuse the frozen analysis; a readable file with changed text remains a conflict. Missing notes cannot create a new record. Keep scripts, original measurements and images as local evidence. Metrics retain their original JSON structure, including nested objects, arrays, empty containers and nulls. Non-object roots use `result` while the original file is preserved.

## Availability and recovery

`init --name NAME [--id ID]` saves a project plan before contacting the service. Keep the returned ID, including when the receipt is pending. An explicit project passed to `event` or `record` can also prepare a missing project. Recovery creates the project only if absent; it never replaces an existing project's metadata.

`context` returns an explicitly unavailable response when the service cannot be reached, together with any dated remote cache and a summary of local pending work. An unavailable response is not an empty remote experiment. Continue from research files when context is unavailable; preserve the supplied experiment ID.

Compact context exposes `hasNotes` without expanding every analysis. Use `context --project ID --node NODE` to read that node's native notes and its descendants' notes in full. This works online and offline: offline `localNodes` folds the available frozen node updates, preserving earlier notes through later summary-only revisions; `localPendingNodes` provides the corresponding view alongside pending work when the service is available. Summary and conclusion previews are limited to 512 characters with explicit `*Truncated` flags. The receipt lists remain bounded to 20 entries, while `localNodes` can still read older retained notes. A record's `localTaskPath` also identifies its original durable JSON. No separate report is needed.

The client writes only within the working directory. Application setup connects the research directory once; the running application discovers queues there, including future experiment subdirectories, without requiring the research agent to write a global registry. Discovery stays inside explicitly connected directories and never executes experimental commands. Queue contents, timestamps and staged evidence are frozen before submission; retries reuse stable identities. A child experiment reuses its ancestor's prepared project identity and metadata. A command blocked before execution cannot leave a durable record.

Manual recovery remains available from the original working directory:

```sh
python3 <skill>/scripts/exp_observer.py sync --project ID
```

`sync` reports pending registration separately from experimental outcomes and never reruns an experiment. Automatic recovery does not cover low-level `apply`, `artifact` or evidence reads; use those optional online operations only when appropriate. A real command's return code remains its own, even if registration is pending.

Before the final brief result, read the authoritative local receipts once:

```sh
python3 <skill>/scripts/exp_observer.py status --project ID
```

`status` is read-only: it makes no HTTP requests, does not poll, run commands or retry submissions. It checks this working directory's queue and ancestor queues for this URL/project, without scanning sibling research. `source`, `scope` and `checkedAt` identify that local snapshot; `records` contains the latest receipts (up to 20), while counts cover all matching records. Project preparation is reported separately. `pendingCount` means queued records awaiting acknowledgement, and `incompleteCount` means capture did not finish and will not be rerun. `deliveryState: unknown` means no matching durable receipt was found; `partial` includes unreadable entries listed in `localReadWarnings`. Neither confirms full registration.

`deliveryState` describes recording, not connectivity; `transportChecked` is always false. For `synced`, report that the records were registered. For `pending`, say they are saved locally awaiting background reception. A past HTTP exception is a transport diagnostic, not evidence that the service is down. Historical `recordingWarnings` can remain in an acknowledged receipt and do not change its delivery state. A synced receipt confirms registration, not research success. Do not describe an earlier pending response as still pending after this snapshot says synced. Do not repeatedly call status or diagnose the platform to obtain a preferred result.

`execute --project ID --title TITLE -- COMMAND...` also works without a pre-existing node: it retains a new record and the real execution together. Supply `--node NODE` only to attach an existing record. A supplied missing node remains an invalid reference awaiting correction, rather than causing the client to invent it.

The following lower-level operations are optional adapter details.

For low-level atomic writes use `apply --project ID`, JSON input from stdin or `--file`. `context` returns the current `revision`. Supply `--expected-revision` for edits and a stable `--request-id` for safe retries. The batch is atomic: either all operations validate or none are saved.

```json
[
  {"op":"node.add","data":{"id":"study","kind":"group","title":"Retrieval study"}},
  {"op":"node.add","data":{"id":"baseline","parentId":"study","kind":"experiment","title":"Recorded scan result","status":"completed"}},
  {"op":"node.add","data":{"id":"index","parentId":"study","title":"Investigate indexing","status":"active"}},
  {"op":"edge.add","data":{"source":"baseline","target":"index","relation":"leads_to"}}
]
```

Any node kind is allowed. Parent IDs and relationship endpoints must exist in the resulting batch. Containment cycles are rejected; semantic revisit cycles are allowed.

Node states describe work, rather than scientific truth:

| Status | Meaning |
|---|---|
| `proposed` | Planned or untried; no execution implied |
| `active` | Currently being investigated |
| `paused` | Started, intentionally parked |
| `completed` | Research unit completed, including useful negative results |
| `rejected` | Deliberately excluded from this study |
| `failed` | Execution error prevented completion |

Runs retain their own status. Execution failure is distinct from a research conclusion. Optional `importance` is independently `normal` (default) or `critical`, with `importanceReason` for its significance.

Example of parking started work while opening another direction, in one atomic batch:

```json
[
  {"op":"node.update","data":{"id":"EXISTING-NODE","status":"paused","pauseReason":"A newly observed counterexample changes the next priority","resumeWhen":"After the counterexample is explained","nextAction":"Finish the remaining repeated measurements"}},
  {"op":"node.add","data":{"id":"counterexample-review","title":"Explain the observed counterexample","status":"proposed","importance":"critical","importanceReason":"The retained result conflicts with the current conclusion"}},
  {"op":"edge.add","data":{"id":"pivot-review","source":"EXISTING-NODE","target":"counterexample-review","relation":"leads_to","basis":"observed","label":"Investigate the retained conflicting output"}}
]
```

Describe a relationship's basis honestly: `observed` for an actual observation, `hypothesis` for an untested relationship, or omit it when unknown.

Operations:

| Operation | Data |
|---|---|
| `node.add` | id?, title, kind?, status?, parentId?, summary?, conclusion?, notes?, nextAction?, importance?, importanceReason?, pauseReason?, resumeWhen?, tags? |
| `node.ensure` | explicit id plus creation fields; existing ID or alias preserves all metadata |
| `node.update` | id plus changed fields; omitted fields preserved |
| `node.merge` | id, target; folds a leaf into existing work, preserving runs, evidence, observations and decisions; original metadata remains in history |
| `node.delete` | id; removes subtree and associated execution records; recoverable from history |
| `edge.add/update/delete` | id, source/target/relation/label/basis as needed |
| `run.add` | id?, nodeId, title, status, configuration, metrics?, origin |
| `run.update` | id plus changed fields |
| `run.event` | runId, event: {id?,type,message,at?,...} |
| `assessment.add` | id?, runId, rubric, metrics, conclusion, limitations, supersedes?, artifactIds? |
| `decision.add` | id?, nodeId, title, conclusion, scope, nextAction, runIds, artifactIds |
| `project.update` | name?, description?, sourceRoots? |

Register actual evidence with `artifact`, rather than supplying hashes in metadata. Multiple files can be registered with `artifact --project ID --path result.json timing.csv`. Export with `export --project ID --output project.json`.

## Read evidence

Read registered evidence through the Skill client:

```sh
python <skill>/scripts/exp_observer.py read --project ID --artifact ARTIFACT_ID
python <skill>/scripts/exp_observer.py read --project ID --artifact ARTIFACT_ID --offset 262144 --limit 262144
python <skill>/scripts/exp_observer.py read --project ID --artifact ARTIFACT_ID --offset 0 --limit 4096 --output result-part.bin
```

The server verifies the full artifact's SHA-256 and byte count before returning the requested range. `read` defaults to the first 262144 bytes; `--offset` is a zero-based byte position and `--limit` is capped at 1048576 bytes. Default output is UTF-8 text; invalid or split characters use replacement characters. `--output` preserves the original range bytes and prints a concise file acknowledgement. Use it for binary evidence or exact bytes. Reads do not update experiment records. For direct adapters, `/api/projects/ID/artifacts/ARTIFACT/content?offset=0&limit=262144` provides the same bounded bytes, and `/metadata` verifies identity without returning content.

Assessment example, using an existing run:

```json
[{"op":"assessment.add","data":{"id":"eval-v1","runId":"ACTUAL-RUN-ID","rubric":"exact-query-v1","metrics":{"consistent":true,"mean_ms":0.2},"conclusion":"Exact output equality on the recorded fixture","limitations":"One machine and one fixed corpus; inspect repeated measurements","artifactIds":["REGISTERED-RESULT-ID"]}}]
```

The example values above illustrate shape only; replace with actual results. Use one rubric to compare measurement boundaries consistently. If preparation time was omitted, revise the assessment using the existing raw evidence when possible, linking `supersedes`. If new execution is needed, create a new run.

HTTP routes and storage contract: see the repository's `docs/contract.md` when developing an adapter. Agent research generally needs only this reference and the client.
