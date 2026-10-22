# ExpObserver engineering contract

Local application for Windows, macOS and Linux; persistent experiments independent of conversations. SQLite is canonical; JSON is the HTTP/export format. No account, telemetry, model API or Git required. UI consumes real HTTP data. camelCase fields everywhere. Unknown optional fields must survive edits. Node containment is separate from semantic edges; arbitrary kinds and arbitrary finite depth, no containment cycles.

Project: `{id,name,description,revision,createdAt,updatedAt,nodes:[],edges:[],runs:[],artifacts:[],assessments:[],decisions:[],observations:[],usageRecords:[],activity:[]}`. `origin` on runs/evidence is `mock` or `observed`.

Node: `{id,title,kind,status,parentId:null,isContainer?:boolean,summary:'',conclusion:'',notes:'',nextAction:'',importance:'normal',importanceReason:'',pauseReason:'',resumeWhen:'',tags:[],position:{x,y},collapsed:false,createdAt,updatedAt}`. Optional `conclusion` is text; older records remain valid. Cards retain the question/work title and a short summary, with a distinct recorded conclusion, latest decision or current assessment in the body. Arbitrary metrics are not converted into a narrative. Full analysis belongs in `notes` and evidence remains attached. Execution success is not a scientific conclusion. Defined statuses: proposed, active, paused, completed, rejected, failed. Completion belongs to the relevant work rather than a separate status-only finding. Custom text statuses remain readable. Status is not a hypothesis truth value, and a failed run does not automatically fail a node or its parent.

Importance is independent: `normal` or `critical`, with `importanceReason` describing its impact on the main conclusion. Critical nodes have a blue outline; selection has a separate temporary ring. Parked work retains `pauseReason`, `resumeWhen` and `nextAction`. These fields are included in scoped Agent context. Legacy nodes without them remain valid.

Any node can have children through `parentId`; this logical containment does not itself create a visual container. `isContainer: true` explicitly enables the enclosing frame for any kind; omitted `isContainer` defaults to true only for `kind: group`. Explicit false overrides that default. Ordinary parents stay cards, and their children render under the nearest visual-container ancestor or at canvas level. Logical containment still governs scoped context, usage and subtree operations. Omit `position` on `node.add` or a creating `node.ensure` for automatic initial placement after the batch resolves containment. Explicit positions remain absolute world coordinates, including children; collapse hides logical descendants. IDs can also be omitted on add operations. Edges reference stable node IDs. Edge: `{id,source,target,relation,label,basis:'observed'|'hypothesis'|'unknown'}`. Self edges invalid. Relations free text. The interface chooses connection sides and separates reciprocal relationships from current node bounds; research clients need not supply ports or routing coordinates.

Run: `{id,nodeId,title,status,configuration:{},metrics:{},startedAt,finishedAt,events:[],artifactIds:[],origin}`. Each event `{id,type,message,at,...}`. Run and assessment `metrics` accept JSON objects containing arbitrary nested objects, arrays, finite numbers, strings, booleans and nulls. Empty containers and literal keys survive unchanged. The interface derives comparison paths without mutating records. Assessment: `{id,runId,rubric,metrics:{},conclusion,limitations,artifactIds:[],supersedes:null,createdAt}`. Different assessment revisions never fabricate a run. Decision: `{id,nodeId,title,conclusion,scope,nextAction,runIds:[],artifactIds:[]}`. Artifact `{id,nodeId,runId,title,path,sha256,bytes,mime,createdAt,origin,capturedAt?}`. Evidence registration copies a file into project-managed evidence and computes identity, never trusts supplied hash. `createdAt` is server registration time; optional `capturedAt` preserves the client's original capture timestamp.

## Observation boundary

The observer records the user's existing research without adding experimental phases, mandatory measurements, graph-completeness reviews or report requirements. Scientific choices belong to the user's task and evidence. Optional timers, importance flags and low-level record edits are capabilities, not research gates.

The primary semantic entry is `event --project ID --question TEXT [--finding TEXT | --correction TEXT | --direction TEXT]`. A question alone opens meaningful work as `active`; optional `--reason` supplies its initial summary. A question is resolved by retained ID or exact title from local queues, ancestor queues and retained compact context. New titles receive a stable ID derived from URL, project and the title with surrounding whitespace removed; case and internal whitespace remain significant. Ambiguous titles require an ID, with no approximate matching or prose inference.

Each supplied finding, correction or direction becomes its own completed ordinary node with that text as title and conclusion. The question links to it using `has_finding`, `has_correction` or `has_direction`; these associations claim no scientific causality and add no parent container. Existing question metadata and prior findings remain intact. Only explicit `--status` changes question status. `--after ID_OR_EXACT_TITLE` relates the earlier record to the change with default `related_to`, `revises` or `leads_to`, respectively; `--relation` overrides it. Repeated `--evidence ID_OR_EXACT_TITLE` adds `supports` links from captured evidence. A missing or ambiguous optional relationship title produces a warning while retaining the finding without that relationship; explicit IDs are validated on delivery. No order-only edges are added by `event`. Receipts include `questionId`, `nodeId` and `eventType`.

`event` accepts `--notes` / `--notes-file` (including stdin `-`), `--metrics-file` and repeated `--artifact`. Notes attach to the change when supplied, otherwise the question. Detailed analysis stays in native fields without requiring a report. One command may support several distinct discoveries through reused evidence. `execute --question TEXT --title TEXT -- COMMAND...` adds another run of the same question without creating a discovery or resetting its metadata/status; `--question` and `--node` are mutually exclusive. Text-only events create no run. External JSON results have `configuration.capturedExternalResult: true`, an original `capturedAt`, and unknown execution timestamps. Non-object result JSON uses `result` without changing the file.

`node.ensure` requires an explicit ID and accepts the creation fields of `node.add`. If that ID, or its merged alias, exists it preserves every existing field; otherwise it creates the node. It participates in the same atomic batch as the event's new node and edges. Independent offline directories can thus retain the same question without overwriting its first registered metadata. Use `node.update` for intentional changes. Retries with a stable request ID reuse frozen operations; changed intent conflicts rather than rewriting the queued event.

The older `record --project ID --title TEXT` remains available for direct edits, with optional `--node`, `--kind`, `--summary`, `--conclusion`, `--notes` / `--notes-file`, `--after`, `--relation`, `--independent`, `--parent`, `--status`, `--metrics-file` and repeated `--artifact`. New records default to kind `finding`; `--node` replaces only supplied fields. Use `event` to preserve a distinct new outcome. New legacy records and standalone command captures can retain the preceding local record with `relation: recorded_after`, `label: 记录顺序`, and `basis: observed`; `--independent` omits it. This is capture order, not causality. The canvas draws it as a faint dashed line without a relation label or flow animation. Explicit scientific links remain labeled and separate. Legacy `--after` accepts an ID or exact local title; an ambiguous title warns without inventing a relationship. Relationships are frozen before first submission and never added to old queued records during retry.

`node.merge {id,target}` folds a leaf into another existing node atomically. It moves run, artifact, decision and observation references, redirects edges and removes resulting self edges. It retains all execution identities, evidence bytes and artifact metadata; the original source node remains in revision history. `nodeAliases` maps merged IDs directly to their current nodes so pending references, evidence registration and context reads remain valid. Containers and self merges are rejected. This allows duplicate status records to be consolidated without the data loss of subtree deletion.

`execute` runs the requested command independently of recording availability. Its return code describes the command. `recordingWarnings` and `pending` describe registration problems separately. Original command timestamps, metrics, stdout/stderr and staged requested files are kept in a local persistent outbox; `sync` retries only registration using stable identities. It never reruns an experiment or rereads a changed source file as if it were the original result. The ordinary low-level API remains atomic and rejects invalid references or non-JSON values.

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
- `runMs` separately sums finite, nonnegative `run.metrics.wallTimeMs` from scoped execution runs; it is `null` if none is known. `runCount` counts those executions regardless of whether timing is known. External result snapshots are excluded. Query latency metrics are never substituted for execution time.
- `inputTokens` and `outputTokens` independently sum explicit finite, nonnegative integer counters within one token scope, preserving `null` if no value is known. `totalTokens` sums known input/output totals, or stays `null` if both are unknown. A known zero remains zero. The compact node total prefers measured agent counters (including manual observations); if none exist and execution records are available, it uses execution counters and labels that scope. It never mixes the scopes. Detailed panels retain both.
- `tokensPartial` is true when a selected observation or usage record lacks a valid input or output counter. It is also true when known counters exist in that scope but a worked leaf (state other than `proposed`, kind other than `group`/`container`) has no selected observation or usage record. Observations are listed newest first.

### Automatic host usage

`usageRecords` retains measured inference increments independently of manual observations. Each record has `{id,source,sourceRef,agentId?,provider,model,inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens,startedAt,finishedAt,nodeId,attribution,scope?}`. Missing scope means `agent` for older records. Unknown counters remain `null`; `(source, sourceRef)` identifies one measurement. Input/output/cache fields preserve the source's raw values. The interface groups by scope, provider and model and lists cache counts separately without adding them again to input. Agent and execution scopes are displayed separately and never summed as one cost.

The optional Happy adapter reads its local SQLite database in read-only mode after checking the schema. This is an internal host format, not a portable public API. Missing, locked or unsupported host data does not prevent recording. A binding requires an actual research client invocation with a matching project ID and a working directory under that project's source roots; mentioning an experiment in an unrelated conversation does not bind its usage. Research agents do not maintain counters or host configuration.

An inference belongs to a node only when its complete measured time interval falls inside one unambiguous recorded active interval. Frozen capture timestamps provide that interval; delayed registration time cannot substitute for research time. Otherwise it remains in project usage with `nodeId: null`. Historical whole-conversation totals must never be divided among nodes or copied onto each node. Node aggregates include only explicitly attributed usage and containment descendants, deduplicating any explicit observation of the same source/reference. Project usage retains unassigned measurements and states how many could not be attributed.

### Captured execution usage

The default background importer also reads measured task usage through `backend/execution_usage.py`, independently of Happy availability. It considers observed runs and their observed, run-linked evidence, reads retained copies through the hash-checked artifact API, and ignores changing `sourcePath` files. It never reruns commands or extracts counters from arbitrary nested research metrics named `usage`, `tokens` or `model`.

Native Codex capture uses an actual command run with nonempty `configuration.command` and no `capturedExternalResult` flag. For a task already required by the research:

```sh
python3 skills/exp-observer/scripts/exp_observer.py execute \
  --project my-study --question 'Exact question' --title 'Actual Codex task' \
  -- codex exec --json 'Task prompt'
```

`execute` retains stdout/stderr automatically; a separately written native log can be included with `--artifact task.jsonl` on that execution. A native stream must consist entirely of JSON-object lines, begin with `thread.started` containing a nonblank `thread_id`, and use recognized Codex events (`thread.started`, `turn.started/completed/failed`, `item.started/updated/completed`, `error`). A `turn.completed` must carry measured `usage.input_tokens` and `usage.output_tokens`. Optional `cached_input_tokens`, `cache_write_input_tokens` and `reasoning_output_tokens` are preserved; reasoning is not added again to output. An unfinished trailing turn leaves earlier completed turns valid. Mixed plain text, unknown wrappers, isolated completion objects, overlapping turns or repeated thread headers cannot establish native attribution. An external result snapshot cannot establish a native invocation identity.

Each completed turn uses source `codex-cli`, provider `codex`, and a `sourceRef` derived from project ID, execution run ID, thread ID and turn ordinal. Repeated copies of the same run's log and importer restarts do not duplicate usage; a separate execution using the same thread is a distinct measurement. The native stream does not report model identity: `model` stays `unknown` with `modelSource: unreported`, regardless of prompt text or command arguments.

Other executors can declare **per-invocation deltas** using this explicit protocol in `run.metrics.expObserverUsage` or a retained JSON object's top-level `expObserverUsage`:

```json
{
  "expObserverUsage": {
    "version": 1,
    "records": [{
      "source": "executor-name",
      "sourceRef": "original-invocation-id",
      "provider": "provider-name",
      "model": "reported-model-name",
      "scope": "execution",
      "counterKind": "delta",
      "inputTokens": 100,
      "outputTokens": 7,
      "cacheReadTokens": 80,
      "cacheWriteTokens": 0
    }]
  }
}
```

These numbers illustrate protocol shape only. The stream equivalent is one JSON object per declaration with `type: expobserver.usage.v1` plus the record fields. `source`, `sourceRef` and `provider` are required nonblank strings; omitted model defaults to `unknown`. Omitted `scope` and `counterKind` default to `execution` and `delta`; no other values are accepted. Counters are nonnegative integers or unknown (`null`/omitted), with at least one measured counter; booleans and cumulative totals are rejected. The version must be integer `1`, and `records` is bounded to 10,000 entries. Explicit original invocation identities also permit import from retained external snapshots. Reusing a source/reference across snapshots does not create another measurement; conflicting counters, provider or model warn without replacing the original. The same declaration found on two nodes in one scan remains unassigned (`ambiguous-execution`).

Imported records have `scope: execution`, `attribution: captured-execution`, `executionRunId`, `timestampScope: execution`, and `tokenSemantics: runtime-reported`. Artifact imports additionally retain `evidenceArtifactId` and `evidenceSha256`. They attach directly to the run's node without the host adapter's active-interval inference. Timestamps use the containing execution's measured bounds; if either bound is absent both stay `null`. They are not measured turn timestamps or registration times. Captured task counters are not the main research agent's complete cost.

Candidate evidence must have a text MIME type, JSON/JSONL MIME type, or a `.json`, `.jsonl`, `.ndjson`, `.txt` or `.log` suffix. Each file is limited to 8 MiB and each scan to 16 MiB of uncached evidence. Invalid or unavailable evidence produces recording warnings without blocking valid imports or research; failures back off before retrying. Unknown model, time and counters remain unknown. Importing old screenshots requires the original qualifying execution records and evidence; screenshots alone establish neither usage nor a successful import.

### Observation CLI

```text
python3 skills/exp-observer/scripts/exp_observer.py observe start --project ID --node NODE [--title TEXT] [--request-id REQUEST]
python3 skills/exp-observer/scripts/exp_observer.py observe finish --project ID --id OBSERVATION_ID [--input-tokens N] [--output-tokens N] [--usage-source SOURCE] [--usage-ref REF] [--request-id REQUEST]
```

`start` returns `observationId`, the project revision and observation fields. With a request ID, the CLI derives a stable observation ID from it; use the same request ID only to retry the same operation. Finish uses a distinct request ID and the returned observation ID. Finish also returns the resulting fields, including actual elapsed time and the known/unknown counters. Either input or output count can be supplied independently when only one is available. Both commands use the same `EXP_OBSERVER_URL` / global `--url` configuration as other CLI operations. No additional model call is used to start, finish or aggregate observations.

HTTP, local loopback only:
- GET `/api/health` -> `{ok:true,version:'0.1.4'}`
- GET `/api/workspaces` -> `{workspaces:[{id,path,addedAt}]}`. Application configuration, independent of research revisions.
- POST `/api/workspaces` `{path}` -> same list; enroll an absolute existing research directory once, deduplicating its canonical identity.
- POST `/api/workspaces/remove` `{id}` -> same list; stop discovery without deleting research files or records, including legacy registrations under the removed root unless independently enrolled.
- GET `/api/agent-setup` -> `{skillPath,clientPath,pythonPath,shell,url}` using the running server's absolute bundled Skill/client/interpreter paths and actual loopback port; `shell` is `powershell` on Windows and `posix` elsewhere. The UI uses literal quoting and the PowerShell call operator where required, so copied client commands work with spaces, apostrophes and shell metacharacters in installation paths.
- GET `/api/projects` -> `{projects:[{id,name,description,revision,nodeCount,updatedAt}]}`
- POST `/api/projects` `{id?,name,description?}` -> Project
- GET `/api/projects/:id` -> Project
- GET `/api/projects/:id/context?node=ID` -> compact state and record IDs
- POST `/api/projects/:id/batch` `{expectedRevision?,requestId?,operations:[{op,data}]}` -> Project. Atomic SQLite write transaction. Reject stale expectedRevision with HTTP 409. Stable requestId retry returns the exact original result without duplication.
- operations: node.add, node.ensure (`{id,...creationFields}`, create only if absent, preserving existing ID/alias metadata), node.update (`{id,...patch}`), node.merge (`{id,target}`, leaf only), node.delete (`{id}`, removes subtree and dangling relations), edge.add/update/delete, run.add/update/event (`{runId,event}`), assessment.add, decision.add, observation.start/finish (see above), project.update (`{name?,description?}`), artifact.add (metadata only for mock; observed evidence requires registration).
- POST `/api/projects/:id/artifacts` `{id?,path,title?,nodeId?,runId?,sha256?,bytes?,capturedAt?}` -> Artifact; source must be under project sourceRoots (set through project.update) or project data directory. Optional expected SHA-256/byte count are checked against the copied bytes before committing; mismatch returns `evidence_changed` (409). CLI can set sourceRoots on init/update. No arbitrary external reads by content endpoint.
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

Skill CLI standalone Python stdlib HTTP client at `skills/exp-observer/scripts/exp_observer.py`, URL env EXP_OBSERVER_URL default http://127.0.0.1:4317. Commands: `event --project ID --question TEXT [--finding TEXT | --correction TEXT | --direction TEXT]` (options above), legacy `record`, `status --project ID`, `sync --project ID`, `observe start/finish` (syntax above), `projects`, `init --name NAME [--id ID] [--source-root PATH]`, `context --project ID [--node ID]`, `apply --project ID [--file FILE] [--expected-revision N] [--request-id ID]` reading JSON array/operations from stdin, `artifact --project ID --path PATH... [--node ID] [--run ID]`, `read --project ID --artifact ID [--offset N] [--limit N] [--output PATH]`, `export --project ID [--output PATH]`, `check --project ID`, `execute --project ID [--node ID | --question TEXT] --title TITLE [--artifact PATH ...] -- COMMAND...` (runs actual command; registers lifecycle, stdout/stderr and specified result files without extra model calls). Each explicit operation selects experiment/node; no conversation registry or global current experiment.

`init` durably saves a project plan before contacting HTTP. Recovery creates the project only when it is absent and never replaces existing metadata; lost create responses can be resolved by reading the same stable ID. If a prepared plan is already being processed, initialization returns a pending receipt without waiting for recovery or sending another request; unconfirmed metadata is omitted. A lock alone does not prove a plan was saved. `event`, `record` and `execute` can prepare a missing explicitly named project without a separate initialization call. For `execute`, omitting both `--node` and `--question` atomically adds a record for the actual command and its run; an explicit `--node` must refer to an existing node, while `--question` ensures the question and adds its run. Project plans and capture tasks remain in the originating working directory's `.exp-observer-runs` directory. Receipts distinguish local pending work from successful remote registration.

`context` uses a short network attempt and returns an explicit availability marker on connection failure. Any retained remote context has its own cache timestamp; pending local operations are summarized separately. Unavailability never implies that the remote project is empty or that all existing records are known. Actual request validation errors remain errors.

Project-wide context marks each node with `hasNotes` and omits full analysis text. Scoped `context --project ID --node NODE` includes native `notes` verbatim for that node and its containment descendants. This keeps initial context compact while allowing analysis to be read without a separate report artifact.

`status --project ID` reads local capture receipts and project plans in the working directory and its ancestors without HTTP, writes or polling. It reports that explicit scope, `transportChecked: false`, and `deliveryState: synced|pending|unknown|partial`. A matching frozen task receipt supersedes its earlier pending result; historical connection warnings do not turn an acknowledged record into pending work. An empty queue is unknown, not proof of registration. Background file recovery can acknowledge a record even when the research client's loopback network access is denied. A synced receipt confirms registration, not scientific success or current HTTP reachability.

The portable client writes no global recovery registration. The application persists explicitly enrolled research roots in its SQLite settings, separately from research history; `--workspace PATH` can enroll roots during installation/startup. Recovery incrementally discovers `.exp-observer-runs/outbox` inside those roots, including future experiment directories. Traversal is bounded per cycle, skips dependency/build and capture-evidence trees, and never follows child symlinks or Windows junctions. Evidence, queue and lock paths must stay inside the connected scope. Explicit ancestor initialization plans take precedence over descendant implicit metadata; a child capture also reuses an accessible ancestor plan.

Legacy per-user outbox registrations remain readable (`EXP_OBSERVER_STATE_DIR` overrides their location). Failure to read that registry does not stop enrolled-root recovery. Removed roots suppress matching legacy registrations unless another active enrollment authorizes them. Recovery submits only matching loopback HTTP queues, with redirects and proxies disabled. Stable identities and frozen evidence permit concurrent retry without duplicate captures, rerunning commands or rereading changed source evidence. Low-level online operations remain unqueued. The research client still needs permission to execute and write inside its working directory.

Server `python3 -m backend.server --port 4317 [--data-dir PATH] [--no-demo] [--workspace PATH ...]` serves built dist and API from the same origin. An empty store is seeded through `backend/seed.py` unless `--no-demo` is supplied.
