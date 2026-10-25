import type { AgentSetup } from "./api";

export function agentPrompt(setup: AgentSetup, projectId?: string): string {
  return `请读取 Skill：${setup.skillPath}\n服务：${setup.url}${projectId ? `\n实验 ID：${projectId}\n按我的研究任务推进，参考可用的实验 context。` : "\n按我的研究任务推进。"}`;
}

export function agentCommand(
  setup: AgentSetup,
  projectId?: string,
  nodeId?: string,
): string {
  const quote = (value: string) =>
    `'${value.replaceAll("'", setup.shell === "powershell" ? "''" : "'\\''")}'`;
  const invocation = `${quote(setup.pythonPath)} ${quote(setup.clientPath)} --url ${quote(setup.url)}`;
  const action = projectId
    ? `context --project ${quote(projectId)}${nodeId ? ` --node ${quote(nodeId)}` : ""}`
    : "projects";
  return `${setup.shell === "powershell" ? "& " : ""}${invocation} ${action}`;
}
