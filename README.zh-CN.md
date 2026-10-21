# ExpObserver

[English](README.md)

**由你和 Agent 共同维护的本地研究图。**

探索不同方案，保留证据，看清实验为什么转向。任何节点都能包含子图：把几个算法想法放进容器，展开各自的实验，再沿着结果追溯决策。Agent 通过可移植的 Skill 和少量 JSON 增量更新，在不同对话中持续维护同一实验。

![研究图：嵌套的算法分支、实验状态，以及相互关联的发现和决策](docs/screenshots/research.png)

*研究图将候选方案、实验和决策连接起来，支持展开嵌套子图。*

## 本地启动

在 **macOS 或 Linux** 上从源码构建，需要 **Node.js 22+** 和 **Python 3.10+**：

```sh
npm ci
npm run build
npm start
```

打开 [127.0.0.1:4317](http://127.0.0.1:4317)。无需账号或模型 API Key，本地服务使用 Python 标准库。

如果 ZIP 包内包含已构建的 `dist/` 目录，可以跳过 Node.js，直接运行：

```sh
python3 -m backend.server --port 4317
```

默认工作区包含模拟研究演示。需要空白工作区时，使用 `python3 -m backend.server --port 4317 --no-demo` 启动。Agent 或界面使用期间，请保持服务运行。

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

> 使用 ExpObserver Skill 维护实验 `my-study`。研究开始时建立清晰的 start 节点，推进时连接前后研究步骤，实际发现直接写进节点标题和概览。证据关联在图中，默认不生成独立结论文档。在已授权目标和预算内自主探索。

实验属于其持久化记录。**多个对话和 Agent 可以共同维护同一个实验。** 每次操作显式指定项目，相关操作同时指定节点；不绑定对话，也不存在全局“当前实验”指针。

### 读取、执行、记录

```sh
python3 skills/exp-observer/scripts/exp_observer.py projects
python3 skills/exp-observer/scripts/exp_observer.py init --id my-study --name 'My study' --source-root /absolute/study/directory
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study --node NODE_ID
```

使用 `apply` 批量提交少量相关变化，无需重写整个实验。先从 `context` 获取版本号，修改已有工作时携带该版本；写入结果不确定时，使用相同的请求 ID 重试。

```sh
python3 skills/exp-observer/scripts/exp_observer.py apply --project my-study \
  --file changes.json --expected-revision REVISION --request-id stable-change-id
```

例如，`changes.json` 可以包含：

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

一次调用即可捕获真实命令及其结果文件：

```sh
python3 skills/exp-observer/scripts/exp_observer.py execute \
  --project my-study --node candidate-a --title 'Evaluate candidate A' \
  --artifact results.json --artifact timing.csv -- python3 experiment.py
```

包装器记录生命周期、退出码、墙钟时间、标准输出／错误和指定文件。机械记录**不增加模型调用**，但仍涉及本地处理和文件读写。Agent 在有研究意义的决策点补充目的、观察和结论，可以在授权目标及预算内选择分支、记录转向，并根据证据修订结论。暂停节点使用 `pauseReason` 和 `resumeWhen`；关键节点使用 `importance: "critical"` 和 `importanceReason`。

批量登记已有文件、读取保留的证据、检查记录或导出研究图：

```sh
python3 skills/exp-observer/scripts/exp_observer.py artifact --project my-study --node candidate-a --path results.json timing.csv
python3 skills/exp-observer/scripts/exp_observer.py read --project my-study --artifact ARTIFACT_ID
python3 skills/exp-observer/scripts/exp_observer.py check --project my-study
python3 skills/exp-observer/scripts/exp_observer.py export --project my-study --output my-study.json
```

通过 `EXP_OBSERVER_URL` 或全局 `--url` 参数选择其他本地服务地址。操作、版本控制和分段证据读取见 [Skill 指南](skills/exp-observer/SKILL.md)、[记录参考](skills/exp-observer/references/records.md)和 [HTTP／数据契约](docs/contract.md)。自动命令采集使用显式的 `execute` 包装器；安装 Skill 不会安装全局 Hook。

### 观测研究步骤

使用 observation 为任意节点上的工作计时，也可以覆盖跨越多条命令的分析过程。开始步骤，完成工作，再使用返回的 observation ID 结束：

```sh
python3 skills/exp-observer/scripts/exp_observer.py observe start --project my-study --node candidate-a --title 'Review candidate A' --request-id review-a-start
python3 skills/exp-observer/scripts/exp_observer.py observe finish --project my-study --id OBSERVATION_ID --request-id review-a-finish
```

服务记录开始、结束时间及包含等待在内的墙钟耗时。Observation 属于节点，不绑定会话。如果运行时或供应商提供本步骤的用量计数，结束时传入 `--input-tokens N`、`--output-tokens N` 和 `--usage-source SOURCE`；`--usage-ref REF` 用于标识来源记录。缺少计数时省略对应参数：**未知保留为 `null`，实测零值保留为零**。使用步骤自身的计数，避免在多个 observation 中重复填写累计用量。

界面只汇总节点及其包含的后代。已结束的时间区间按并集合并，父子计时及并行工作不会重复累计耗时；未结束的步骤保留进行中标记。命令执行墙钟时间单独展示。Token 总量汇总已知计数，缺失计数或已开展的叶子节点缺少 observation 时标记覆盖不完整；语义连线和决策复用的证据不计入用量。

## 记录保存在本地

权威 JSON 位于 `.exp-observer/<project-id>/state.json`，证据副本位于其 `evidence/` 目录。原子写入、文件锁、版本检查和幂等请求 ID 支持多个 Agent 增量维护。读取证据时按登记身份校验内容。

请备份**整个 `.exp-observer` 目录**，以保留历史和证据。研究图导出包含引用，不内嵌文件内容。服务绑定 localhost，用于本地运行。

## 示例与开发

[精确检索研究](examples/real-study/report.md)比较三种检索方法，并在纳入索引构建成本后重新审视决策。[独立接续复核](examples/real-study/continuation-review.md)检查推理并提出下一研究分支。[研究脚本](examples/real-study/study.py)在本地生成输入和测量；公开源码包含代码与报告，不附带已填充的研究工作区或归档原始测量。

前端使用 React、TypeScript、React Flow 和 Tailwind CSS，后端与可移植客户端使用 Python。开发、测试和贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

采用 [MIT](LICENSE) 许可。
