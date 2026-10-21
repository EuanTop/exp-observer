# Record reference

For routine recording, prefer the high-level client:

```sh
python3 <skill>/scripts/exp_observer.py record --project ID --title "Result already reached" --metrics-file result.json --artifact result.json
python3 <skill>/scripts/exp_observer.py record --project ID --node NODE --title "Updated finding" --summary "New evidence and implication"
```

IDs, run/evidence references and idempotent retries are handled by the client. `--after NODE` records a continuation relationship; `--parent NODE` groups related records. Metrics retain their original JSON object structure, including nested objects, arrays, empty containers and nulls. Non-object roots are stored under `result` while the original file is preserved.

## Availability and recovery

`init --name NAME [--id ID]` saves a project plan before contacting the service. Keep the returned ID, including when the receipt is pending. An explicit project passed to `record` can also prepare a missing project. Recovery creates the project only if absent; it never replaces an existing project's metadata.

`context` returns an explicitly unavailable response when the service cannot be reached, together with any dated remote cache and a summary of local pending work. An unavailable response is not an empty remote experiment. Continue from research files when context is unavailable; preserve the supplied experiment ID.

The client registers its outbox directory in the local user's recovery registry. The running application retries only these registered directories for its own loopback HTTP address, including after startup. It does not search research folders or execute experimental commands. Queue contents, captured timestamps and staged evidence are frozen before submission; retries reuse their stable identities. Local registration and file-access failures appear in recording warnings. A command blocked before execution cannot leave a durable record.

Manual recovery remains available from the original working directory:

```sh
python3 <skill>/scripts/exp_observer.py sync --project ID
```

`sync` reports pending registration separately from experimental outcomes and never reruns an experiment. Automatic recovery does not cover low-level `apply`, `artifact`, timers or evidence reads; use those optional online operations only when appropriate. A real command's return code remains its own, even if registration is pending.

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
| `node.add` | id?, title, kind?, status?, parentId?, summary?, notes?, nextAction?, importance?, importanceReason?, pauseReason?, resumeWhen?, tags? |
| `node.update` | id plus changed fields; omitted fields preserved |
| `node.delete` | id; removes subtree and associated execution records; recoverable from history |
| `edge.add/update/delete` | id, source/target/relation/label/basis as needed |
| `run.add` | id?, nodeId, title, status, configuration, metrics?, origin |
| `run.update` | id plus changed fields |
| `run.event` | runId, event: {id?,type,message,at?,...} |
| `assessment.add` | id?, runId, rubric, metrics, conclusion, limitations, supersedes?, artifactIds? |
| `decision.add` | id?, nodeId, title, conclusion, scope, nextAction, runIds, artifactIds |
| `observation.start` | id?, nodeId, title?; server supplies actual start time |
| `observation.finish` | id, inputTokens?, outputTokens?, usageSource?, usageRef?; server supplies actual finish time and duration |
| `project.update` | name?, description?, sourceRoots? |

Register actual evidence with `artifact`, rather than supplying hashes in metadata. Multiple files can be registered with `artifact --project ID --path result.json timing.csv`. Export with `export --project ID --output project.json`.

## Step timing and measured usage

Optional observations can measure a work interval, including analysis without a command run. They do not bind a conversation or change node/run state. Leave them unused when timing would require extra bookkeeping; the research can continue with unknown timing and token values.

```sh
python3 <skill>/scripts/exp_observer.py observe start --project ID --node NODE --title "Review retained outputs" --request-id review-start-1
# Work on the research question; retain the returned observationId.
python3 <skill>/scripts/exp_observer.py observe finish --project ID --id OBSERVATION_ID --request-id review-finish-1
```

If the host or provider supplies actual counters, finish can additionally carry `--input-tokens N --output-tokens N --usage-source SOURCE --usage-ref UNIQUE_USAGE_ID`. These are usage deltas attributed once, ideally to the most specific node. Do not estimate counts from text, time or command exit status. Do not repeat cumulative conversation totals on multiple nodes. A supplied counter requires a source; the same source/reference pair cannot be recorded twice. Missing counters are `null`; an actual measured zero is `0`.

The server timestamps start/finish and calculates `durationMs`. Command execution wall time is stored separately. Semantic relationships and decision evidence references do not duplicate recorded usage. A running interval can finish when the observed work stops; research state is updated independently.

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
