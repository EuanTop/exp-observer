import type { AgentSetup } from "./api";
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
    "ExpObserver 节点引用",
    `实验：${project.name}`,
    `服务：${serverUrl}`,
    `引用版本：r${project.revision}`,
    setup ? `Skill：${setup.skillPath}` : "Skill：exp-observer",
    ...unique.map((node) => {
      const presentation = nodePresentation(project, node);
      return [
        "",
        `节点：${node.title}`,
        `路径：${ancestry(project.nodes, node.id)
          .map((parent) => parent.title)
          .join(" / ")}`,
        `类型：${kinds[node.kind] || node.kind}；状态：${statuses[node.status] || node.status}`,
        // JSON preserves stable identities even when a title or ID contains punctuation.
        `定位：${JSON.stringify({ project: project.id, node: node.id })}`,
        presentation.summary && `摘要：${excerpt(presentation.summary)}`,
        presentation.conclusion && `结论：${excerpt(presentation.conclusion)}`,
        node.pauseReason && `暂停原因：${excerpt(node.pauseReason)}`,
        node.nextAction && `下一步：${excerpt(node.nextAction)}`,
        node.resumeWhen && `恢复条件：${excerpt(node.resumeWhen)}`,
        setup &&
          `读取：${agentCommand({ ...setup, url: serverUrl }, project.id, node.id)}`,
      ]
        .filter(Boolean)
        .join("\n");
    }),
    "",
    "接下来的问题引用以上环节。请使用 ExpObserver Skill 按实验和节点 ID 读取最新 context，按需查看内部节点和相关证据，再处理我的问题。",
  ].join("\n");
}
