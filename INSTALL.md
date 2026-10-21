# Install ExpObserver

This guide is for an agent asked to install ExpObserver and its portable Skill. Follow the user's platform and agent host conventions. The ready-to-run release supports Windows, macOS and Linux and needs only Python 3.10 or newer, including its standard-library `sqlite3`. It does not need Node.js, npm, pip dependencies or a model key.

## Agent installation

1. Find an existing Python 3.10+ interpreter: `python3` or `python` on macOS/Linux; `py -3` or `python` on Windows. Check its version and that `import sqlite3` succeeds. If Python is absent, install a supported Python using the platform's normal installation method within the user's authorization. Prefer reusing an existing interpreter.
2. Download the release asset at **https://github.com/EuanTop/exp-observer/releases/latest/download/exp-observer.zip**. Use the release asset, not GitHub's source archive. `SHA256SUMS` is available alongside it. The ZIP contains a top-level `exp-observer/` folder with the built interface, backend, launchers and Skill.
3. Extract to a persistent user-owned location outside the user's research repository, for example `~/.local/share/exp-observer` on macOS/Linux or `%LOCALAPPDATA%\ExpObserver` on Windows. Python's `zipfile` works without an additional extractor. Keep the final application root, containing `start.py`, stable. Never delete an existing `.exp-observer/` data directory. Stop an existing server before replacing application files for an upgrade.
4. Copy the **whole** `skills/exp-observer/` directory into the current agent host's supported Skill directory; it includes a standalone client and references. Use the host's documented Skill installation mechanism when available. If the host cannot register local Skills, read the installed `SKILL.md` directly and keep its absolute path for future conversations. Do not place the application or research data inside the Skill directory.
5. Start `<python> <application-root>/start.py --no-demo --no-browser` using the host's supported background-process facility, with an absolute interpreter path and platform-appropriate argument quoting. If the user supplied a research directory, add `--workspace <absolute-research-directory>`; repeat for additional directories. The application persists these connections, so later experiment subdirectories are discovered too. Otherwise, the user can connect a directory in **Connect Agent**. The default address is `http://127.0.0.1:4317`. Reuse an appropriate existing server after inspecting `/api/agent-setup`. For another port, pass `--port PORT` and use that URL subsequently.
6. Verify `GET /api/health` returns `ok: true`, `/` serves the interface, and `/api/agent-setup` points to existing Skill/client files. Run `<python> <installed-skill>/scripts/exp_observer.py projects` (with `--url URL` before `projects` when using a different address). A copied Skill is self-contained; no backend imports belong in the user's research project.
7. Tell the user the browser URL, application location and Skill location. They can then give the agent a research task or use **Connect Agent** in the interface. Do not create a research project or run experiments merely to verify installation.

Connect the user's research directory once during setup, using **Connect Agent → Research directories** or `--workspace PATH`. This is application configuration, stored with its data; it is not a research-agent duty. Select the actual research directory, not a home directory as a substitute. Disconnecting stops recovery there without deleting research files.

Research can begin while the application is closed. The installed client saves project preparation and records locally, and the application recovers queues within connected research directories when running. The client does not write a global registry, so a sandbox may deny both loopback HTTP and files outside the research directory without preventing local recording. It still needs permission to execute and write inside its working directory. Verify host access during setup, separately from research.

The application continues to read the legacy user recovery registry (`EXP_OBSERVER_STATE_DIR` overrides its location) for older clients; new clients do not depend on it. Automatic recovery only submits queues for the application's loopback address, preserves original captured evidence, and never executes experiments. Manual `sync` remains available from the original working directory. Update the whole Skill as well as the application; old copied clients do not acquire new behavior automatically.

## Manual installation

Download [exp-observer.zip](https://github.com/EuanTop/exp-observer/releases/latest/download/exp-observer.zip), extract it and open the extracted `exp-observer` folder. Install [Python](https://www.python.org/downloads/) first if it is not available.

On macOS/Linux:

```sh
python3 start.py
```

On Windows:

```powershell
py -3 start.py
```

You can also double-click `start.bat` on Windows or `start.command` on macOS. If Windows has `python` on `PATH` without the `py` launcher, run `python start.py`. The browser opens automatically; keep the terminal running and use Ctrl+C to stop. `--no-browser` disables automatic browser opening; `--no-demo` starts without the synthetic demo. Use `--help` for server options.

To connect an agent, use **Connect Agent** in the interface or send it the installed `skills/exp-observer/SKILL.md` path. For automatic Skill discovery, install the entire `skills/exp-observer` directory using your agent host's documented location.

Records and evidence stay in `.exp-observer/` under the application root unless `--data-dir PATH` selects another location. For upgrades, stop the server, replace application files with the new release, and preserve that entire data directory. For development from a source checkout, see [CONTRIBUTING.md](CONTRIBUTING.md#development); only that workflow needs Node.js 20+ to build the frontend.

中文快速安装见 [README.zh-CN.md](README.zh-CN.md#快速开始)。可直接给 Agent 发送：

> 请按照 https://github.com/EuanTop/exp-observer/blob/main/INSTALL.md 安装并启动 ExpObserver，同时安装它的 Skill。