# Incremental record reference

All CLI writes use `apply --project ID`, JSON input from stdin or `--file`. `context` returns the current `revision`. Supply `--expected-revision` for edits and a stable `--request-id` for safe retries. The batch is atomic: either all operations validate or none are saved.

```json
[
  {"op":"node.add","data":{"id":"goal","kind":"group","title":"Reduce query cost without changing results","status":"active","collapsed":false,"position":{"x":300,"y":0}}},
  {"op":"node.add","data":{"id":"start","parentId":"goal","kind":"start","title":"Can indexing reduce query cost with identical results?","status":"active","summary":"Use a fixed local corpus and exact result equality; first inspect the scan baseline.","position":{"x":330,"y":100}}},
  {"op":"node.add","data":{"id":"baseline","parentId":"goal","kind":"experiment","title":"Measure the fixed scan baseline","status":"proposed","position":{"x":330,"y":340}}},
  {"op":"edge.add","data":{"id":"start-baseline","source":"start","target":"baseline","relation":"leads_to","basis":"hypothesis","label":"Establish cost and result identity before comparing alternatives"}}
]
```

Positions are absolute world coordinates, including children. Default node dimensions are 280×178. Place children at least 30px to the right and 85px below their parent origin. `collapsed` affects graph visibility; children remain stored and queryable. Any node kind is allowed. Parent IDs and edge endpoints must exist in the resulting batch. Containment cycles are rejected; semantic revisit cycles are allowed.

Use `kind: start` for the investigation's visible entry and add directed edges as real research advances; `parentId` only expresses containment. Update a result or decision node's `title` and `summary` with the actual answer, decisive evidence and limits. A decision record and its evidence references support that overview, rather than replacing it. Do not create an independent conclusion document unless the user explicitly requests one. Follow the graph presentation requirements in [the Skill](../SKILL.md); a structurally valid batch alone does not ensure a readable research path.

Node states describe work, rather than scientific truth:

| Status | Meaning | Mark |
|---|---|---|
| `proposed` | Planned or untried; no execution implied | Dashed ring |
| `active` | Currently being investigated | Blue activity ring |
| `paused` | Started, intentionally parked; record reason and resume condition | Pause bars in a dashed ring |
| `completed` | Research unit completed, including useful negative results | White check in a green circle |
| `rejected` | Deliberately excluded from this study, with a reason | Minus |
| `failed` | Execution error prevented completion | Red cross |

Runs retain their own status. Fixing a failed run may continue the same research question; do not treat execution failure as evidence that an algorithm is scientifically wrong. `importance` is independently `normal` (default) or `critical`; use `importanceReason` for the impact on the main conclusion. A critical node receives a blue outline, whether it is completed, paused or failed.

Example of parking started work while opening another direction, in one atomic batch:

```json
[
  {"op":"node.update","data":{"id":"EXISTING-NODE","status":"paused","pauseReason":"A newly observed counterexample changes the next priority","resumeWhen":"After the counterexample is explained","nextAction":"Finish the remaining repeated measurements"}},
  {"op":"node.add","data":{"id":"counterexample-review","title":"Explain the observed counterexample","status":"proposed","importance":"critical","importanceReason":"The retained result conflicts with the current conclusion","position":{"x":650,"y":500}}},
  {"op":"edge.add","data":{"id":"pivot-review","source":"EXISTING-NODE","target":"counterexample-review","relation":"leads_to","basis":"observed","label":"Investigate the retained conflicting output"}}
]
```

Use `observed` only when there really is retained supporting evidence. An idea without observed support uses `hypothesis`. A pending direction may remain proposed; a change in attention alone does not justify rejecting or completing it.

Operations:

| Operation | Data |
|---|---|
| `node.add` | id?, title, kind?, status?, parentId?, summary?, notes?, nextAction?, importance?, importanceReason?, pauseReason?, resumeWhen?, tags?, position?, collapsed? |
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

Every node can have observations, including questions, analysis and decisions without a command run. An observation is a measured work interval; it does not bind a conversation or change node/run state.

```sh
python3 <skill>/scripts/exp_observer.py observe start --project ID --node NODE --title "Review retained outputs" --request-id review-start-1
# Work on the research question; retain the returned observationId.
python3 <skill>/scripts/exp_observer.py observe finish --project ID --id OBSERVATION_ID --request-id review-finish-1
```

If the host or provider supplies actual counters, finish can additionally carry `--input-tokens N --output-tokens N --usage-source SOURCE --usage-ref UNIQUE_USAGE_ID`. These are usage deltas attributed once, ideally to the most specific node. Do not estimate counts from text, time or command exit status. Do not repeat cumulative conversation totals on multiple nodes. A supplied counter requires a source; the same source/reference pair cannot be recorded twice. Missing counters are `null`; an actual measured zero is `0`.

The server timestamps start/finish and calculates `durationMs`. A node's displayed timing combines its own and contained descendants' finished intervals, merging overlaps; command execution wall time is shown separately. Token counters sum known observations in that containment subtree; partial coverage remains marked. Semantic links and decision evidence references do not add usage. Keep a running interval when work continues; finish it when the observed work stops or is parked, and update research state independently.

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
