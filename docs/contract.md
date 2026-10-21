# ExpObserver engineering contract

Local application for Windows, macOS and Linux; persistent experiments independent of conversations. SQLite is canonical; JSON is the HTTP/export format. No account, telemetry, model API or Git required. UI consumes real HTTP data. camelCase fields everywhere. Unknown optional fields must survive edits. Node containment is separate from semantic edges; arbitrary kinds and arbitrary finite depth, no containment cycles.

Project: `{id,name,description,revision,createdAt,updatedAt,nodes:[],edges:[],runs:[],artifacts:[],assessments:[],decisions:[],observations:[],activity:[]}`. `origin` on runs/evidence is `mock` or `observed`.

Node: `{id,title,kind,status,parentId:null,summary:'',notes:'',nextAction:'',importance:'normal',importanceReason:'',pauseReason:'',resumeWhen:'',tags:[],position:{x,y},collapsed:false,createdAt,updatedAt}`. Defined statuses: proposed (not started), active (being investigated), paused (intentionally suspended), completed (unit finished, including negative results), rejected (deliberately excluded), failed (execution error prevented completion). Existing custom text statuses remain readable. Status is not a truth value for a hypothesis, and one failed run does not automatically fail a node or its parent.

Importance is independent: `normal` or `critical`, with `importanceReason` describing its impact on the main conclusion. Critical nodes have a blue outline; selection has a separate temporary ring. Parked work retains `pauseReason`, `resumeWhen` and `nextAction`. These fields are included in scoped Agent context. Legacy nodes without them remain valid.

Any node can contain nodes. Positions are absolute world coordinates, including children; a collapsed container hides descendants. Edges reference stable node IDs. Edge: `{id,source,target,relation,label,basis:'observed'|'hypothesis'|'unknown'}`. Self edges invalid. Relations free text.

Run: `{id,nodeId,title,status,configuration:{},metrics:{},startedAt,finishedAt,events:[],artifactIds:[],origin}`. Each event `{id,type,message,at,...}`. `metrics` numeric/string/bool values. Assessment: `{id,runId,rubric,metrics:{},conclusion,limitations,artifactIds:[],supersedes:null,createdAt}`. Different assessment revisions never fabricate a run. Decision: `{id,nodeId,title,conclusion,scope,nextAction,runIds:[],artifactIds:[],createdAt}`. Artifact `{id,nodeId,runId,title,path,sha256,bytes,mime,createdAt,origin}`. Evidence registration copies a file into project-managed evidence and computes identity, never trusts supplied hash.

## Storage and history

The default data directory is `.exp-observer/`. Its `records.sqlite3` database uses Python's standard-library SQLite implementation. Each operation opens and closes its own connection; write transactions use `BEGIN IMMEDIATE`, foreign-key enforcement and `synchronous=FULL`. SQLite provides process/thread coordination on all supported platforms; no Unix-specific file locks are required. Busy requests time out after 30 seconds with `storage_busy` (HTTP 503).

Current project metadata and collection records are stored separately. Only changed records, their ordering and project metadata are updated. Project list polling reads indexed summaries, without parsing project bodies or history. Reading a current project loads its current collection records, without reconstructing a historical version.

Each successful mutation atomically appends one version containing compact operation metadata and resolved JSON changes. Changes contain actual values, including generated IDs and timestamps; history reconstruction never re-executes commands or recalculates observation time. A full checkpoint is saved at the initial revision and every 50 revisions. Restore and exact idempotent retry reconstruct from the nearest checkpoint plus subsequent changes. Restoring appends a new revision and retains the current activity chronology. Request IDs and fingerprints remain durably indexed with their resulting revision; they are not evicted after 256 writes. The public history endpoint returns metadata, excluding changes and checkpoints.

On first initialization of a data directory, existing `*/state.json` bundles migrate in one transaction, including snapshots and request identities. A failed migration rolls back all imported projects and can be retried after the source is fixed. Original JSON files remain untouched as backups and are not rewritten by subsequent operations. Stop existing servers before upgrading; simultaneous JSON-based and SQLite-based writers are unsupported.

Retained evidence remains under `<project-folder>/evidence/`, outside the database. Files are copied to a temporary file, flushed and atomically installed before metadata commit. A failed commit removes the installed copy; a process crash before commit can leave an unreferenced file, never a committed partial copy. File identity is verified on reads. Existing retained files are never replaced, including after a restore or node deletion. IDs containing uppercase letters, Windows device names and trailing dots map to bounded hash-based filenames; extensions use lowercase. Logical IDs remain unchanged and case-sensitive, with distinct paths across all supported filesystems. Retained evidence paths recognize both Windows and Unix separators after backup relocation; foreign-platform source roots remain metadata until replaced with local source directories.

Stop all servers using a data directory before copying the whole directory for backup. The database and evidence must be backed up together. JSON exports contain the current graph and evidence references, rather than the database history or evidence bytes.

## Node observations

`observations` is an optional project collection for older records; a missing collection is treated as empty. New observations use the following shape:

| Field | Type / meaning |
| --- | --- |
| `id` | Stable observation ID, unique in the project |
| `nodeId` | Existing node ID; any node kind can be observed |
| `title` | Text, default empty string |
| `status` | `running` or `finished`, independent of node/run state |
| `startedAt` | ISO timestamp with timezone |
| `finishedAt` | ISO timestamp with timezone, or `null` while running |
| `durationMs` | Finite nonnegative wall-time milliseconds, or `null` while running |
| `inputTokens` | Nonnegative integer or `null` when unknown |
| `outputTokens` | Nonnegative integer or `null` when unknown |
| `usageSource` | Runtime/provider source text; empty string when no source is recorded |
| `usageRef` | Source-record reference text; default empty string |
| `origin` | `observed` for live operations; imported/seeded records may also be `mock` |

Live observations are written through the existing atomic batch endpoint, not a session endpoint:

| Operation | `data` fields | Behavior |
| --- | --- | --- |
| `observation.start` | `id?`, `nodeId`, `title?` | Creates a running observation using the server timestamp. Finish, duration and token fields start as `null`; source/reference start empty. Duplicate IDs return HTTP 409. |
| `observation.finish` | `id`, `inputTokens?`, `outputTokens?`, `usageSource?`, `usageRef?` | Finishes an existing running observation using the server timestamp; computes `durationMs` rounded to three decimal places. Omitted counters remain unknown. |

Each operation targets its explicit project; observations have no conversation or session ownership. They can span multiple commands, waits or research actions. Node completion and command success do not imply that an observation has finished.

Token counters supplied to `finish` must be nonnegative integers; omit unknown values rather than sending `null`. A supplied counter, including zero, requires a nonblank `usageSource`. A nonempty `usageRef` also requires a source; the trimmed `(usageSource, usageRef)` pair must be unique across the project, or validation returns `duplicate_usage_ref` (HTTP 409). Use non-overlapping step counters from the runtime/provider, not repeated cumulative totals. ExpObserver does not infer token counts from text, duration or run success.

Finishing an already finished observation returns `observation_finished` (HTTP 409). Reuse the original batch request ID to retry an uncertain successful finish without duplication. If the server clock precedes the start, finishing returns `invalid_observation_duration` (HTTP 409) rather than storing a negative interval. Imported timestamps must include a timezone; finished duration must agree with its nonnegative timestamp interval within 1 ms. Running records cannot have a finish time or duration. Deleting a node removes observations on that containment subtree.

### Usage aggregation

The UI scopes usage to the selected node and its containment descendants. It never traverses semantic edges or `decision.runIds`. Observation and run IDs are deduplicated before aggregation.

- `elapsedMs` is the union length of valid **finished** observation intervals. Parent/child overlap and parallel work are counted once. No measured finished interval is `null`; a measured zero interval is `0`. Running intervals are excluded; `isRunning` and `elapsedPartial` are true if any scoped observation is running.
- `runMs` separately sums finite, nonnegative `run.metrics.wallTimeMs` from scoped runs; it is `null` if none is known. `runCount` counts scoped runs regardless of whether timing is known. Query latency metrics are never substituted for execution time.
- `inputTokens` and `outputTokens` independently sum explicit finite, nonnegative integer counters, preserving `null` if no value is known. `totalTokens` sums known input/output totals, or stays `null` if both are unknown. A known zero remains zero.
- `tokensPartial` is true when any scoped observation lacks a valid input or output counter. It is also true when known counters exist in scope but a worked leaf (state other than `proposed`) has no observation. Uninstrumented pure containers do not add a missing-counter penalty. Observations are listed newest first.

### Observation CLI

```text
python3 skills/exp-observer/scripts/exp_observer.py observe start --project ID --node NODE [--title TEXT] [--request-id REQUEST]
python3 skills/exp-observer/scripts/exp_observer.py observe finish --project ID --id OBSERVATION_ID [--input-tokens N] [--output-tokens N] [--usage-source SOURCE] [--usage-ref REF] [--request-id REQUEST]
```

`start` returns `observationId`, the project revision and observation fields. With a request ID, the CLI derives a stable observation ID from it; use the same request ID only to retry the same operation. Finish uses a distinct request ID and the returned observation ID. Finish also returns the resulting fields, including actual elapsed time and the known/unknown counters. Either input or output count can be supplied independently when only one is available. Both commands use the same `EXP_OBSERVER_URL` / global `--url` configuration as other CLI operations. No additional model call is used to start, finish or aggregate observations.

HTTP, local loopback only:
- GET `/api/health` -> `{ok:true,version:'0.1.0'}`
- GET `/api/agent-setup` -> `{skillPath,clientPath,pythonPath,shell,url}` using the running server's absolute bundled Skill/client/interpreter paths and actual loopback port; `shell` is `powershell` on Windows and `posix` elsewhere. The UI uses literal quoting and the PowerShell call operator where required, so copied client commands work with spaces, apostrophes and shell metacharacters in installation paths.
- GET `/api/projects` -> `{projects:[{id,name,description,revision,nodeCount,updatedAt}]}`
- POST `/api/projects` `{id?,name,description?}` -> Project
- GET `/api/projects/:id` -> Project
- GET `/api/projects/:id/context?node=ID` -> compact state and record IDs
- POST `/api/projects/:id/batch` `{expectedRevision?,requestId?,operations:[{op,data}]}` -> Project. Atomic SQLite write transaction. Reject stale expectedRevision with HTTP 409. Stable requestId retry returns the exact original result without duplication.
- operations: node.add, node.update (`{id,...patch}`), node.delete (`{id}`, removes subtree and dangling relations), edge.add/update/delete, run.add/update/event (`{runId,event}`), assessment.add, decision.add, observation.start/finish (see below), project.update (`{name?,description?}`), artifact.add (metadata only for mock; observed evidence requires registration).
- POST `/api/projects/:id/artifacts` `{path,title?,nodeId?,runId?}` -> Artifact; source must be under project sourceRoots (set through project.update) or project data directory. CLI can set sourceRoots on init/update. No arbitrary external reads by content endpoint.
- GET `/api/projects/:id/artifacts/:artifactId/content` -> verified raw content; fail clearly on hash change; no HTML execution.
- GET `/api/projects/:id/artifacts/:artifactId/metadata` -> metadata with `verified:true`, using streaming identity verification. Observed evidence is resolved inside the current data directory, supporting backup relocation.
- GET `/api/projects/:id/artifacts/:artifactId/content?offset=0&limit=262144` -> verified byte window, maximum 1 MiB; the entire file's identity is streamed before reading the requested window.
- GET `/api/projects/:id/export` -> full Project JSON attachment
- POST `/api/import` full Project -> validate graph/references; create imported project with unique ID if collision; return Project
- GET `/api/events?project=ID` -> one SSE-formatted revision snapshot, then closes. The delivered UI uses revision polling; this endpoint is not a persistent subscription.
- GET `/api/projects/:id/history` -> revisions and operations metadata, no conversation records
- POST `/api/projects/:id/restore` `{revision,expectedRevision}` -> new Project revision (do not erase history)
- errors `{error:'human readable',code:'...'}`

Frontend reads the project list and current snapshot, then polls revisions and loads changed snapshots. Local view settings live in localStorage. The seeded `检索策略 · 研究演示` project uses synthetic `mock` records; observed studies retain actual process results and file identities separately.

Evidence preview renders verified PNG/JPEG/GIF/WebP files up to 5 MiB as images. Other binary files show verified metadata and offer the original download. SVG, HTML and script-like text remain inert text. Previews use the same hash-checked content route; image data stays local.

Skill CLI standalone Python stdlib HTTP client at `skills/exp-observer/scripts/exp_observer.py`, URL env EXP_OBSERVER_URL default http://127.0.0.1:4317. Commands: `observe start/finish` (syntax above), `projects`, `init --name NAME [--id ID] [--source-root PATH]`, `context --project ID [--node ID]`, `apply --project ID [--file FILE] [--expected-revision N] [--request-id ID]` reading JSON array/operations from stdin, `artifact --project ID --path PATH... [--node ID] [--run ID]`, `read --project ID --artifact ID [--offset N] [--limit N] [--output PATH]`, `export --project ID [--output PATH]`, `check --project ID`, `execute --project ID --node ID --title TITLE [--artifact PATH ...] -- COMMAND...` (runs actual command; registers lifecycle, stdout/stderr and specified result files without extra model calls). Each explicit operation selects experiment/node; no conversation registry or global current experiment.

Server `python3 -m backend.server --port 4317 [--data-dir PATH] [--no-demo]` serves built dist and API from the same origin. An empty store is seeded through `backend/seed.py` unless `--no-demo` is supplied.
