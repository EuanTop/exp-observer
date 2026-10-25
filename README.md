<p align="center">
  <img src="public/assets/app-icon.svg" width="88" height="88" alt="ExpObserver icon" />
</p>
<h1 align="center">ExpObserver</h1>
<p align="center"><strong>See how your agent's research unfolds.</strong></p>
<p align="center">Questions, experiments, evidence, and findings — connected in one local workspace.</p>
<p align="center">
  <a href="https://github.com/EuanTop/exp-observer/actions/workflows/ci.yml"><img src="https://github.com/EuanTop/exp-observer/actions/workflows/ci.yml/badge.svg" alt="Build and tests" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license" /></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10 or newer" /></a>
</p>
<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/usage.md">User guide</a> ·
  <a href="skills/exp-observer/SKILL.md">Agent Skill</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

![ExpObserver showing the main story of a real research study, with collapsed containers and paused follow-up questions](docs/screenshots/workspace.png)

<p align="center"><sub>A real exploratory study: follow the main story, then enter a container to inspect the work behind it.</sub></p>

## Research you can follow

| Follow the reasoning | Inspect the evidence |
| :--- | :--- |
| **Nested research spaces.** Keep the main story readable; open containers for subquestions, alternatives, and deeper experiments. | **Original results.** Inspect retained files, command output, configuration, and comparisons beside the graph. |
| **Work across conversations.** A portable Skill lets multiple agent chats contribute to the same experiment. Copy a node reference to discuss a specific step. | **Visible progress and cost.** See completed, paused, excluded, and failed work, with captured timing and available Token usage. |

Your agent chooses the research approach. ExpObserver preserves how it develops, including negative results and unfinished questions. Records, revision history, and evidence stay on your computer.

## Quick start

### Ask your agent

Send this instruction to your agent:

> Install and start ExpObserver and its Skill by following https://github.com/EuanTop/exp-observer/blob/main/INSTALL.md.

### Or start it yourself

1. [Download **exp-observer.zip**](https://github.com/EuanTop/exp-observer/releases/latest/download/exp-observer.zip) and extract it.
2. Launch **start.bat** on Windows or **start.command** on macOS. On Linux, run `python3 start.py`.
3. Open **Connect Agent**, connect your research directory, and copy the instruction into your agent chat.

Requires **Python 3.10+**. The ready-to-run package needs no Node.js, pip packages, account, or model API key. [Installation & upgrades →](INSTALL.md)

Then give your agent a research task:

> Use the ExpObserver Skill for experiment `my-study`. Investigate my question, retain the evidence, and keep the experiment up to date as you work.

The Skill can wake the installed platform when it is closed. Records queue locally if the service is unavailable.

<details>
<summary><strong>A closer look: explore a research step and reference it in your next conversation</strong></summary>

![A selected research node with its details and the copy-reference action](docs/screenshots/node-reference.png)

Select a node and choose **复制引用** (Copy reference). Paste it into any agent chat and add your question. The reference carries the experiment and node identity, so the agent can read the latest context.

</details>

## Explore further

[User guide](docs/usage.md) · [Skill](skills/exp-observer/SKILL.md) · [API & data contract](docs/contract.md) · [Measured example](examples/real-study/report.md) · [Contributing](CONTRIBUTING.md)

Built with React, TypeScript, Tailwind CSS, React Flow, ELK, and Python. [MIT licensed](LICENSE).
