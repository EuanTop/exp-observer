import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  Box,
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  Layers,
  Search,
  X,
} from "lucide-react";
import { t, useLocale } from "../i18n";
import {
  descendants,
  isResearchContainer,
  kinds,
  statuses,
  type Artifact,
  type NodeTab,
  type Project,
} from "../model";
import { buildResearchRows } from "../research-table";
import { nodePresentation } from "../node-presentation";
import { nodeEvidence, nodeImages, subtreeEvidence } from "../image-evidence";
import { formatDuration, formatTokens } from "../usage";
import { originLabel, questionOrigin } from "../question-origin";
import { Badge, kindIcon } from "./Primitives";
import { EvidenceThumbnail } from "./EvidenceMedia";
import "./research-table.css";

type Preferences = {
  expanded: string[];
  query: string;
  status: string;
  kind: string;
  sort: "recorded" | "title" | "time" | "tokens";
  direction: "asc" | "desc";
};
const defaults: Preferences = {
  expanded: [],
  query: "",
  status: "",
  kind: "",
  sort: "recorded",
  direction: "asc",
};
function savedPreferences(id: string): Preferences {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(`exp-observer-table:${id}`) || "null",
    );
    if (!value || typeof value !== "object") return defaults;
    return {
      expanded: Array.isArray(value.expanded)
        ? value.expanded.filter((id: unknown) => typeof id === "string")
        : [],
      query: typeof value.query === "string" ? value.query : "",
      status: typeof value.status === "string" ? value.status : "",
      kind: typeof value.kind === "string" ? value.kind : "",
      sort: ["recorded", "title", "time", "tokens"].includes(value.sort)
        ? value.sort
        : "recorded",
      direction: value.direction === "desc" ? "desc" : "asc",
    };
  } catch {
    return defaults;
  }
}
export function ResearchTable({
  project,
  selectedId,
  activeNodeIds = [],
  onInspect,
  onGraph,
  onArtifact,
}: {
  project: Project;
  selectedId?: string;
  activeNodeIds?: string[];
  onInspect: (id: string, tab: NodeTab) => void;
  onGraph: (id: string) => void;
  onArtifact: (artifact: Artifact) => void;
}) {
  const { locale } = useLocale();
  const [preferences, setPreferences] = useState(() =>
    savedPreferences(project.id),
  );
  const tableRef = useRef<HTMLTableElement>(null);
  const { query, status, kind, sort, direction } = preferences;
  const expandedIds = useMemo(
    () => new Set(preferences.expanded),
    [preferences.expanded],
  );
  const filtering = !!(query.trim() || status || kind);
  useEffect(() => {
    try {
      sessionStorage.setItem(
        `exp-observer-table:${project.id}`,
        JSON.stringify(preferences),
      );
    } catch {}
  }, [project.id, preferences]);
  const rows = useMemo(
    () =>
      buildResearchRows(project, {
        expandedIds,
        query,
        status,
        kind,
        sort,
        direction,
      }),
    [project, expandedIds, query, status, kind, sort, direction, locale],
  );
  useEffect(() => {
    if (!selectedId) return;
    const ancestors: string[] = [],
      seen = new Set<string>();
    let current = project.nodes.find((node) => node.id === selectedId);
    while (current?.parentId && !seen.has(current.parentId)) {
      seen.add(current.parentId);
      ancestors.push(current.parentId);
      current = project.nodes.find((node) => node.id === current!.parentId);
    }
    setPreferences((previous) =>
      ancestors.every((id) => previous.expanded.includes(id))
        ? previous
        : {
            ...previous,
            expanded: [...new Set([...previous.expanded, ...ancestors])],
          },
    );
  }, [selectedId, project.id]);
  const scrolledSelection = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!selectedId || scrolledSelection.current === selectedId) return;
    const button = tableRef.current?.querySelector<HTMLButtonElement>(
      `[data-row-title="${CSS.escape(selectedId)}"]`,
    );
    if (button) {
      button.scrollIntoView({ block: "nearest", inline: "nearest" });
      scrolledSelection.current = selectedId;
    }
  }, [selectedId, rows]);
  const evidence = useMemo(
    () =>
      new Map(
        rows.map(({ node, hasChildren }) => {
          const records = hasChildren
            ? subtreeEvidence(project, node.id)
            : nodeEvidence(project, node.id);
          return [
            node.id,
            { records, images: nodeImages(project, node.id, hasChildren) },
          ];
        }),
      ),
    [rows, project],
  );
  const update = (value: Partial<Preferences>) =>
    setPreferences((previous) => ({ ...previous, ...value }));
  const toggle = (id: string) =>
    setPreferences((previous) => ({
      ...previous,
      expanded: previous.expanded.includes(id)
        ? previous.expanded.filter((key) => key !== id)
        : [...previous.expanded, id],
    }));
  const focusRow = (id: string) =>
    tableRef.current
      ?.querySelector<HTMLButtonElement>(`[data-row-title="${CSS.escape(id)}"]`)
      ?.focus();
  const keyNavigation = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    const row = rows[index];
    if (
      ![
        "ArrowDown",
        "ArrowUp",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
      ].includes(event.key)
    )
      return;
    event.preventDefault();
    if (event.key === "ArrowDown")
      focusRow(rows[Math.min(rows.length - 1, index + 1)].node.id);
    if (event.key === "ArrowUp") focusRow(rows[Math.max(0, index - 1)].node.id);
    if (event.key === "Home") focusRow(rows[0].node.id);
    if (event.key === "End") focusRow(rows[rows.length - 1].node.id);
    if (event.key === "ArrowRight" && row.hasChildren) {
      if (!row.expanded && !filtering) toggle(row.node.id);
      else if (rows[index + 1]?.depth > row.depth)
        focusRow(rows[index + 1].node.id);
    }
    if (event.key === "ArrowLeft") {
      if (row.expanded && !filtering) toggle(row.node.id);
      else {
        for (let i = index - 1; i >= 0; i--)
          if (rows[i].depth < row.depth) {
            focusRow(rows[i].node.id);
            break;
          }
      }
    }
  };
  return (
    <section className="research-table-view" aria-label={t("研究表格")}>
      <div className="research-table-tools">
        <label className="research-table-search">
          <Search size={14} />
          <input
            aria-label={t("搜索节点、结论或记录…")}
            placeholder={t("搜索节点、结论或记录…")}
            value={query}
            onChange={(event) => update({ query: event.target.value })}
          />
          {query && (
            <button
              aria-label={t("清除筛选")}
              onClick={() => update({ query: "" })}
            >
              <X size={13} />
            </button>
          )}
        </label>
        <select
          aria-label={t("表格状态筛选")}
          value={status}
          onChange={(event) => update({ status: event.target.value })}
        >
          <option value="">{t("全部状态")}</option>
          {[...new Set(project.nodes.map((n) => n.status))].map((value) => (
            <option key={value} value={value}>
              {t(statuses[value] || value)}
            </option>
          ))}
        </select>
        <select
          aria-label={t("表格类型筛选")}
          value={kind}
          onChange={(event) => update({ kind: event.target.value })}
        >
          <option value="">{t("全部类型")}</option>
          {[...new Set(project.nodes.map((n) => n.kind))].map((value) => (
            <option key={value} value={value}>
              {t(kinds[value] || value)}
            </option>
          ))}
        </select>
        <select
          aria-label={t("表格排序")}
          value={sort}
          onChange={(event) =>
            update({ sort: event.target.value as Preferences["sort"] })
          }
        >
          {(
            [
              ["recorded", "记录顺序"],
              ["title", "标题顺序"],
              ["time", "时间排序"],
              ["tokens", "用量排序"],
            ] as const
          ).map(([value, label]) => (
            <option key={value} value={value}>
              {t(label)}
            </option>
          ))}
        </select>
        <button
          className="table-tool"
          aria-label={t(direction === "asc" ? "降序" : "升序")}
          title={t(direction === "asc" ? "升序" : "降序")}
          onClick={() =>
            update({ direction: direction === "asc" ? "desc" : "asc" })
          }
        >
          {direction === "asc" ? (
            <ArrowUp size={14} />
          ) : (
            <ArrowDown size={14} />
          )}
        </button>
        {filtering && (
          <button
            className="table-tool"
            onClick={() => update({ query: "", status: "", kind: "" })}
          >
            {t("清除筛选")}
          </button>
        )}
        <div className="table-expand-tools">
          <button
            className="table-tool"
            disabled={filtering}
            title={filtering ? t("筛选结果保留完整路径") : t("展开全部")}
            onClick={() =>
              update({ expanded: project.nodes.map((node) => node.id) })
            }
          >
            <ChevronsUpDown size={14} />
            <span>{t("展开全部")}</span>
          </button>
          <button
            className="table-tool"
            disabled={filtering}
            title={filtering ? t("筛选结果保留完整路径") : t("折叠全部")}
            onClick={() => update({ expanded: [] })}
          >
            <ChevronsDownUp size={14} />
            <span>{t("折叠全部")}</span>
          </button>
        </div>
      </div>
      <div className="research-table-scroll">
        <table
          ref={tableRef}
          className="research-table"
          role="treegrid"
          aria-label={t("研究表格")}
          aria-rowcount={rows.length + 1}
        >
          <thead>
            <tr>
              {[
                "节点",
                "类型",
                "状态",
                "当前结论",
                "时间",
                "Token",
                "证据",
                "提出依据",
                "",
              ].map((label, index) => (
                <th key={index} scope="col">
                  {label ? t(label) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const { node, usage } = row;
              const presentation = nodePresentation(project, node);
              const group = isResearchContainer(project.nodes, node);
              const Icon = group ? Layers : kindIcon[node.kind] || Box;
              const attached = evidence.get(node.id)!;
              const image = attached.images[0];
              const time =
                usage.elapsedMs !== null
                  ? { value: usage.elapsedMs, label: "步骤计时" }
                  : usage.runMs !== null
                    ? { value: usage.runMs, label: "命令执行" }
                    : usage.externalReportedMs !== null
                      ? { value: usage.externalReportedMs, label: "执行器报告" }
                      : { value: usage.externalTaskMs, label: "任务跨度" };
              const processing = activeNodeIds.some(
                (id) =>
                  id === node.id ||
                  (row.hasChildren &&
                    descendants(project.nodes, node.id).includes(id)),
              );
              const origin = questionOrigin(node);
              return (
                <tr
                  key={node.id}
                  aria-level={row.depth + 1}
                  aria-expanded={row.hasChildren ? row.expanded : undefined}
                  aria-selected={selectedId === node.id}
                  className={`${row.contextOnly ? "context-row" : ""} ${selectedId === node.id ? "selected-row" : ""}`}
                >
                  <td>
                    <div
                      className="table-node-cell"
                      style={{ paddingLeft: Math.min(row.depth, 20) * 16 }}
                    >
                      {row.hasChildren ? (
                        <button
                          className="table-fold"
                          disabled={filtering}
                          aria-expanded={row.expanded}
                          aria-label={t(
                            row.expanded ? "折叠 {title}" : "展开 {title}",
                            { title: node.title },
                          )}
                          title={
                            filtering ? t("筛选结果保留完整路径") : undefined
                          }
                          onClick={() => toggle(node.id)}
                        >
                          {row.expanded ? (
                            <ChevronDown size={14} />
                          ) : (
                            <ChevronRight size={14} />
                          )}
                        </button>
                      ) : (
                        <span className="table-fold-spacer" />
                      )}
                      <Icon size={14} />
                      <div>
                        <button
                          className="table-node-title"
                          data-row-title={node.id}
                          onKeyDown={(event) => keyNavigation(event, index)}
                          onClick={() => onInspect(node.id, "overview")}
                        >
                          {node.title}
                        </button>
                        {row.hasChildren && (
                          <small>
                            {t("{count} 个子节点", { count: row.childCount })}
                          </small>
                        )}
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="table-kind">
                      {t(kinds[node.kind] || node.kind)}
                    </span>
                  </td>
                  <td>
                    <Badge status={node.status} />
                    {processing && (
                      <span
                        className="table-running"
                        title={t(row.hasChildren ? "内部执行中" : "处理中")}
                      >
                        <Activity size={11} />
                        {t("运行中")}
                      </span>
                    )}
                  </td>
                  <td>
                    <button
                      className="table-conclusion"
                      title={presentation.conclusion || presentation.summary}
                      onClick={() => onInspect(node.id, "overview")}
                    >
                      {(
                        presentation.conclusion ||
                        presentation.summary ||
                        "—"
                      ).replace(/^#{1,6}\s+/gm, "")}
                    </button>
                  </td>
                  <td>
                    <button
                      className="table-metric"
                      title={t("查看计量详情")}
                      onClick={() => onInspect(node.id, "usage")}
                    >
                      <strong>
                        {time.value === null ? "—" : formatDuration(time.value)}
                        {usage.elapsedPartial && usage.elapsedMs !== null
                          ? "+"
                          : ""}
                      </strong>
                      <small>
                        {time.value !== null ? t(time.label) : t("未采集")}
                        {row.hasChildren && time.value !== null
                          ? ` · ${t("容器汇总")}`
                          : ""}
                      </small>
                    </button>
                  </td>
                  <td>
                    <button
                      className="table-metric"
                      title={t("查看计量详情")}
                      onClick={() => onInspect(node.id, "usage")}
                    >
                      <strong>
                        {formatTokens(usage.totalTokens)}
                        {usage.totalTokens !== null && usage.tokensPartial
                          ? "+"
                          : ""}
                      </strong>
                      <small>
                        {usage.totalTokens === null
                          ? t("未采集")
                          : t(
                              usage.tokenScope === "execution"
                                ? "被测任务用量"
                                : "研究 Agent 用量",
                            )}
                      </small>
                    </button>
                  </td>
                  <td>
                    <div className="table-evidence">
                      {image && (
                        <button
                          className="table-image"
                          aria-label={t("查看图片：{title}", {
                            title: image.artifact.title,
                          })}
                          onClick={() => onArtifact(image.artifact)}
                        >
                          <EvidenceThumbnail
                            projectId={project.id}
                            artifact={image.artifact}
                          />
                        </button>
                      )}
                      <button
                        className="table-evidence-count"
                        title={t("查看 {count} 份证据", {
                          count: attached.records.length,
                        })}
                        onClick={() => onInspect(node.id, "evidence")}
                      >
                        {attached.records.length || "—"}
                      </button>
                    </div>
                  </td>
                  <td>
                    {origin || node.kind === "question" ? (
                      <button
                        className="table-origin"
                        title={origin?.reason || originLabel(node)}
                        onClick={() => onInspect(node.id, "overview")}
                      >
                        {originLabel(node)}
                        {origin?.retrospective && (
                          <small>{t("事后补记")}</small>
                        )}
                      </button>
                    ) : (
                      <span className="table-muted">—</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="table-graph-link"
                      aria-label={t("在研究图中定位 {title}", {
                        title: node.title,
                      })}
                      title={t("研究图")}
                      onClick={() => onGraph(node.id)}
                    >
                      <ArrowUpRight size={15} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && (
          <div className="research-table-empty">
            {t(filtering ? "无匹配节点" : "表格暂无节点")}
            {filtering && (
              <button
                className="text-button"
                onClick={() => update({ query: "", status: "", kind: "" })}
              >
                {t("清除筛选")}
              </button>
            )}
          </div>
        )}
      </div>
      <div className="research-table-footer">
        {t("{count} 行 · {total} 个节点", {
          count: rows.length,
          total: project.nodes.length,
        })}
      </div>
    </section>
  );
}
