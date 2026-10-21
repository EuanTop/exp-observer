# Contributing to ExpObserver

ExpObserver is a local research graph that agents maintain through explicit, incremental operations. Contributions should keep that workflow direct and the interface focused on the research.

## Development

Use Node.js 22+ and Python 3.10+ on macOS or Linux.

```sh
npm ci
```

Start the API in one terminal:

```sh
python3 -m backend.server --port 4317
```

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

Add focused regression coverage for changes to record validation, history, concurrency, evidence handling and command capture. For interface changes, verify nested containers, collapsed connections, selection and relevant keyboard actions in both appearances.

## Design and data conventions

- Experiments persist independently of conversations. Every operation explicitly selects its project and, where relevant, its node.
- Any node may contain children. Keep containment separate from semantic relationships; preserve nested records when collapsing or focusing the graph.
- Keep state and importance independent. A completed research step can have a negative conclusion. Paused work should explain its reason and resumption condition.
- Preserve earlier evidence and interpretations when revising conclusions. Resolve revision conflicts rather than overwriting another contributor's work.
- Use the portable Skill client or API for experiment maintenance. Keep synthetic fixtures marked `mock` and actual captured execution marked `observed`.
- Keep routine capture independent of model calls. Use sparse semantic updates for branches, findings and decisions.
- Keep interface text concise and actionable. Technical explanations belong in the documentation.

The [data contract](docs/contract.md) describes persistence and HTTP behavior. The [Skill](skills/exp-observer/SKILL.md) and [record reference](skills/exp-observer/references/records.md) describe agent-facing operations. Update both READMEs together when changing setup or public behavior.

## Issues and pull requests

For a bug, include the shortest reproduction, expected and actual behavior, your OS and runtime versions, and relevant error output. For a feature, describe the research task and the friction you want to remove.

Keep pull requests focused. Explain the behavior change, provide the checks you ran, and include screenshots or a short recording for visual changes. Do not commit personal `.exp-observer` workspaces, retained evidence, generated measurements, credentials or dependencies. Small synthetic fixtures and reproducible research scripts belong in source.

Contributions are covered by the project's [MIT license](LICENSE).
