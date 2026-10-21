import {
  CheckCircle2,
  Copy,
  Download,
  FolderOpen,
  Terminal,
  X,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api, type AgentSetup } from "../api";
import { agentCommand, agentPrompt } from "../agent-command";
import {
  ancestry,
  kinds,
  NODE_SIZE,
  relations,
  uid,
  type Artifact,
  type Operation,
  type Project,
} from "../model";

import { IconButton } from "./Primitives";
import { WorkspaceEnrollment } from "./WorkspaceEnrollment";
export type DialogState = {
  type: "node" | "project" | "artifact" | "branch" | "group" | "connect";
  parentId?: string | null;
  source?: string;
} | null;
export function ArtifactDialog({
  artifact: a,
  project,
  onClose,
}: {
  artifact: Artifact;
  project: Project;
  onClose: () => void;
}) {
  const [content, setContent] = useState(""),
    [error, setError] = useState(""),
    [raw, setRaw] = useState(false),
    [verified, setVerified] = useState(false),
    [imageSource, setImageSource] = useState(""),
    [offset, setOffset] = useState(0);
  const pageSize = 262144;
  const endpoint = `/api/projects/${encodeURIComponent(project.id)}/artifacts/${encodeURIComponent(a.id)}`;
  const textLike =
    a.mime.startsWith("text/") || /json|javascript|xml/.test(a.mime);
  const imageLike =
    /^image\/(png|jpeg|gif|webp)$/.test(a.mime) && a.bytes <= 5 * 1024 * 1024;
  useEffect(() => {
    const controller = new AbortController();
    setVerified(false);
    setError("");
    setContent("");
    setImageSource("");
    fetch(
      textLike
        ? `${endpoint}/content?offset=${offset}&limit=${pageSize}`
        : imageLike
          ? `${endpoint}/content`
          : `${endpoint}/metadata`,
      { signal: controller.signal },
    )
      .then(async (r) => {
        if (!r.ok) {
          const d = await r.json();
          throw new Error(d.error);
        }
        if (imageLike) {
          const bytes = await r.arrayBuffer();
          const source = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result));
            reader.onerror = () => reject(new Error("图片读取失败"));
            reader.readAsDataURL(new Blob([bytes], { type: a.mime }));
          });
          if (!controller.signal.aborted) setImageSource(source);
          return "";
        }
        return textLike ? r.text() : "";
      })
      .then((t) => {
        if (controller.signal.aborted) return;
        setContent(t);
        setVerified(true);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [endpoint, offset, textLike, imageLike, a.mime]);
  let json: unknown;
  try {
    json = JSON.parse(content);
  } catch {}
  const csv =
    a.path.endsWith(".csv") &&
    !raw &&
    offset === 0 &&
    content &&
    !content.includes('"')
      ? content
          .trim()
          .split(/\r?\n/)
          .map((line) => line.split(","))
      : null;
  return (
    <div
      className="modal-backdrop evidence-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="evidence-modal">
        <div className="modal-heading">
          <div>
            <span className="eyebrow">SOURCE EVIDENCE</span>
            <h2>{a.title}</h2>
          </div>
          <IconButton label="关闭证据" onClick={onClose}>
            <X size={18} />
          </IconButton>
        </div>
        <div className="evidence-meta">
          <span className={verified ? "verified" : ""}>
            <CheckCircle2 size={13} />
            {verified ? "指纹一致" : error ? "无法校验" : "校验中"}
          </span>
          <span>{a.bytes} bytes</span>
          <span>{a.mime}</span>
        </div>
        <div className="file-location">
          <FolderOpen size={13} />
          <span>{a.path}</span>
        </div>
        <div className="hash-line">
          SHA-256<code>{a.sha256}</code>
        </div>
        <div className="evidence-mode">
          {textLike ? (
            <>
              <button
                className={!raw ? "selected" : ""}
                onClick={() => setRaw(false)}
              >
                阅读视图
              </button>
              <button
                className={raw ? "selected" : ""}
                onClick={() => setRaw(true)}
              >
                原文
              </button>
            </>
          ) : (
            <span className="evidence-preview-label">
              {imageLike ? "图片预览" : "文件信息"}
            </span>
          )}
          <a
            className="download-evidence"
            href={`${endpoint}/content`}
            download={a.path.split(/[\\/]/).at(-1) || "evidence"}
            aria-disabled={!verified}
            onClick={(e) => {
              if (!verified) e.preventDefault();
            }}
          >
            <Download size={13} />
            下载
          </a>
        </div>
        <div className={`evidence-content ${imageLike ? "image-preview" : ""}`}>
          {error ? (
            <div className="inline-error">{error}</div>
          ) : !verified ? (
            <div className="small-empty">正在读取…</div>
          ) : imageLike ? (
            <img
              className="evidence-image"
              src={imageSource}
              alt={a.title}
              onError={() => setError("无法显示这张图片，可下载原文件查看")}
            />
          ) : !textLike ? (
            <div className="small-empty">
              {a.mime} · {a.bytes.toLocaleString()} bytes
            </div>
          ) : csv ? (
            <table>
              <thead>
                <tr>
                  {csv[0].map((c, i) => (
                    <th key={i}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {csv.slice(1).map((r, i) => (
                  <tr key={i}>
                    {r.map((c, j) => (
                      <td key={j}>{c}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <pre>{json && !raw ? JSON.stringify(json, null, 2) : content}</pre>
          )}
        </div>
        {textLike && a.bytes > pageSize && (
          <div className="evidence-pagination">
            <button
              className="button subtle"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
            >
              上一段
            </button>
            <span>
              {offset.toLocaleString()}–
              {Math.min(offset + pageSize, a.bytes).toLocaleString()} /{" "}
              {a.bytes.toLocaleString()} bytes
            </span>
            <button
              className="button subtle"
              disabled={offset + pageSize >= a.bytes}
              onClick={() => setOffset(offset + pageSize)}
            >
              下一段
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function SkillPanel({
  project,
  notify,
}: {
  project: Project | null;
  notify: (m: string) => void;
}) {
  const [setup, setSetup] = useState<AgentSetup | null>(null);
  const [setupError, setSetupError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    setSetupError("");
    api
      .agentSetup()
      .then((value) => {
        if (current) setSetup(value);
      })
      .catch(() => {
        if (current) setSetupError("无法读取 Agent 接入信息");
      });
    return () => {
      current = false;
    };
  }, [attempt]);
  const command = setup ? agentCommand(setup, project?.id) : "";
  const prompt = setup ? agentPrompt(setup, project?.id) : "";
  return (
    <div className="skill-panel">
      <div className="skill-panel-icon">
        <Terminal size={25} />
      </div>
      <h2>让 Agent 接着探索</h2>
      <p>复制指令到 Agent 对话，再补充你的研究任务。</p>
      <WorkspaceEnrollment />
      <div
        className="skill-prompt"
        style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
      >
        {prompt || setupError || "正在读取接入信息…"}
      </div>
      {setupError && (
        <button className="button wide" onClick={() => setAttempt(attempt + 1)}>
          重试
        </button>
      )}
      <button
        className="button primary wide"
        disabled={!setup}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(prompt);
            notify("接续指令已复制");
          } catch {
            notify("复制失败，请选中指令复制");
          }
        }}
      >
        <Copy size={14} />
        复制接续指令
      </button>
      <details>
        <summary>
          客户端命令{setup?.shell === "powershell" ? "（PowerShell）" : ""}
        </summary>
        <pre>{command || "正在读取…"}</pre>
      </details>
    </div>
  );
}

export function CreateDialog({
  dialog,
  project,
  selected,
  onClose,
  mutate,
  onCreated,
  onNodeCreated,
  notify,
  flowCenter,
}: {
  dialog: NonNullable<DialogState>;
  project: Project | null;
  selected: string[];
  onClose: () => void;
  mutate: (ops: Operation[]) => Promise<boolean>;
  onCreated: (p: Project) => Promise<void>;
  onNodeCreated: (id: string) => void;
  notify: (m: string) => void;
  flowCenter: () => { x: number; y: number };
}) {
  const [title, setTitle] = useState(""),
    [summary, setSummary] = useState(""),
    [kind, setKind] = useState(
      dialog.type === "group" ? "group" : "experiment",
    ),
    [parentId, setParentId] = useState(dialog.parentId || ""),
    [path, setPath] = useState(""),
    [target, setTarget] = useState(""),
    [relation, setRelation] = useState("leads_to"),
    [saving, setSaving] = useState(false);
  const heading = {
    project: "新建研究",
    node: "添加节点",
    branch: "探索新分支",
    group: "创建容器",
    artifact: "登记证据",
    connect: "连接研究节点",
  }[dialog.type];
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (dialog.type === "project") {
        await onCreated(await api.create(title));
        onClose();
        return;
      }
      if (!project) return;
      if (dialog.type === "artifact") {
        await api.artifact(project.id, {
          path,
          title: title || path.split(/[\\/]/).at(-1),
          nodeId: parentId || undefined,
        });
        notify("证据已登记");
        onClose();
        return;
      }
      if (dialog.type === "connect") {
        if (
          await mutate([
            {
              op: "edge.add",
              data: {
                id: uid("edge"),
                source: dialog.source,
                target,
                relation,
                basis: "hypothesis",
                label: summary,
              },
            },
          ])
        )
          onClose();
        return;
      }
      const id = uid(kind);
      const center = flowCenter();
      const source = project.nodes.find((n) => n.id === dialog.source);
      let position = source
        ? {
            x: source.position.x + NODE_SIZE.w + 50,
            y: source.position.y + NODE_SIZE.h + 60,
          }
        : {
            x: Math.round(center.x - NODE_SIZE.w / 2),
            y: Math.round(center.y - NODE_SIZE.h / 2),
          };
      if (parentId) {
        const parent = project.nodes.find((n) => n.id === parentId);
        if (parent) {
          const siblings = project.nodes.filter((n) => n.parentId === parentId);
          position = {
            x:
              parent.position.x +
              30 +
              (siblings.length % 2) * (NODE_SIZE.w + 30),
            y:
              parent.position.y +
              85 +
              Math.floor(siblings.length / 2) * (NODE_SIZE.h + 35),
          };
        }
      }
      let ops: Operation[] = [];
      if (dialog.type === "group") {
        const roots = project.nodes.filter(
          (n) =>
            selected.includes(n.id) &&
            !ancestry(project.nodes, n.id)
              .slice(0, -1)
              .some((a) => selected.includes(a.id)),
        );
        position = {
          x: Math.min(...roots.map((n) => n.position.x)) - 30,
          y: Math.min(...roots.map((n) => n.position.y)) - 85,
        };
        const commonParent = roots.every(
          (n) => n.parentId === roots[0].parentId,
        )
          ? roots[0].parentId
          : null;
        ops = [
          {
            op: "node.add",
            data: {
              id,
              title,
              kind: "group",
              status: "active",
              summary,
              parentId: commonParent,
              position,
              collapsed: false,
            },
          },
          ...roots.map((n) => ({
            op: "node.update",
            data: { id: n.id, parentId: id },
          })),
        ];
      } else {
        ops = [
          {
            op: "node.add",
            data: {
              id,
              title,
              summary,
              kind,
              status: "proposed",
              parentId: parentId || null,
              position,
              collapsed: false,
            },
          },
        ];
        if (parentId)
          ops.push({
            op: "node.update",
            data: { id: parentId, collapsed: false },
          });
        if (source)
          ops.push({
            op: "edge.add",
            data: {
              id: uid("edge"),
              source: source.id,
              target: id,
              relation: "branches",
              basis: "hypothesis",
              label: summary ? "新方向" : "分支",
            },
          });
      }
      if (await mutate(ops)) {
        onNodeCreated(id);
        onClose();
      }
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form className="modal create-modal" onSubmit={submit}>
        <div className="modal-heading">
          <h2>{heading}</h2>
          <IconButton label="关闭" onClick={onClose}>
            <X size={17} />
          </IconButton>
        </div>
        <div className="edit-fields">
          {dialog.type === "connect" ? (
            <>
              <label>
                目标节点
                <select
                  required
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                >
                  <option value="">选择节点</option>
                  {project?.nodes
                    .filter((n) => n.id !== dialog.source)
                    .map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.title}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                关系
                <select
                  value={relation}
                  onChange={(e) => setRelation(e.target.value)}
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
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                />
              </label>
            </>
          ) : (
            <>
              <label>
                {dialog.type === "project"
                  ? "研究名称"
                  : dialog.type === "group"
                    ? "容器名称"
                    : "名称"}
                <input
                  autoFocus
                  required={dialog.type !== "artifact"}
                  placeholder={
                    dialog.type === "project"
                      ? "你想探索什么？"
                      : "给这个方向起个名字"
                  }
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  maxLength={160}
                />
              </label>
              {dialog.type === "artifact" ? (
                <label>
                  本地文件路径
                  <input
                    required
                    placeholder="/path/to/results.json"
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                  />
                </label>
              ) : (
                dialog.type !== "project" && (
                  <label>
                    {dialog.type === "branch" ? "为什么尝试这个方向" : "摘要"}
                    <textarea
                      placeholder="记录目标、假设或发现…"
                      value={summary}
                      onChange={(e) => setSummary(e.target.value)}
                    />
                  </label>
                )
              )}
              {["node", "branch"].includes(dialog.type) && (
                <label>
                  节点类型
                  <input
                    list="node-kinds"
                    value={kind}
                    onChange={(e) => setKind(e.target.value)}
                    required
                  />
                  <datalist id="node-kinds">
                    {Object.entries(kinds).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </datalist>
                </label>
              )}
              {["node", "branch", "artifact"].includes(dialog.type) && (
                <label>
                  所属节点 / 容器
                  <select
                    value={parentId}
                    onChange={(e) => setParentId(e.target.value)}
                  >
                    <option value="">项目根目录</option>
                    {project?.nodes.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.title}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </>
          )}
        </div>
        <div className="form-actions">
          <button type="button" className="button subtle" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="button primary" disabled={saving}>
            {saving ? "保存中…" : dialog.type === "artifact" ? "登记" : "创建"}
          </button>
        </div>
      </form>
    </div>
  );
}
