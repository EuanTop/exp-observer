import type { AgentSetup } from "./api";

export function agentCommand(setup: AgentSetup, projectId?: string): string {
  const quote = (value: string) =>
    `'${value.replaceAll("'", setup.shell === "powershell" ? "''" : "'\\''")}'`;
  const invocation = `${quote(setup.pythonPath)} ${quote(setup.clientPath)} --url ${quote(setup.url)}`;
  const action = projectId
    ? `context --project ${quote(projectId)}`
    : "projects";
  return `${setup.shell === "powershell" ? "& " : ""}${invocation} ${action}`;
}
