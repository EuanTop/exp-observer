import type { AgentSetup } from "./api";

export function agentPrompt(setup: AgentSetup, projectId?: string): string {
  return `请读取 Skill：${setup.skillPath}\n服务：${setup.url}${projectId ? `\n实验：${projectId}\n读取该实验的 context，再执行我的研究任务。` : "\n执行我的研究任务。"}`;
}

export function agentCommand(setup: AgentSetup, projectId?: string): string {
  const quote = (value: string) =>
    `'${value.replaceAll("'", setup.shell === "powershell" ? "''" : "'\\''")}'`;
  const invocation = `${quote(setup.pythonPath)} ${quote(setup.clientPath)} --url ${quote(setup.url)}`;
  const action = projectId
    ? `context --project ${quote(projectId)}`
    : "projects";
  return `${setup.shell === "powershell" ? "& " : ""}${invocation} ${action}`;
}
