import type { AgentSetup } from "./api";
import { t } from "./i18n";
import { agentCommand } from "./agent-command";
import {
  ancestry,
  kinds,
  statuses,
  type Project,
  type ResearchNode,
} from "./model";
import { nodePresentation } from "./node-presentation";

const excerpt = (text?: string) =>
  text?.replace(/\s+/g, " ").trim().slice(0, 220);

export function nodeReference(
  project: Project,
  nodes: ResearchNode[],
  serverUrl: string,
  setup?: AgentSetup,
): string {
  const unique = [...new Map(nodes.map((node) => [node.id, node])).values()];
  return [
    t("ExpObserver 节点引用"),
    t("实验：{name}", { name: project.name }),
    t("服务：{url}", { url: serverUrl }),
    t("引用版本：r{revision}", { revision: project.revision }),
    t("Skill：{skill}", { skill: setup?.skillPath || "exp-observer" }),
    ...unique.map((node) => {
      const presentation = nodePresentation(project, node);
      return [
        "",
        t("节点：{title}", { title: node.title }),
        t("路径：{path}", {
          path: ancestry(project.nodes, node.id)
            .map((parent) => parent.title)
            .join(" / "),
        }),
        t("类型：{kind}；状态：{status}", {
          kind: kinds[node.kind] ? t(kinds[node.kind]) : node.kind,
          status: statuses[node.status]
            ? t(statuses[node.status])
            : node.status,
        }),
        // JSON preserves stable identities even when a title or ID contains punctuation.
        t("定位：{identity}", {
          identity: JSON.stringify({ project: project.id, node: node.id }),
        }),
        presentation.summary &&
          t("摘要：{summary}", { summary: excerpt(presentation.summary)! }),
        presentation.conclusion &&
          t("结论：{conclusion}", {
            conclusion: excerpt(presentation.conclusion)!,
          }),
        node.pauseReason &&
          t("暂停原因：{reason}", { reason: excerpt(node.pauseReason)! }),
        node.nextAction &&
          t("下一步：{action}", { action: excerpt(node.nextAction)! }),
        node.resumeWhen &&
          t("恢复条件：{condition}", { condition: excerpt(node.resumeWhen)! }),
        setup &&
          t("读取：{command}", {
            command: agentCommand(
              { ...setup, url: serverUrl },
              project.id,
              node.id,
            ),
          }),
      ]
        .filter(Boolean)
        .join("\n");
    }),
    "",
    t(
      "接下来的问题引用以上环节。请使用 ExpObserver Skill 按实验和节点 ID 读取最新 context，按需查看内部节点和相关证据，再处理我的问题。",
    ),
  ].join("\n");
}
