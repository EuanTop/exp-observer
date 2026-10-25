import { describe, expect, it } from "vitest";
import { nodeReference } from "./node-reference";
import type { AgentSetup } from "./api";
import type { Project, ResearchNode } from "./model";
const parent = {
  id: "parent",
  title: "研究问题",
  kind: "question",
  status: "completed",
  parentId: null,
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 0, y: 0 },
  collapsed: true,
} satisfies ResearchNode;
const node = {
  ...parent,
  id: "step' $x",
  title: "同名问题",
  status: "paused",
  parentId: parent.id,
  summary: "原始摘要",
  pauseReason: "缺少独立样本",
  resumeWhen: "取得新数据",
  nextAction: "检查新样本",
};
const project = {
  id: "study",
  name: "实际实验",
  revision: 110,
  nodes: [parent, node],
  runs: [],
  assessments: [],
  decisions: [],
} as unknown as Project;
const setup: AgentSetup = {
  skillPath: "C:/Skill/SKILL.md",
  clientPath: "C:/Skill/client.py",
  pythonPath: "C:/Python/python.exe",
  shell: "powershell",
  url: "http://localhost:4317",
};
describe("node reference", () => {
  it("preserves stable identity, hierarchy and actual pause conditions with a scoped, quoted command", () => {
    const result = nodeReference(
      project,
      [node],
      "http://localhost:5000",
      setup,
    );
    expect(result).toContain("路径：研究问题 / 同名问题");
    expect(result).toContain('定位：{"project":"study","node":"step\' $x"}');
    expect(result).toContain("引用版本：r110");
    expect(result).toContain("状态：已暂停");
    expect(result).toContain("暂停原因：缺少独立样本");
    expect(result).toContain("恢复条件：取得新数据");
    expect(result).toContain(
      "--url 'http://localhost:5000' context --project 'study' --node 'step'' $x'",
    );
    expect(result).toContain("读取最新 context");
  });
  it("can reference multiple same-title nodes, deduplicates IDs and does not export entire notes", () => {
    const other = { ...node, id: "other", notes: "private-long-notes" };
    const result = nodeReference(project, [node, other, node], setup.url);
    expect(result.match(/定位：/g)).toHaveLength(2);
    expect(result).toContain('"node":"other"');
    expect(result).not.toContain("private-long-notes");
    expect(result).not.toContain("读取：");
    expect(result).toContain("Skill：exp-observer");
  });
  it("bounds previews without omitting the full title or identity", () => {
    const result = nodeReference(
      project,
      [{ ...node, title: "很长的标题".repeat(60), summary: "x".repeat(10000) }],
      setup.url,
    );
    expect(result).toContain(node.id);
    expect(result).toContain("很长的标题".repeat(60));
    expect(result).not.toContain("x".repeat(221));
  });
});
