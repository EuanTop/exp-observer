import { intlLocale, t, useLocale } from "../i18n";
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
import { metricLeaves, metricPathLabel, type MetricLeaf } from "../metrics";
import { MetricDetails } from "./MetricDetails";
import {
  effectiveAssessments,
  formatMetric,
  isExecutionRun,
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
  useLocale();
  const [filter, setFilter] = useState("all"),
    [expanded, setExpanded] = useState<string | null>(null);
  const runs = [...project.runs]
    .reverse()
    .filter((r) => filter === "all" || r.status === filter);
  return (
    <div className="data-view">
      <div className="data-heading">
        <div>
          <h2>{t("运行与结果")}</h2>
          <span>
            {t("{count} 次运行", {
              count: project.runs.filter(isExecutionRun).length,
            })}
            {project.runs.some((r) => !isExecutionRun(r))
              ? t(" · {count} 条结果记录", {
                  count: project.runs.filter((r) => !isExecutionRun(r)).length,
                })
              : ""}
          </span>
        </div>
        <select
          aria-label={t("运行状态筛选")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">{t("全部状态")}</option>
          {["running", "completed", "failed", "invalid", "paused"].map((s) => (
            <option key={s} value={s}>
              {t(statuses[s])}
            </option>
          ))}
        </select>
      </div>
      <div className="run-table">
        <div className="run-table-head">
          <span>{t("实验运行")}</span>
          <span>{t("状态")}</span>
          <span>{t("关键结果")}</span>
          <span>{t("时间")}</span>
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
                    {!isExecutionRun(r) && t("结果记录 · ")}
                    {project.nodes.find((n) => n.id === r.nodeId)?.title}
                  </small>
                </span>
              </span>
              <Badge status={r.status} />
              <span className="run-metric">
                {metricLeaves(r.metrics || {})
                  .slice(0, 2)
                  .map(({ key, path, value }) => (
                    <span key={key}>
                      <strong>{formatMetric(value)}</strong>
                      <small>{metricPathLabel(path)}</small>
                    </span>
                  ))}
              </span>
              <time
                title={
                  isExecutionRun(r)
                    ? t("执行开始时间")
                    : t("结果登记时间；执行时间未知")
                }
              >
                {date(isExecutionRun(r) ? r.startedAt : r.capturedAt)}
              </time>
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
                    {t("查看研究节点")}
                    <ArrowUpRight size={12} />
                  </button>
                </div>
                <div className="section-label">{t("原始指标")}</div>
                <MetricDetails metrics={r.metrics || {}} />
                <div className="run-detail-grid">
                  <div>
                    <div className="section-label">{t("过程事件")}</div>
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
                      <div className="small-empty">{t("暂无过程事件")}</div>
                    )}
                  </div>
                  <div>
                    <div className="section-label">{t("实际配置")}</div>
                    <pre>{JSON.stringify(r.configuration, null, 2)}</pre>
                    <div className="section-label">{t("产物")}</div>
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
          <h3>{t("暂无运行")}</h3>
          <p>{t("Agent 登记的实验运行会出现在这里")}</p>
        </div>
      )}
    </div>
  );
}

export function CompareView({ project }: { project: Project }) {
  useLocale();
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
  const metricRows = new Map<string, MetricLeaf>();
  const valuesByRun = new Map(
    runs.map((r) => {
      const rows = metricLeaves(metricsFor(r));
      rows.forEach((row) => metricRows.set(row.key, row));
      return [r.id, new Map(rows.map((row) => [row.key, row.value]))];
    }),
  );
  const keys = [...metricRows.keys()];
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
          <h2>{t("对比评估")}</h2>
          <span>{t("{count} 条记录已选择", { count: picked.length })}</span>
        </div>
        <select
          aria-label={t("评价口径")}
          value={rubric}
          onChange={(e) => setRubric(e.target.value)}
        >
          <option value="">{t("运行原始指标")}</option>
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
          <h3>{t("选择至少两条记录")}</h3>
        </div>
      ) : (
        <>
          <div className="comparison-heading">
            <span>
              <Settings2 size={14} />
              {t("配置与条件")}
            </span>
            <span className="neutral-badge">
              {t("{count} 项差异", {
                count: configKeys.filter((k) => !same(k)).length,
              })}
            </span>
          </div>
          <div className="comparison-scroll">
            <table className="comparison-table">
              <thead>
                <tr>
                  <th>{t("条件 / 指标")}</th>
                  {runs.map((r) => (
                    <th key={r.id}>
                      <span className="compare-column-dot" />
                      {r.title}
                      <small>
                        {statuses[r.status] ? t(statuses[r.status]) : r.status}
                      </small>
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
                        {same(k) ? t("一致") : t("差异 / 缺失")}
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
              {t("实验结果")}
            </span>
            <span className="neutral-badge">{rubric || t("原始指标")}</span>
          </div>
          <div className="comparison-scroll">
            <table className="comparison-table metrics-table">
              <thead>
                <tr>
                  <th>{t("指标")}</th>
                  {runs.map((r) => (
                    <th key={r.id}>{r.title}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => {
                  const values = runs.map((r) => valuesByRun.get(r.id)?.get(k));
                  const max = Math.max(
                    ...(values.filter(
                      (v) => typeof v === "number",
                    ) as number[]),
                    0,
                  );
                  return (
                    <tr key={k}>
                      <td>{metricPathLabel(metricRows.get(k)!.path)}</td>
                      {runs.map((r) => {
                        const v = valuesByRun.get(r.id)?.get(k);
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
                    <td colSpan={runs.length + 1}>
                      {t("所选口径下尚无指标记录")}
                    </td>
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
                  <p>{a?.conclusion || t("尚未登记此口径的评估")}</p>
                  {a?.limitations && (
                    <div className="conclusion-scope">
                      <span>{t("适用范围")}</span>
                      {a.limitations}
                    </div>
                  )}
                  {a && <code>{a.id}</code>}
                  <details className="raw-metrics">
                    <summary>{t("原始指标")}</summary>
                    <MetricDetails metrics={metricsFor(r)} />
                  </details>
                </div>
              );
            })}
          </div>
          {project.assessments.some((a) => a.supersedes) && (
            <details className="assessment-history">
              <summary>
                <History size={14} />
                {t("评估修订历史")}
              </summary>
              {project.assessments
                .filter((a) => picked.includes(a.runId))
                .map((a) => (
                  <div key={a.id}>
                    <code>{a.id}</code>
                    <span>{a.conclusion}</span>
                    {a.supersedes && (
                      <small>{t("修订自 {id}", { id: a.supersedes })}</small>
                    )}
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
  useLocale();
  const [q, setQ] = useState("");
  const list = project.artifacts.filter((a) =>
    `${a.title} ${a.path}`.toLowerCase().includes(q.toLowerCase()),
  );
  return (
    <div className="data-view">
      <div className="data-heading">
        <div>
          <h2>{t("资料与产物")}</h2>
          <span>
            {t("{count} 份原始资料与产物", { count: project.artifacts.length })}
          </span>
        </div>
        <button className="button subtle" onClick={onAdd}>
          <Plus size={14} />
          {t("登记文件")}
        </button>
      </div>
      <div className="table-search">
        <Search size={15} />
        <input
          placeholder={t("搜索文件…")}
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
                    ? `${a.bytes.toLocaleString(intlLocale())} B`
                    : `${(a.bytes / 1024).toLocaleString(intlLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 })} KB`}
                </span>
                <span>{a.origin === "mock" ? t("模拟资料") : t("已登记")}</span>
              </div>
            </div>
            <ArrowUpRight size={15} />
          </button>
        ))}
      </div>
      {!list.length && (
        <div className="empty-state compact">
          <Files size={30} />
          <h3>{q ? t("没有匹配的文件") : t("暂无证据")}</h3>
        </div>
      )}
    </div>
  );
}
