# ExpObserver

[简体中文](README.zh-CN.md)

**A local workspace for observing experiments and research.**

Explore alternatives, keep evidence, and follow how an experiment changes direction. Agents record findings and existing results through a portable Skill; the interface updates from those records. Expand nested alternatives, compare results, and trace the evidence behind a decision across conversations.

![Current research graph with a nested candidate group, horizontal connections and separate reciprocal links](docs/screenshots/research.png)

*Current interface with synthetic demonstration data: nested candidates, evidence links, and a two-way review loop. Active indicators rotate and connections show directional flow in the app.*

## Quick start

**With an agent:** copy and send this instruction:

> Install and start ExpObserver and its Skill by following https://github.com/EuanTop/exp-observer/blob/main/INSTALL.md.

**By hand:** [download the ready-to-run ZIP](https://github.com/EuanTop/exp-observer/releases/latest/download/exp-observer.zip), extract it, then run this in the extracted `exp-observer` folder:

```sh
python3 start.py
```

On Windows, double-click `start.bat` or run `py -3 start.py`. On macOS, you can also double-click `start.command`. The launcher opens [127.0.0.1:4317](http://127.0.0.1:4317) in your browser. Keep its terminal open while using ExpObserver.

You only need **[Python 3.10 or newer](https://www.python.org/downloads/)**. No Node.js, npm, pip packages, account or model API key is needed. On Windows, use `python start.py` if Python is on `PATH` without the `py` launcher. Download `exp-observer.zip` from Releases; GitHub's “Source code” ZIP is for developers and does not contain the built interface.

The default workspace includes a synthetic demo. Add `--no-demo` for an empty workspace, or `--no-browser` to start without opening a browser. In **Connect Agent**, connect your research directory once, then copy the short instruction for the research agent. Future experiment subdirectories are included automatically. You can also connect a directory at startup with `--workspace /absolute/research/path`. [Installation details](INSTALL.md) · [Build from source](CONTRIBUTING.md#development)

## Work in the graph

- **Compose research.** Any node kind can contain child nodes. Collapse, expand, focus, group, move and connect them. Containment and research relationships are separate.
- **Keep execution and interpretation together.** Runs retain configuration, events, metrics and outputs. Assessments and decisions link back to evidence; revised interpretations preserve earlier records.
- **Compare alternatives.** Inspect configuration differences and effective or historical assessments under a selected rubric.
- **Read the evidence.** Register local files, retain verified copies, and inspect images, JSON, CSV or text alongside the graph.
- **Pick up the work.** Search the graph, switch projects, review history and restore a prior snapshot as a new revision.

Node state distinguishes **not started** (`proposed`), **active**, **paused**, **completed**, **excluded** (`rejected`) and **failed**. A filled green check marks completion; a dashed ring marks not started; pause bars, a minus and an × mark paused, excluded and failed work. Completion means the research step finished, including a negative result. A **blue outline** marks critical importance separately from state. Paused work records why it stopped and what would allow it to resume.

`N` adds a node, `⌘/Ctrl K` opens search, `⌘/Ctrl G` groups selected nodes, and `F` fits the graph. Drag a node by its header. Shift-drag selects nodes; a trackpad or middle/right mouse button pans the canvas. Double-click a container to focus it.

![Current comparison view preserving nested JSON metrics from two synthetic example runs](docs/screenshots/comparison.png)

*Compare configuration, nested metrics and assessments side by side. This screenshot uses synthetic demonstration data. For a measured example, see the [exact-search study](examples/real-study/report.md).*

## Give your agent the Skill

Copy [`skills/exp-observer`](skills/exp-observer) into your agent host's supported Skill directory, or give the agent the path to [`SKILL.md`](skills/exp-observer/SKILL.md). The standalone client travels with the Skill; the research project does not need to import ExpObserver as a dependency.

The interface's **Connect Agent** action copies an instruction with the actual Skill path, local server address and current experiment ID. Paste it into a new agent conversation and add your research task.

A useful instruction is:

> Use the ExpObserver Skill for experiment `my-study`. Follow my research task.

An experiment belongs to its persistent record. **Multiple conversations and agents can contribute to the same experiment.** Operations explicitly select the project and, where relevant, the node; there is no conversation binding or global current-experiment pointer.

### Read, run, record

The following examples use a macOS/Linux shell. In Windows PowerShell, replace `python3` with `py -3`, put continued commands on one line (remove the trailing `\`), and use a Windows source path such as `C:/research/my-study`. Quote paths containing spaces. For example:

```powershell
py -3 skills/exp-observer/scripts/exp_observer.py init --id my-study --name 'My study' --source-root 'C:/research/my study'
```

```sh
python3 skills/exp-observer/scripts/exp_observer.py init --id my-study --name 'My study' --source-root /absolute/study/directory
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study --node NODE_ID
```

`init` saves the experiment's identity locally before contacting the service, so a new experiment can begin offline. `context` distinguishes available records, dated cached context and an unavailable service. Reading context is not a condition for continuing research. Use `projects` to list experiments when the service is running.

Record an existing result with one call. An explicit project ID can also prepare a missing project without a separate `init`. The client supplies IDs and references; the platform places the node:

```sh
python3 skills/exp-observer/scripts/exp_observer.py record --project my-study \
  --title 'Observed result' --summary 'Evidence and implication' \
  --metrics-file results.json --artifact results.json
```

Use the actual finding as the title; `--conclusion TEXT` adds a precise conclusion displayed directly on its card. Use `--node NODE_ID` to revise the same work, including a finding from a captured command. Completion belongs to that work's status rather than a separate completion node. New records retain capture order automatically, clearly labeled as record order. For an actual scientific relationship, `--after 'Earlier finding title' --relation supports` accepts an exact local title or ID; `--independent` omits ordinary order. `--parent NODE_ID` groups related work. Nested metrics remain intact, including arrays, nulls and empty containers. Non-object result JSON uses `result`; files stay unchanged. Text-only updates create no run.

Keep a distinct finding as its own record when useful, and revise the same finding with `--node`. A batch comparison can remain one record. Node count is not a target; a final summary does not establish an unrecorded research chronology.

Capture a real command and its result files with one call:

```sh
python3 skills/exp-observer/scripts/exp_observer.py execute \
  --project my-study --title 'Evaluate candidate A' \
  --artifact results.json --artifact timing.csv -- python3 experiment.py
```

The wrapper supplies a record ID and captures the actual command's exit code, wall time, stdout/stderr and requested files with **zero extra model calls**. Use `--node NODE_ID` to attach an existing record. Recording does not prescribe experimental phases, methods, measurements or deliverables. Agents leave brief updates when the research already changes a judgment or direction; coordinates, IDs and display formatting belong to the platform.

`init`, `record` and `execute` save pending work inside the working directory. The application discovers queues within connected research directories, including newly created experiment subdirectories and when starting after offline research. Clients need no global-registry write. The application submits only queues for its own loopback address and never follows directory links outside the connected root. A successful experiment remains successful even when recording is unavailable. Receipts expose `pending` and `recordingWarnings`; captured stdout/stderr remain available at their returned paths. Optional manual `sync` runs from the original working directory. Recovery never reruns an experiment or rereads changed source evidence.

The client must run to queue a record: result files alone are not queued. If the host blocks client execution or writes inside its working directory, recording is unavailable. Research continues. Connect directories during application setup, separately from the research task. The application still supports older clients' recovery registries (`EXP_OBSERVER_STATE_DIR` overrides their location); new clients do not depend on that registry. Installing the Skill grants no sandbox permissions or system service.

Register existing files in bulk, inspect retained evidence, check the record or export the graph:

```sh
python3 skills/exp-observer/scripts/exp_observer.py artifact --project my-study --node NODE_ID --path results.json timing.csv
python3 skills/exp-observer/scripts/exp_observer.py read --project my-study --artifact ARTIFACT_ID
python3 skills/exp-observer/scripts/exp_observer.py check --project my-study
python3 skills/exp-observer/scripts/exp_observer.py export --project my-study --output my-study.json
```

`EXP_OBSERVER_URL` or the global `--url` option selects another local server address. See the [Skill guide](skills/exp-observer/SKILL.md), [record reference](skills/exp-observer/references/records.md) and [HTTP/data contract](docs/contract.md) for operations, versioning and bounded evidence reads. [Testing notes and a research-focused trial prompt](docs/observation-test.md) separate connection checks from the research task. Automatic command capture uses the explicit `execute` wrapper; installing the Skill does not install global hooks.

### Observe a research step

Optional observations can time work on a node, including analysis spanning several commands. Use them when timing is useful; they are not a requirement for conducting or recording research. Start the step, do the work, then finish with the returned observation ID:

```sh
python3 skills/exp-observer/scripts/exp_observer.py observe start --project my-study --node candidate-a --title 'Review candidate A' --request-id review-a-start
python3 skills/exp-observer/scripts/exp_observer.py observe finish --project my-study --id OBSERVATION_ID --request-id review-a-finish
```

The server records start/finish times and elapsed wall time, including waits. An observation belongs to a node, with no session binding. If the runtime or provider exposes counters for this step, pass `--input-tokens N`, `--output-tokens N` and `--usage-source SOURCE` when finishing; `--usage-ref REF` identifies the source record. Omit unavailable counters: **unknown stays `null`, while measured zero stays zero**. Use step-specific counters rather than repeating cumulative usage across observations.

The interface aggregates a node and its contained descendants. Finished time intervals are combined by union, so parent timers and parallel work do not double-count elapsed time; running steps remain marked in progress. Command execution wall time is shown separately. Token totals include known counters and show partial coverage when counters or worked leaf observations are missing; semantic links and reused decision evidence do not add usage.

## Your records stay local

Canonical records and incremental revision history live in `.exp-observer/records.sqlite3`, using Python's built-in `sqlite3` module. Retained evidence copies live in each project's `evidence/` directory under `.exp-observer/`; directory names are encoded when needed for portable paths. SQLite transactions, revision checks and idempotent request IDs support maintenance by multiple agents. Evidence is verified against its registered identity when read.

Stop existing servers before upgrading. Existing `state.json` workspaces migrate automatically to SQLite, preserving their history and original JSON files. Subsequent updates use the database.

Stop every server using the data directory, then back up the **whole `.exp-observer` directory** to preserve the database, history and evidence together. Do not copy just the database file while a server is running. A graph export contains references rather than embedded file contents. The server binds to localhost and is intended for local use.

## Examples and development

The [exact-search study](examples/real-study/report.md) compares three retrieval approaches and revisits its decision after including index construction costs. An [independent continuation review](examples/real-study/continuation-review.md) checks the reasoning and proposes the next branch. The [study script](examples/real-study/study.py) generates inputs and measurements locally; the public source includes the code and reports, not a prepopulated research workspace or archived raw measurements.

The frontend uses React, TypeScript, React Flow and Tailwind CSS. The backend and portable client use Python. See [CONTRIBUTING.md](CONTRIBUTING.md) for development, tests and pull requests.

Licensed under [MIT](LICENSE).
