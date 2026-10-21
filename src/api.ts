import type { Artifact, Operation, Project, ProjectSummary } from "./model";
export type AgentSetup = { skillPath: string; clientPath: string; url: string };
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!r.ok) {
    let m;
    try {
      m = (await r.json()).error;
    } catch {
      m = r.statusText;
    }
    throw new ApiError(m || "请求失败", r.status);
  }
  return r.json();
}
export const api = {
  agentSetup: () => request<AgentSetup>("/api/agent-setup"),
  list: () => request<{ projects: ProjectSummary[] }>("/api/projects"),
  project: (id: string) =>
    request<Project>(`/api/projects/${encodeURIComponent(id)}`),
  create: (name: string) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  batch: (project: Project, operations: Operation[]) =>
    request<Project>(`/api/projects/${encodeURIComponent(project.id)}/batch`, {
      method: "POST",
      body: JSON.stringify({
        expectedRevision: project.revision,
        requestId: crypto.randomUUID(),
        operations,
      }),
    }),
  import: (p: unknown) =>
    request<Project>("/api/import", {
      method: "POST",
      body: JSON.stringify(p),
    }),
  artifact: (id: string, data: Record<string, unknown>) =>
    request<Artifact>(`/api/projects/${encodeURIComponent(id)}/artifacts`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  history: (id: string) =>
    request<any>(`/api/projects/${encodeURIComponent(id)}/history`),
  restore: (p: Project, revision: number) =>
    request<Project>(`/api/projects/${encodeURIComponent(p.id)}/restore`, {
      method: "POST",
      body: JSON.stringify({ expectedRevision: p.revision, revision }),
    }),
};
