import { useEffect, useState, type FormEvent } from "react";
import { api, type ResearchWorkspace } from "../api";

export function WorkspaceEnrollment() {
  const [workspaces, setWorkspaces] = useState<ResearchWorkspace[]>([]);
  const [path, setPath] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    api
      .workspaces()
      .then((result) => {
        if (current) setWorkspaces(result.workspaces);
      })
      .catch((reason: Error) => {
        if (current) setError(`无法读取研究目录：${reason.message}`);
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [attempt]);
  const add = async (event: FormEvent) => {
    event.preventDefault();
    if (!path.trim() || saving) return;
    setSaving(true);
    setError("");
    try {
      setWorkspaces((await api.addWorkspace(path.trim())).workspaces);
      setPath("");
    } catch (reason) {
      setError(`无法添加目录：${(reason as Error).message}`);
    } finally {
      setSaving(false);
    }
  };
  const remove = async (id: string) => {
    setSaving(true);
    setError("");
    try {
      setWorkspaces((await api.removeWorkspace(id)).workspaces);
    } catch (reason) {
      setError(`无法移除目录：${(reason as Error).message}`);
    } finally {
      setSaving(false);
    }
  };
  return (
    <section
      className="workspace-enrollment"
      aria-labelledby="workspace-heading"
      aria-busy={loading || saving}
    >
      <h3 id="workspace-heading">研究目录</h3>
      <p>添加后，应用会自动读取该目录下的本地记录，包括后续新增的子实验。</p>
      <form onSubmit={(event) => void add(event)} className="workspace-form">
        <input
          aria-label="研究目录路径"
          placeholder="输入本地研究目录的完整路径"
          value={path}
          onChange={(event) => setPath(event.target.value)}
          disabled={saving || loading}
        />
        <button
          className="button"
          type="submit"
          disabled={saving || loading || !path.trim()}
        >
          {saving ? "处理中…" : "添加"}
        </button>
      </form>
      {error && (
        <div className="inline-error" role="alert">
          {error}
          <button
            className="text-button"
            onClick={() => setAttempt(attempt + 1)}
            disabled={saving}
          >
            重试读取
          </button>
        </div>
      )}
      {loading ? (
        <div className="workspace-empty" role="status">
          正在读取研究目录…
        </div>
      ) : (
        <ul className="workspace-list">
          {workspaces.map((workspace) => (
            <li key={workspace.id}>
              <span title={workspace.path}>{workspace.path}</span>
              <button
                type="button"
                disabled={saving}
                onClick={() => void remove(workspace.id)}
                title="移除接入，保留目录和已有记录"
                aria-label={`移除研究目录 ${workspace.path}`}
              >
                移除
              </button>
            </li>
          ))}
          {!workspaces.length && !error && (
            <li className="workspace-empty">尚未添加研究目录</li>
          )}
        </ul>
      )}
      {!!workspaces.length && (
        <small>移除仅停止接入，保留目录和已有记录。</small>
      )}
    </section>
  );
}
