import {
  ArrowRight,
  ArrowUpRight,
  Box,
  CheckCircle2,
  ChevronRight,
  Diamond,
  FileText,
  FlaskConical,
  GitBranch,
  Lightbulb,
  Link2,
  Plus,
  Target,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  descendants,
  kinds,
  isExecutionRun,
  relations,
  statuses,
  type Artifact,
  type Operation,
  type Project,
  type ResearchNode,
  type NodeTab,
} from "../model";

import { Badge, date, IconButton, kindIcon } from "./Primitives";
import { NodeUsagePanel } from "./NodeUsagePanel";
import { MetricDetails } from "./MetricDetails";
import { nodePresentation } from "../node-presentation";
import { ProjectHostUsage } from "./HostUsage";
export function ProjectInspector({
  project,
  onAdd,
  onSelect,
  onClose,
}: {
  project: Project;
  onAdd: () => void;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const active = project.nodes.filter((n) => n.status === "active");
  const decisions = project.decisions;
  return (
    <>
      <div className="inspector-heading">
        <span>
          <Target size={14} />
          研究概览
        </span>
        <IconButton label="关闭详情" onClick={onClose}>
          <X size={15} />
        </IconButton>
      </div>
      <div className="inspector-scroll">
        <h2 className="inspector-title">{project.name}</h2>
        <p className="inspector-summary">{project.description}</p>
        <div className="project-stats">
          <div>
            <strong>{project.nodes.length}</strong>
            <span>研究节点</span>
          </div>
          <div>
            <strong>{project.runs.filter(isExecutionRun).length}</strong>
            <span>实验运行</span>
          </div>
          <div>
            <strong>{project.artifacts.length}</strong>
            <span>原始证据</span>
          </div>
        </div>
        <ProjectHostUsage project={project} />
        <div className="inspector-section-title">
          <span>开放问题与方向</span>
          <span>{active.length}</span>
        </div>
        {active.map((n) => (
          <button
            className="active-path"
            key={n.id}
            onClick={() => onSelect(n.id)}
          >
            <span className="path-icon">
              <GitBranch size={15} />
            </span>
            <span>
              <strong>{n.title}</strong>
              <small>{n.nextAction || n.summary}</small>
            </span>
            <ChevronRight size={14} />
          </button>
        ))}
        {decisions.length > 0 && (
          <>
            <div className="inspector-section-title">
              <span>最近结论</span>
            </div>
            {decisions.slice(-2).map((d) => (
              <div className="finding-summary" key={d.id}>
                <Lightbulb size={16} />
                <strong>{d.title}</strong>
                <p>{d.conclusion}</p>
                {d.nextAction && (
                  <div>
                    <ArrowRight size={12} />
                    {d.nextAction}
                  </div>
                )}
              </div>
            ))}
          </>
        )}
        <button className="button wide subtle" onClick={onAdd}>
          <Plus size={14} />
          继续探索
        </button>
      </div>
      <div className="inspector-bottom">
        <span className="tiny-dot accent" />
        记录持续保存在本地<span>r{project.revision}</span>
      </div>
    </>
  );
}

export function NodeInspector({
  node,
  project,
  busy,
  tab,
  onTabChange,
  mutate,
  onClose,
  onBranch,
  onChild,
  onDelete,
  onArtifact,
  onSelect,
  onConnect,
}: {
  node: ResearchNode;
  project: Project;
  busy: boolean;
  tab: NodeTab;
  onTabChange: (tab: NodeTab) => void;
  mutate: (ops: Operation[]) => Promise<boolean>;
  onClose: () => void;
  onBranch: () => void;
  onChild: () => void;
  onDelete: () => void;
  onArtifact: (a: Artifact) => void;
  onSelect: (id: string) => void;
  onConnect: () => void;
}) {
  const [editing, setEditing] = useState(false),
    [draft, setDraft] = useState({ ...node });
  useEffect(() => {
    if (!editing) setDraft({ ...node });
  }, [node]);
  const runs = project.runs.filter((r) => r.nodeId === node.id);
  const presentation = nodePresentation(project, node);
  const relatedArtifacts = project.artifacts.filter(
    (a) =>
      a.nodeId === node.id ||
      runs.some((r) => r.id === a.runId || r.artifactIds.includes(a.id)),
  );
  const children = project.nodes.filter((n) => n.parentId === node.id);
  const Icon = kindIcon[node.kind] || Box;
  const save = async () => {
    if (!draft.title.trim()) return;
    if (
      await mutate([
        {
          op: "node.update",
          data: {
            id: node.id,
            title: draft.title,
            summary: draft.summary,
            conclusion: draft.conclusion || "",
            notes: draft.notes,
            nextAction: draft.nextAction,
            parentId: draft.parentId,
            isContainer: draft.isContainer ?? draft.kind === "group",
            tags:
              typeof draft.tags === "string"
                ? (draft.tags as string).split(",")
                : draft.tags,
            importance: draft.importance || "normal",
            importanceReason: draft.importanceReason || "",
            pauseReason: draft.pauseReason || "",
            resumeWhen: draft.resumeWhen || "",
          },
        },
      ])
    )
      setEditing(false);
  };
  return (
    <>
      <div className="inspector-heading">
        <span>
          <Icon size={14} />
          {kinds[node.kind] || node.kind}
        </span>
        <div>
          <IconButton label="新增子节点" onClick={onChild}>
            <Plus size={14} />
          </IconButton>
          <IconButton label="关闭详情" onClick={onClose}>
            <X size={15} />
          </IconButton>
        </div>
      </div>
      <div className="inspector-scroll">
        <div className="node-detail-title">
          {editing ? (
            <input
              autoFocus
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            />
          ) : (
            <h2>{node.title}</h2>
          )}
          <select
            aria-label="节点状态"
            disabled={busy || editing}
            value={node.status}
            className={`status-select status-${node.status}`}
            onChange={(e) =>
              void mutate([
                {
                  op: "node.update",
                  data: { id: node.id, status: e.target.value },
                },
              ])
            }
          >
            {[
              "proposed",
              "active",
              "completed",
              "paused",
              "rejected",
              "failed",
            ].map((s) => (
              <option key={s} value={s}>
                {statuses[s]}
              </option>
            ))}
          </select>
          <button
            className={`importance-toggle ${node.importance === "critical" ? "selected" : ""}`}
            aria-pressed={node.importance === "critical"}
            disabled={busy || editing}
            onClick={() =>
              void mutate([
                {
                  op: "node.update",
                  data: {
                    id: node.id,
                    importance:
                      node.importance === "critical" ? "normal" : "critical",
                  },
                },
              ])
            }
          >
            <Diamond size={12} />
            关键节点
          </button>
        </div>
        <div className="detail-tabs">
          {[
            ["overview", "概览"],
            ["runs", `记录 ${runs.length}`],
            ["evidence", `证据 ${relatedArtifacts.length}`],
            ["usage", "用量"],
          ].map(([id, label]) => (
            <button
              key={id}
              className={tab === id ? "selected" : ""}
              onClick={() => onTabChange(id as NodeTab)}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "usage" ? (
          <NodeUsagePanel
            project={project}
            node={node}
            busy={busy}
            mutate={mutate}
          />
        ) : tab === "overview" ? (
          <>
            {editing ? (
              <div className="edit-fields">
                <label>
                  显示方式
                  <select
                    value={
                      (draft.isContainer ?? draft.kind === "group")
                        ? "container"
                        : "node"
                    }
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        isContainer: e.target.value === "container",
                      })
                    }
                  >
                    <option value="node">普通节点</option>
                    <option value="container">容器分组</option>
                  </select>
                </label>
                <label>
                  节点重要性
                  <select
                    value={draft.importance || "normal"}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        importance: e.target.value as "normal" | "critical",
                      })
                    }
                  >
                    <option value="normal">普通节点</option>
                    <option value="critical">关键节点</option>
                  </select>
                </label>
                {draft.importance === "critical" && (
                  <label>
                    影响主结论的原因
                    <textarea
                      value={draft.importanceReason || ""}
                      onChange={(e) =>
                        setDraft({ ...draft, importanceReason: e.target.value })
                      }
                    />
                  </label>
                )}
                {node.status === "paused" && (
                  <>
                    <label>
                      挂起原因
                      <textarea
                        value={draft.pauseReason || ""}
                        onChange={(e) =>
                          setDraft({ ...draft, pauseReason: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      恢复条件
                      <textarea
                        value={draft.resumeWhen || ""}
                        onChange={(e) =>
                          setDraft({ ...draft, resumeWhen: e.target.value })
                        }
                      />
                    </label>
                  </>
                )}
                <label>
                  结论
                  <textarea
                    placeholder="用一句话说明这一步发现了什么"
                    value={draft.conclusion || ""}
                    onChange={(e) =>
                      setDraft({ ...draft, conclusion: e.target.value })
                    }
                  />
                </label>
                <label>
                  摘要
                  <textarea
                    value={draft.summary}
                    onChange={(e) =>
                      setDraft({ ...draft, summary: e.target.value })
                    }
                  />
                </label>
                <label>
                  详细记录
                  <textarea
                    rows={5}
                    value={draft.notes || ""}
                    onChange={(e) =>
                      setDraft({ ...draft, notes: e.target.value })
                    }
                  />
                </label>
                <label>
                  下一步
                  <textarea
                    value={draft.nextAction || ""}
                    onChange={(e) =>
                      setDraft({ ...draft, nextAction: e.target.value })
                    }
                  />
                </label>
                <label>
                  所属容器
                  <select
                    value={draft.parentId || ""}
                    onChange={(e) =>
                      setDraft({ ...draft, parentId: e.target.value || null })
                    }
                  >
                    <option value="">项目根目录</option>
                    {project.nodes
                      .filter(
                        (n) =>
                          n.id !== node.id &&
                          !descendants(project.nodes, node.id).includes(n.id),
                      )
                      .map((n) => (
                        <option key={n.id} value={n.id}>
                          {n.title}
                        </option>
                      ))}
                  </select>
                </label>
                <div className="form-actions">
                  <button
                    className="button subtle"
                    onClick={() => setEditing(false)}
                  >
                    取消
                  </button>
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => void save()}
                  >
                    保存
                  </button>
                </div>
              </div>
            ) : (
              <>
                {presentation.source && (
                  <div className="node-context-note">
                    <strong>{presentation.source}</strong>
                    <p>
                      {presentation.conclusion ||
                        node.conclusion ||
                        node.summary}
                    </p>
                  </div>
                )}
                <p className="inspector-summary">
                  {node.summary || "暂无摘要"}
                </p>
                {node.importance === "critical" && node.importanceReason && (
                  <div className="node-context-note critical-note">
                    <strong>
                      <Diamond size={12} />
                      影响主结论
                    </strong>
                    <p>{node.importanceReason}</p>
                  </div>
                )}
                {node.status === "paused" &&
                  (node.pauseReason || node.resumeWhen) && (
                    <div className="node-context-note pause-note">
                      {node.pauseReason && (
                        <>
                          <strong>挂起原因</strong>
                          <p>{node.pauseReason}</p>
                        </>
                      )}
                      {node.resumeWhen && (
                        <>
                          <strong>恢复条件</strong>
                          <p>{node.resumeWhen}</p>
                        </>
                      )}
                    </div>
                  )}
                {node.tags?.length > 0 && (
                  <div className="tags">
                    {node.tags.map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </div>
                )}
                {node.notes && (
                  <div className="detail-note">
                    <div className="inspector-section-title">
                      <span>研究记录</span>
                    </div>
                    <p>{node.notes}</p>
                  </div>
                )}
                {node.nextAction && (
                  <div className="next-action">
                    <span>
                      <ArrowUpRight size={14} />
                      下一步
                    </span>
                    <p>{node.nextAction}</p>
                  </div>
                )}
                <button
                  className="text-button edit-link"
                  onClick={() => setEditing(true)}
                >
                  <FileText size={13} />
                  编辑记录
                </button>
              </>
            )}
            {children.length > 0 && (
              <>
                <div className="inspector-section-title">
                  <span>子节点</span>
                  <span>{children.length}</span>
                </div>
                {children.map((n) => (
                  <button
                    key={n.id}
                    className="related-row"
                    onClick={() => onSelect(n.id)}
                  >
                    <Box size={13} />
                    <span>{n.title}</span>
                    <ChevronRight size={12} />
                  </button>
                ))}
              </>
            )}
            <div className="inspector-section-title">
              <span>研究关系</span>
              <button onClick={onConnect}>
                <Plus size={13} />
              </button>
            </div>
            {project.edges
              .filter((e) => e.source === node.id || e.target === node.id)
              .map((e) => {
                const other = project.nodes.find(
                  (n) => n.id === (e.source === node.id ? e.target : e.source),
                );
                return (
                  <button
                    className="related-row"
                    key={e.id}
                    onClick={() => other && onSelect(other.id)}
                  >
                    <GitBranch size={13} />
                    <span>{other?.title}</span>
                    <small>
                      {e.label || relations[e.relation] || e.relation}
                    </small>
                  </button>
                );
              })}
            {project.decisions
              .filter((d) => d.nodeId === node.id)
              .map((d) => (
                <div className="finding-summary" key={d.id}>
                  <CheckCircle2 size={16} />
                  <strong>{d.title}</strong>
                  <p>{d.conclusion}</p>
                  <small>{d.scope}</small>
                </div>
              ))}
          </>
        ) : tab === "runs" ? (
          <>
            {runs.length ? (
              runs.map((r) => (
                <div className="inspector-run" key={r.id}>
                  <div>
                    <FlaskConical size={14} />
                    <strong>{r.title}</strong>
                    {!isExecutionRun(r) && <small>结果记录</small>}
                    <Badge status={r.status} />
                  </div>
                  <MetricDetails metrics={r.metrics || {}} />
                  {project.assessments
                    .filter((a) => a.runId === r.id)
                    .map((a) => (
                      <details className="raw-metrics" key={a.id}>
                        <summary>评估 · {a.rubric}</summary>
                        {a.conclusion && <p>{a.conclusion}</p>}
                        <MetricDetails metrics={a.metrics} />
                      </details>
                    ))}
                  {r.events?.slice(-3).map((e) => (
                    <div className="mini-event" key={e.id}>
                      <span className="tiny-dot" />
                      {e.message}
                    </div>
                  ))}
                </div>
              ))
            ) : (
              <div className="small-empty">暂无运行记录</div>
            )}
          </>
        ) : (
          <>
            {relatedArtifacts.length ? (
              relatedArtifacts.map((a) => (
                <button
                  className="artifact-row"
                  key={a.id}
                  onClick={() => onArtifact(a)}
                >
                  <FileText size={17} />
                  <span>
                    <strong>{a.title}</strong>
                    <small>
                      {a.bytes} bytes · {a.mime}
                    </small>
                  </span>
                  <ArrowUpRight size={13} />
                </button>
              ))
            ) : (
              <div className="small-empty">暂无关联证据</div>
            )}
          </>
        )}
        <div className="metadata">
          <span>节点标识</span>
          <code>{node.id}</code>
          {node.createdAt && (
            <>
              <span>创建时间</span>
              <span>{date(node.createdAt)}</span>
            </>
          )}
        </div>
      </div>
      <div className="inspector-actions">
        <button className="button primary" onClick={onBranch}>
          <GitBranch size={14} />
          从此处分支
        </button>
        <IconButton label="移除节点，可从历史恢复" onClick={onDelete}>
          <Trash2 size={15} />
        </IconButton>
      </div>
    </>
  );
}

export function EdgeInspector({
  edge,
  mutate,
  onDelete,
}: {
  edge: any;
  mutate: (ops: Operation[]) => Promise<boolean>;
  onDelete: () => void;
}) {
  const [draft, setDraft] = useState(edge);
  useEffect(() => setDraft(edge), [edge]);
  return (
    <>
      <div className="inspector-heading">
        <span>
          <Link2 size={14} />
          研究关系
        </span>
      </div>
      <div className="inspector-scroll edit-fields">
        <label>
          关系
          <select
            value={draft.relation}
            onChange={(e) => setDraft({ ...draft, relation: e.target.value })}
          >
            {Object.entries(relations).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          说明
          <input
            value={draft.label || ""}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
          />
        </label>
        <label>
          依据
          <select
            value={draft.basis || "unknown"}
            onChange={(e) => setDraft({ ...draft, basis: e.target.value })}
          >
            <option value="observed">有记录支持</option>
            <option value="hypothesis">待验证</option>
            <option value="unknown">未知</option>
          </select>
        </label>
        <button
          className="button primary"
          onClick={() => void mutate([{ op: "edge.update", data: draft }])}
        >
          保存关系
        </button>
        <button className="button danger" onClick={onDelete}>
          <Trash2 size={14} />
          移除关系
        </button>
      </div>
    </>
  );
}
