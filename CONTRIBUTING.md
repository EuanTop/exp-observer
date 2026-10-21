# Contributing to ExpObserver

ExpObserver retains local experiment records through explicit, incremental operations. Contributions should keep recording lightweight and the interface focused on the research.

## Development

For development, use Node.js 20+ and Python 3.10+ on Windows, macOS or Linux. CI also checks Node.js 22. The ready-to-run release needs only Python; Node.js builds and tests the frontend. Windows runs natively and does not require WSL. Install the Python launcher or add Python to `PATH`.

```sh
npm ci
```

Start the API in one terminal:

```sh
python3 -m backend.server --port 4317
```

On Windows, use `py -3 -m backend.server --port 4317` (or `python` if the launcher is unavailable). The `npm start` and `npm test` commands select a supported Python installation for the current OS.

Start the frontend in another:

```sh
npm run dev
```

Open [127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies API requests to the local backend. Add `--data-dir /absolute/scratch/directory --no-demo` to the backend command to work with an isolated, empty data directory.

## Checks

Before submitting a change:

```sh
npm test
npm run build
```

`npm test` runs frontend logic tests and Python store, HTTP and client tests. `npm run build` type-checks and builds the production interface. Check user-visible interactions in the browser when changing the graph or inspector. For a local experiment you modify, run:

```sh
python3 skills/exp-observer/scripts/exp_observer.py check --project PROJECT_ID
```

Use `py -3` instead of `python3` for the client on Windows. CI runs the checks on Windows, macOS and Linux with Python 3.10 and 3.14, plus a Node.js 20 build. Keep subprocess arguments as lists, handle paths with spaces and Unicode, and make text fixture encodings and newline expectations explicit.

Build the portable distribution after `npm run build` with `python3 scripts/package_release.py`. It contains the built frontend, Python backend, launchers and Skill, without Node dependencies or personal records. Tags named `v*` run distribution checks on all three platforms before publishing `exp-observer.zip` and `SHA256SUMS` to GitHub Releases.

Add focused regression coverage for changes to record validation, history, concurrency, evidence handling and command capture. For interface changes, verify nested containers, collapsed connections, selection and relevant keyboard actions in both appearances.

## Design and data conventions

- Experiments persist independently of conversations. Every operation explicitly selects its project and, where relevant, its node.
- Any node may contain children. Keep containment separate from semantic relationships; preserve nested records when collapsing or focusing the graph.
- Keep state and importance independent. A completed research step can have a negative conclusion. Paused work should explain its reason and resumption condition.
- Preserve earlier evidence and interpretations when revising conclusions. Resolve revision conflicts rather than overwriting another contributor's work.
- Use the portable Skill client or API for experiment maintenance. Keep synthetic fixtures marked `mock` and actual captured execution marked `observed`.
- Keep routine capture independent of model calls. Use sparse semantic updates for branches, findings and decisions.
- Observation supports research without prescribing its stages, methods, report format or validation work. Accept original nested JSON metrics; derive display paths in the interface. Handle IDs, layout, references and retry bookkeeping in the platform/client. Recording failures must not prevent command execution or change the experiment's exit code.
- First contact must also work offline. Persist identity and records before networking; label unavailable or cached context honestly. Research clients must not require writes outside their working directory. The application discovers queues inside explicitly connected research directories, including future experiment subdirectories, without following links outside the root. Recovery must never execute an experiment, invent scientific relationships, overwrite an existing project or reread changed evidence. Use isolated data directories and `EXP_OBSERVER_STATE_DIR` in tests/scratch servers; enroll only temporary roots. Automatic record-order connections must remain distinct from scientific relationships, and conclusions belong on the actual findings rather than separate completion messages.
- Keep canonical records and incremental revision history in `.exp-observer/records.sqlite3` through Python's standard-library `sqlite3`; retained evidence stays in each project's `evidence/` directory under `.exp-observer/`, using portable directory names. Stop all servers using a data directory before backing up the whole directory.
- Keep interface text concise and actionable. Technical explanations belong in the documentation.

The [data contract](docs/contract.md) describes persistence and HTTP behavior. The [Skill](skills/exp-observer/SKILL.md) and [record reference](skills/exp-observer/references/records.md) describe agent-facing operations. Update both READMEs together when changing setup or public behavior.

## Issues and pull requests

For a bug, include the shortest reproduction, expected and actual behavior, your OS and runtime versions, and relevant error output. For a feature, describe the research task and the friction you want to remove.

Keep pull requests focused. Explain the behavior change, provide the checks you ran, and include screenshots or a short recording for visual changes. Do not commit personal `.exp-observer` workspaces, retained evidence, generated measurements, credentials or dependencies. Small synthetic fixtures and reproducible research scripts belong in source.

Contributions are covered by the project's [MIT license](LICENSE).
