# ExpObserver

[简体中文](README.zh-CN.md)

**A local research graph maintained by you and your agents.**

Explore alternatives, keep evidence, and follow how an experiment changes direction. Any node can contain a graph: group a few algorithm ideas, expand their experiments, then trace the results into a decision. Agents maintain the same experiment across conversations through a portable Skill and small JSON updates.

![Research graph with nested algorithm branches, experiment states and linked findings](docs/screenshots/research.png)

*Research graph: explore nested alternatives and trace evidence into decisions.*

## Quick start

**With an agent:** copy and send this instruction:

> Install and start ExpObserver and its Skill by following https://github.com/EuanTop/exp-observer/blob/main/INSTALL.md.

**By hand:** [download the ready-to-run ZIP](https://github.com/EuanTop/exp-observer/releases/latest/download/exp-observer.zip), extract it, then run this in the extracted `exp-observer` folder:

```sh
python3 start.py
```

On Windows, double-click `start.bat` or run `py -3 start.py`. On macOS, you can also double-click `start.command`. The launcher opens [127.0.0.1:4317](http://127.0.0.1:4317) in your browser. Keep its terminal open while using ExpObserver.

You only need **[Python 3.10 or newer](https://www.python.org/downloads/)**. No Node.js, npm, pip packages, account or model API key is needed. On Windows, use `python start.py` if Python is on `PATH` without the `py` launcher. Download `exp-observer.zip` from Releases; GitHub's “Source code” ZIP is for developers and does not contain the built interface.

The default workspace includes a synthetic demo. Add `--no-demo` for an empty workspace, or `--no-browser` to start without opening a browser. The interface's **Connect Agent** button supplies the instruction for attaching an agent to your experiment. [Installation details](INSTALL.md) · [Build from source](CONTRIBUTING.md#development)

## Work in the graph

- **Compose research.** Any node kind can contain child nodes. Collapse, expand, focus, group, move and connect them. Containment and research relationships are separate.
- **Keep execution and interpretation together.** Runs retain configuration, events, metrics and outputs. Assessments and decisions link back to evidence; revised interpretations preserve earlier records.
- **Compare alternatives.** Inspect configuration differences and effective or historical assessments under a selected rubric.
- **Read the evidence.** Register local files, retain verified copies, and inspect images, JSON, CSV or text alongside the graph.
- **Pick up the work.** Search the graph, switch projects, review history and restore a prior snapshot as a new revision.

Node state distinguishes **not started** (`proposed`), **active**, **paused**, **completed**, **excluded** (`rejected`) and **failed**. A filled green check marks completion; a dashed ring marks not started; pause bars, a minus and an × mark paused, excluded and failed work. Completion means the research step finished, including a negative result. A **blue outline** marks critical importance separately from state. Paused work records why it stopped and what would allow it to resume.

`N` adds a node, `⌘/Ctrl K` opens search, `⌘/Ctrl G` groups selected nodes, and `F` fits the graph. Drag a node by its header. Shift-drag selects nodes; a trackpad or middle/right mouse button pans the canvas. Double-click a container to focus it.

![Measured results and assessments for Python inverted-index and SQLite FTS5 runs](docs/screenshots/comparison.png)

*Compare measured results and assessments side by side. Shown here: the [exact-search study](examples/real-study/report.md).*

## Give your agent the Skill

Copy [`skills/exp-observer`](skills/exp-observer) into your agent host's supported Skill directory, or give the agent the path to [`SKILL.md`](skills/exp-observer/SKILL.md). The standalone client travels with the Skill; the research project does not need to import ExpObserver as a dependency.

The interface's **Connect Agent** action copies an instruction with the actual Skill path, local server address and current experiment ID. Paste it into a new agent conversation and add your research task.

A useful instruction is:

> Use the ExpObserver Skill to maintain experiment `my-study`. Begin with a visible start node, connect research steps as the work advances, and state findings directly in node titles and overviews. Keep evidence attached to the graph; do not generate a separate conclusion document unless explicitly requested. Explore within the authorized goal and budget.

An experiment belongs to its persistent record. **Multiple conversations and agents can contribute to the same experiment.** Operations explicitly select the project and, where relevant, the node; there is no conversation binding or global current-experiment pointer.

### Read, run, record

The following examples use a macOS/Linux shell. In Windows PowerShell, replace `python3` with `py -3`, put continued commands on one line (remove the trailing `\`), and use a Windows source path such as `C:/research/my-study`. Quote paths containing spaces. For example:

```powershell
py -3 skills/exp-observer/scripts/exp_observer.py init --id my-study --name 'My study' --source-root 'C:/research/my study'
```

```sh
python3 skills/exp-observer/scripts/exp_observer.py projects
python3 skills/exp-observer/scripts/exp_observer.py init --id my-study --name 'My study' --source-root /absolute/study/directory
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study --node NODE_ID
```

Use `apply` for small, related changes rather than rewriting the experiment. Read the revision from `context`; supply it when updating existing work. Reuse the request ID when retrying an uncertain write.

```sh
python3 skills/exp-observer/scripts/exp_observer.py apply --project my-study \
  --file changes.json --expected-revision REVISION --request-id stable-change-id
```

For example, `changes.json` can contain:

```json
[
  {
    "op": "node.add",
    "data": {
      "id": "candidate-a",
      "kind": "algorithm",
      "title": "Try candidate A",
      "status": "proposed",
      "importance": "normal",
      "nextAction": "Run against the fixed baseline"
    }
  }
]
```

Capture a real command and its result files with one call:

```sh
python3 skills/exp-observer/scripts/exp_observer.py execute \
  --project my-study --node candidate-a --title 'Evaluate candidate A' \
  --artifact results.json --artifact timing.csv -- python3 experiment.py
```

The wrapper records lifecycle, exit code, wall time, stdout/stderr and the requested files. Mechanical recording adds **zero model calls**; it still performs local processing and file I/O. Agents supply purpose, observations and conclusions at meaningful decision points. They can choose branches within the authorized goal and budget, record pivots, and revise conclusions from the evidence. A paused node uses `pauseReason` and `resumeWhen`; critical importance uses `importance: "critical"` and `importanceReason`.

Register existing files in bulk, inspect retained evidence, check the record or export the graph:

```sh
python3 skills/exp-observer/scripts/exp_observer.py artifact --project my-study --node candidate-a --path results.json timing.csv
python3 skills/exp-observer/scripts/exp_observer.py read --project my-study --artifact ARTIFACT_ID
python3 skills/exp-observer/scripts/exp_observer.py check --project my-study
python3 skills/exp-observer/scripts/exp_observer.py export --project my-study --output my-study.json
```

`EXP_OBSERVER_URL` or the global `--url` option selects another local server address. See the [Skill guide](skills/exp-observer/SKILL.md), [record reference](skills/exp-observer/references/records.md) and [HTTP/data contract](docs/contract.md) for operations, versioning and bounded evidence reads. Automatic command capture uses the explicit `execute` wrapper; installing the Skill does not install global hooks.

### Observe a research step

Use an observation to time work on any node, including analysis that spans several commands. Start the step, do the work, then finish with the returned observation ID:

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
