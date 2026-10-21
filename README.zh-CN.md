# ExpObserver

[English](README.md)

**由你和 Agent 共同维护的本地研究图。**

探索不同方案，保留证据，看清实验为什么转向。任何节点都能包含子图：把几个算法想法放进容器，展开各自的实验，再沿着结果追溯决策。Agent 通过可移植的 Skill 和少量 JSON 增量更新，在不同对话中持续维护同一实验。

![研究图：嵌套的算法分支、实验状态，以及相互关联的发现和决策](docs/screenshots/research.png)

*研究图将候选方案、实验和决策连接起来，支持展开嵌套子图。*

## 快速开始

**交给 Agent：**复制这句话发送即可：

> 请按照 https://github.com/EuanTop/exp-observer/blob/main/INSTALL.md 安装并启动 ExpObserver，同时安装它的 Skill。

**手动安装：**[下载安装包](https://github.com/EuanTop/exp-observer/releases/latest/download/exp-observer.zip)，解压后在 `exp-observer` 文件夹中运行：

```sh
python3 start.py
```

Windows 双击 `start.bat`，或运行 `py -3 start.py`；macOS 也可以双击 `start.command`。启动器会自动打开浏览器，地址为 [127.0.0.1:4317](http://127.0.0.1:4317)。使用期间保持启动终端开启。

只需要 **[Python 3.10 或更新版本](https://www.python.org/downloads/)**，无需 Node.js、npm、pip 依赖、账号或模型 API Key。Windows 如果没有 `py` 启动器但已将 Python 加入 `PATH`，使用 `python start.py`。请下载 Releases 中的 `exp-observer.zip`；GitHub 的“Source code”源码包不含已构建界面。

默认包含模拟演示；添加 `--no-demo` 从空白工作区开始，添加 `--no-browser` 可不自动打开浏览器。开始研究后，用界面中的**连接 Agent**获取对应实验的接入指令。[安装细节](INSTALL.md) · [从源码开发](CONTRIBUTING.md#development)

## 在图中推进研究

- **自由组织。** 任意类型的节点都能包含子节点，支持折叠、展开、聚焦、分组、移动和连接。包含关系与研究关系分别维护。
- **连接执行与解释。** 运行记录保留配置、事件、指标和输出；评估及决策引用证据，修订解释时保留之前的记录。
- **比较候选。** 查看配置差异，并按选定的评价规则读取有效评估及历史评估。
- **核对证据。** 登记本地文件，保留经过校验的副本，在图旁查看图片、JSON、CSV 或文本。
- **接续工作。** 搜索研究图、切换项目、查看历史，并把旧快照恢复为一个新版本。

节点状态区分**未开始**（`proposed`）、**进行中**（`active`）、**暂停**（`paused`）、**已完成**（`completed`）、**已排除**（`rejected`）和**失败**（`failed`）。绿色实心勾表示完成，虚线圆环表示未开始，暂停条、减号和 × 分别表示暂停、排除和失败。完成表示这一步研究已结束，也可以得到负结果。**蓝色轮廓**单独标记关键节点，不与状态混用。暂停的工作记录停止原因和恢复条件。

`N` 新建节点，`⌘/Ctrl K` 搜索，`⌘/Ctrl G` 将选中节点分组，`F` 适配整张图。拖动节点标题移动；Shift 拖动框选；触控板或鼠标中键／右键平移画布。双击容器可聚焦其子图。

![方案对比：并排查看 Python 倒排索引与 SQLite FTS5 的实测结果和评估](docs/screenshots/comparison.png)

*并排核对两条路线的实验指标和评估。图中展示的是[精确检索研究](examples/real-study/report.md)的实测对比。*

## 把 Skill 交给 Agent

将 [`skills/exp-observer`](skills/exp-observer) 复制到 Agent 宿主支持的 Skill 目录，或直接把 [`SKILL.md`](skills/exp-observer/SKILL.md) 的路径交给 Agent。独立客户端随 Skill 分发，研究项目无需把 ExpObserver 导入为依赖。

界面中的**连接 Agent**会复制包含实际 Skill 路径、本地服务地址和当前实验 ID 的指令。粘贴到新 Agent 对话，再补充你的研究任务即可。

可以这样下达指令：

> 使用 ExpObserver Skill 观测实验 `my-study`。按我的研究任务推进，在已有发现或方向变化时简短记录并关联现有证据；记录问题留待补交，不打断研究。

实验属于其持久化记录。**多个对话和 Agent 可以共同维护同一个实验。** 每次操作显式指定项目，相关操作同时指定节点；不绑定对话，也不存在全局“当前实验”指针。

### 读取、执行、记录

以下示例使用 macOS/Linux Shell。Windows PowerShell 中请把 `python3` 替换为 `py -3`，将续行命令合并为一行（删除行末的 `\`），并使用 `C:/research/my-study` 等 Windows 源目录。含空格的路径需要加引号，例如：

```powershell
py -3 skills/exp-observer/scripts/exp_observer.py init --id my-study --name 'My study' --source-root 'C:/research/my study'
```

```sh
python3 skills/exp-observer/scripts/exp_observer.py projects
python3 skills/exp-observer/scripts/exp_observer.py init --id my-study --name 'My study' --source-root /absolute/study/directory
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study --node NODE_ID
```

一条命令即可登记已有结果。客户端处理编号与引用，平台安排初始位置：

```sh
python3 skills/exp-observer/scripts/exp_observer.py record --project my-study \
  --title '已经得到的发现' --summary '证据与含义' \
  --metrics-file results.json --artifact results.json
```

用 `--node NODE_ID` 更新已有节点，用 `--after NODE_ID` 关联实际研究的后续，用 `--parent NODE_ID` 分组；这些选项均可省略。嵌套指标原样保存，包括数组、null 和空容器。结果 JSON 顶层不是对象时，客户端自动放到 `result` 字段，原始文件保持原样。仅文字更新不会虚构一次实验运行。

一次调用即可捕获真实命令及其结果文件：

```sh
python3 skills/exp-observer/scripts/exp_observer.py execute \
  --project my-study --node NODE_ID --title 'Evaluate candidate A' \
  --artifact results.json --artifact timing.csv -- python3 experiment.py
```

包装器记录真实命令的退出码、墙钟时间、标准输出／错误和指定文件，**不增加模型调用**。观测平台不规定实验阶段、方法、测量项目或交付格式。Agent 在研究本身已经改变判断或方向时简短更新；坐标、编号和展示格式由平台处理。

登记失败时，`record` 和 `execute` 会在本地保留待补交记录与证据。实验成功时，记录服务不可用也不会把它改判为失败。在合适的间隙运行 `python3 skills/exp-observer/scripts/exp_observer.py sync` 即可补交，无需重跑实验。回执用 `pending` 和 `recordingWarnings` 表示记录状态，并返回已保留的标准输出／错误路径。

批量登记已有文件、读取保留的证据、检查记录或导出研究图：

```sh
python3 skills/exp-observer/scripts/exp_observer.py artifact --project my-study --node NODE_ID --path results.json timing.csv
python3 skills/exp-observer/scripts/exp_observer.py read --project my-study --artifact ARTIFACT_ID
python3 skills/exp-observer/scripts/exp_observer.py check --project my-study
python3 skills/exp-observer/scripts/exp_observer.py export --project my-study --output my-study.json
```

通过 `EXP_OBSERVER_URL` 或全局 `--url` 参数选择其他本地服务地址。操作、版本控制和分段证据读取见 [Skill 指南](skills/exp-observer/SKILL.md)、[记录参考](skills/exp-observer/references/records.md)和 [HTTP／数据契约](docs/contract.md)。自动命令采集使用显式的 `execute` 包装器；安装 Skill 不会安装全局 Hook。

### 观测研究步骤

可选的 observation 为节点上的工作计时，也可以覆盖跨越多条命令的分析。需要这项测量时再使用；它不是开展研究或登记结果的前提。开始步骤，完成工作，再使用返回的 observation ID 结束：

```sh
python3 skills/exp-observer/scripts/exp_observer.py observe start --project my-study --node candidate-a --title 'Review candidate A' --request-id review-a-start
python3 skills/exp-observer/scripts/exp_observer.py observe finish --project my-study --id OBSERVATION_ID --request-id review-a-finish
```

服务记录开始、结束时间及包含等待在内的墙钟耗时。Observation 属于节点，不绑定会话。如果运行时或供应商提供本步骤的用量计数，结束时传入 `--input-tokens N`、`--output-tokens N` 和 `--usage-source SOURCE`；`--usage-ref REF` 用于标识来源记录。缺少计数时省略对应参数：**未知保留为 `null`，实测零值保留为零**。使用步骤自身的计数，避免在多个 observation 中重复填写累计用量。

界面只汇总节点及其包含的后代。已结束的时间区间按并集合并，父子计时及并行工作不会重复累计耗时；未结束的步骤保留进行中标记。命令执行墙钟时间单独展示。Token 总量汇总已知计数，缺失计数或已开展的叶子节点缺少 observation 时标记覆盖不完整；语义连线和决策复用的证据不计入用量。

## 记录保存在本地

权威记录和增量版本历史位于 `.exp-observer/records.sqlite3`，使用 Python 内置的 `sqlite3` 模块。证据副本位于 `.exp-observer/` 下各项目的 `evidence/` 目录；需要时会编码目录名，以兼容不同系统的路径。SQLite 事务、版本检查和幂等请求 ID 支持多个 Agent 共同维护。读取证据时按登记身份校验内容。

升级前请先停止已有服务。已有的 `state.json` 工作区会自动迁移到 SQLite，同时保留历史和原始 JSON 文件；后续更新写入数据库。

先停止使用该数据目录的所有服务，再备份**整个 `.exp-observer` 目录**，一并保留数据库、历史和证据。不要在服务运行时仅复制数据库文件。研究图导出包含引用，不内嵌文件内容。服务绑定 localhost，用于本地运行。

## 示例与开发

[精确检索研究](examples/real-study/report.md)比较三种检索方法，并在纳入索引构建成本后重新审视决策。[独立接续复核](examples/real-study/continuation-review.md)检查推理并提出下一研究分支。[研究脚本](examples/real-study/study.py)在本地生成输入和测量；公开源码包含代码与报告，不附带已填充的研究工作区或归档原始测量。

前端使用 React、TypeScript、React Flow 和 Tailwind CSS，后端与可移植客户端使用 Python。开发、测试和贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

采用 [MIT](LICENSE) 许可。
