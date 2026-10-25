import type { AgentSetup } from "./api";
import { t } from "./i18n";

export function agentPrompt(setup: AgentSetup, projectId?: string): string {
  return projectId
    ? t(
        "请读取 Skill：{skill}\n服务：{url}\n实验 ID：{project}\n按我的研究任务推进，参考可用的实验 context。",
        { skill: setup.skillPath, url: setup.url, project: projectId },
      )
    : t("请读取 Skill：{skill}\n服务：{url}\n按我的研究任务推进。", {
        skill: setup.skillPath,
        url: setup.url,
      });
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
