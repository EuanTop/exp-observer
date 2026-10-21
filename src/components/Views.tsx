import {
  Activity,
  ArrowUpRight,
  Check,
  ChevronDown,
  Files,
  FileText,
  FlaskConical,
  History,
  LayoutGrid,
  Plus,
  Search,
  Settings2,
} from "lucide-react";
import { useState } from "react";
import {
  effectiveAssessments,
  formatMetric,
  metricLabel,
  statuses,
  type Artifact,
  type Project,
  type Run,
} from "../model";

import { Badge, date, time } from "./Primitives";
export function RunsView({
  project,
  onArtifact,
  onNode,
}: {
  project: Project;
  onArtifact: (a: Artifact) => void;
  onNode: (id: string) => void;
}) {
  const [filter, setFilter] = useState("all"),
    [expanded, setExpanded] = useState<string | null>(null);
  const runs = [...project.runs]
    .reverse()
    .filter((r) => filter === "all" || r.status === filter);
  return (
    <div className="data-view">
      <div className="data-heading">
        <div>
          <h2>运行记录</h2>
          <span>{project.runs.length} 次运行</span>
        </div>
        <select
          aria-label="运行状态筛选"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">全部状态</option>
          {["running", "completed", "failed", "invalid", "paused"].map((s) => (
            <option key={s} value={s}>
              {statuses[s]}
            </option>
          ))}
        </select>
      </div>
      <div className="run-table">
        <div className="run-table-head">
          <span>实验运行</span>
          <span>状态</span>
          <span>关键结果</span>
          <span>时间</span>
          <span />
        </div>
        {runs.map((r) => (
          <div className="run-record" key={r.id}>
            <button
              className="run-table-row"
              onClick={() => setExpanded(expanded === r.id ? null : r.id)}
            >
              <span className="run-title">
                <span className={`run-icon status-${r.status}`}>
                  <FlaskConical size={16} />
                </span>
                <span>
                  <strong>{r.title}</strong>
                  <small>
                    {project.nodes.find((n) => n.id === r.nodeId)?.title}
                  </small>
                </span>
              </span>
              <Badge status={r.status} />
              <span className="run-metric">
                {Object.entries(r.metrics || {})
                  .slice(0, 2)
                  .map(([k, v]) => (
                    <span key={k}>
                      <strong>{formatMetric(v)}</strong>
                      <small>{metricLabel(k)}</small>
                    </span>
                  ))}
              </span>
              <time>{date(r.startedAt)}</time>
              <ChevronDown
                className={expanded === r.id ? "rotated" : ""}
                size={14}
              />
            </button>
            {expanded === r.id && (
              <div className="run-expanded">
                <div className="run-expanded-top">
                  <code>{r.id}</code>
                  <button
                    className="text-button"
                    onClick={() => onNode(r.nodeId)}
                  >
                    查看研究节点
                    <ArrowUpRight size={12} />
                  </button>
                </div>
                <div className="run-detail-grid">
                  <div>
                    <div className="section-label">过程事件</div>
                    {r.events?.length ? (
                      r.events.map((e) => (
                        <div className="event-line" key={e.id}>
                          <span
                            className={`event-mark ${e.type === "error" ? "error" : ""}`}
                          />
                          <time>{time(e.at)}</time>
                          <div>
                            <strong>{e.message}</strong>
                            <small>{e.type}</small>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="small-empty">暂无过程事件</div>
                    )}
                  </div>
                  <div>
                    <div className="section-label">实际配置</div>
                    <pre>{JSON.stringify(r.configuration, null, 2)}</pre>
                    <div className="section-label">产物</div>
                    {project.artifacts
                      .filter(
                        (a) =>
                          a.runId === r.id || r.artifactIds?.includes(a.id),
                      )
                      .map((a) => (
                        <button
                          key={a.id}
                          className="related-row"
                          onClick={() => onArtifact(a)}
                        >
                          <FileText size={13} />
                          <span>{a.title}</span>
                          <ArrowUpRight size={12} />
                        </button>
                      ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      {!runs.length && (
        <div className="empty-state compact">
          <FlaskConical size={30} />
          <h3>暂无运行</h3>
          <p>Agent 登记的实验运行会出现在这里</p>
        </div>
      )}
    </div>
  );
}

export function CompareView({ project }: { project: Project }) {
  const completed = project.runs.filter((r) => r.status === "completed");
  const [picked, setPicked] = useState<string[]>(
    completed.slice(-2).map((r) => r.id),
  );
  const allAssessments = effectiveAssessments(project);
  const rubrics = [...new Set(allAssessments.map((a) => a.rubric))];
  const [rubric, setRubric] = useState(rubrics[0] || "");
  const runs = project.runs.filter((r) => picked.includes(r.id));
  const assessmentFor = (r: Run) =>
    allAssessments.find((a) => a.runId === r.id && a.rubric === rubric);
  const metricsFor = (r: Run) =>
    rubric ? assessmentFor(r)?.metrics || {} : r.metrics || {};
  const keys = [...new Set(runs.flatMap((r) => Object.keys(metricsFor(r))))];
  const configKeys = [
    ...new Set(runs.flatMap((r) => Object.keys(r.configuration || {}))),
  ];
  const same = (k: string) =>
    runs.length > 1 &&
    runs.every(
      (r) =>
        JSON.stringify(r.configuration[k]) ===
          JSON.stringify(runs[0].configuration[k]) &&
        r.configuration[k] !== undefined,
    );
  return (
    <div className="data-view compare-view">
      <div className="data-heading">
        <div>
          <h2>对比评估</h2>
          <span>{picked.length} 次运行已选择</span>
        </div>
        <select
          aria-label="评价口径"
          value={rubric}
          onChange={(e) => setRubric(e.target.value)}
        >
          <option value="">运行原始指标</option>
          {rubrics.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <div className="run-picker">
        {project.runs.map((r) => (
          <button
            key={r.id}
            className={picked.includes(r.id) ? "selected" : ""}
            onClick={() =>
              setPicked((p) =>
                p.includes(r.id)
                  ? p.filter((id) => id !== r.id)
                  : p.length < 8
                    ? [...p, r.id]
                    : p,
              )
            }
          >
            <span className="check-box">
              {picked.includes(r.id) && <Check size={11} />}
            </span>
            {r.title}
          </button>
        ))}
      </div>
      {runs.length < 2 ? (
        <div className="empty-state compact">
          <LayoutGrid size={32} />
          <h3>选择至少两次运行</h3>
        </div>
      ) : (
        <>
          <div className="comparison-heading">
            <span>
              <Settings2 size={14} />
              配置与条件
            </span>
            <span className="neutral-badge">
              {configKeys.filter((k) => !same(k)).length} 项差异
            </span>
          </div>
          <div className="comparison-scroll">
            <table className="comparison-table">
              <thead>
                <tr>
                  <th>条件 / 指标</th>
                  {runs.map((r) => (
                    <th key={r.id}>
                      <span className="compare-column-dot" />
                      {r.title}
                      <small>{statuses[r.status] || r.status}</small>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {configKeys.map((k) => (
                  <tr key={k} className={same(k) ? "" : "diff-row"}>
                    <td>
                      {k}
                      <span
                        className={`field-state ${same(k) ? "same" : "diff"}`}
                      >
                        {same(k) ? "一致" : "差异 / 缺失"}
                      </span>
                    </td>
                    {runs.map((r) => (
                      <td key={r.id}>
                        <code>
                          {r.configuration[k] === undefined
                            ? "—"
                            : typeof r.configuration[k] === "object"
                              ? JSON.stringify(r.configuration[k])
                              : String(r.configuration[k])}
                        </code>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="comparison-heading">
            <span>
              <Activity size={14} />
              实验结果
            </span>
            <span className="neutral-badge">{rubric || "原始指标"}</span>
          </div>
          <div className="comparison-scroll">
            <table className="comparison-table metrics-table">
              <thead>
                <tr>
                  <th>指标</th>
                  {runs.map((r) => (
                    <th key={r.id}>{r.title}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => {
                  const values = runs.map((r) => metricsFor(r)[k]);
                  const max = Math.max(
                    ...(values.filter(
                      (v) => typeof v === "number",
                    ) as number[]),
                    0,
                  );
                  return (
                    <tr key={k}>
                      <td>{metricLabel(k)}</td>
                      {runs.map((r) => {
                        const v = metricsFor(r)[k];
                        return (
                          <td key={r.id}>
                            <strong>{formatMetric(v)}</strong>
                            {typeof v === "number" && max > 0 && (
                              <div className="metric-bar">
                                <span
                                  style={{
                                    width: `${Math.max(2, (v / max) * 100)}%`,
                                  }}
                                />
                              </div>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
                {!keys.length && (
                  <tr>
                    <td colSpan={runs.length + 1}>所选口径下尚无指标记录</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="comparison-conclusions">
            {runs.map((r) => {
              const a = assessmentFor(r);
              return (
                <div key={r.id}>
                  <div className="inspector-section-title">
                    <span>{r.title}</span>
                  </div>
                  <p>{a?.conclusion || "尚未登记此口径的评估"}</p>
                  {a?.limitations && (
                    <div className="conclusion-scope">
                      <span>适用范围</span>
                      {a.limitations}
                    </div>
                  )}
                  {a && <code>{a.id}</code>}
                </div>
              );
            })}
          </div>
          {project.assessments.some((a) => a.supersedes) && (
            <details className="assessment-history">
              <summary>
                <History size={14} />
                评估修订历史
              </summary>
              {project.assessments
                .filter((a) => picked.includes(a.runId))
                .map((a) => (
                  <div key={a.id}>
                    <code>{a.id}</code>
                    <span>{a.conclusion}</span>
                    {a.supersedes && <small>修订自 {a.supersedes}</small>}
                  </div>
                ))}
            </details>
          )}
        </>
      )}
    </div>
  );
}

export function EvidenceView({
  project,
  onOpen,
  onAdd,
}: {
  project: Project;
  onOpen: (a: Artifact) => void;
  onAdd: () => void;
}) {
  const [q, setQ] = useState("");
  const list = project.artifacts.filter((a) =>
    `${a.title} ${a.path}`.toLowerCase().includes(q.toLowerCase()),
  );
  return (
    <div className="data-view">
      <div className="data-heading">
        <div>
          <h2>资料与产物</h2>
          <span>{project.artifacts.length} 份原始资料与产物</span>
        </div>
        <button className="button subtle" onClick={onAdd}>
          <Plus size={14} />
          登记文件
        </button>
      </div>
      <div className="table-search">
        <Search size={15} />
        <input
          placeholder="搜索文件…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      <div className="evidence-grid">
        {list.map((a) => (
          <button
            className="evidence-card"
            key={a.id}
            onClick={() => onOpen(a)}
          >
            <div className="evidence-file-icon">
              <FileText size={24} />
              <span>{a.path.split(".").at(-1)?.toUpperCase().slice(0, 6)}</span>
            </div>
            <div className="evidence-card-body">
              <h3>{a.title}</h3>
              <p>{a.path.split(/[\/]/).at(-1)}</p>
              <div>
                <span>
                  {a.bytes < 1024
                    ? `${a.bytes} B`
                    : `${(a.bytes / 1024).toFixed(1)} KB`}
                </span>
                <span>{a.origin === "mock" ? "模拟资料" : "已登记"}</span>
              </div>
            </div>
            <ArrowUpRight size={15} />
          </button>
        ))}
      </div>
      {!list.length && (
        <div className="empty-state compact">
          <Files size={30} />
          <h3>{q ? "没有匹配的文件" : "暂无证据"}</h3>
        </div>
      )}
    </div>
  );
}
