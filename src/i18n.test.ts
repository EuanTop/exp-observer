import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ReactFlowProvider } from "@xyflow/react";
import {
  englishMessages,
  getLocale,
  LANGUAGE_KEY,
  preferredLocale,
  setLocale,
  t,
  translate,
} from "./i18n";
import {
  kinds,
  metricLabel,
  relations,
  statuses,
  toCanvas,
  type Project,
} from "./model";
import { ResearchCard } from "./components/ResearchCard";
import { nodeReference } from "./node-reference";
import { agentPrompt } from "./agent-command";

beforeEach(() => setLocale("en"));
afterEach(() => {
  vi.unstubAllGlobals();
  setLocale("en");
});

describe("interface language", () => {
  it("defaults to English regardless of missing, unsupported or inaccessible storage", () => {
    expect(preferredLocale()).toBe("en");
    expect(preferredLocale({ getItem: () => "fr" })).toBe("en");
    expect(
      preferredLocale({
        getItem: () => {
          throw new Error("blocked");
        },
      }),
    ).toBe("en");
    expect(preferredLocale({ getItem: () => "zh-CN" })).toBe("zh-CN");
  });

  it("persists explicit selection, updates document language and tolerates blocked storage", () => {
    const save = vi.fn();
    const root = { lang: "en" };
    vi.stubGlobal("localStorage", { setItem: save });
    vi.stubGlobal("document", { documentElement: root });
    setLocale("zh-CN");
    expect(save).toHaveBeenCalledWith(LANGUAGE_KEY, "zh-CN");
    expect(root.lang).toBe("zh-CN");
    expect(t("研究图")).toBe("研究图");
    vi.stubGlobal("localStorage", {
      setItem: () => {
        throw new Error("blocked");
      },
    });
    setLocale("en");
    expect(getLocale()).toBe("en");
    expect(root.lang).toBe("en");
    expect(t("研究图")).toBe("Graph");
  });

  it("interpolates values verbatim without interpreting their braces or translating research prose", () => {
    expect(
      translate("节点：{title}", "en", { title: "问题 {count} <script>" }),
    ).toBe("Node: 问题 {count} <script>");
    expect(
      translate("节点：{title}", "zh-CN", { title: "An original finding" }),
    ).toBe("节点：An original finding");
    expect(t("custom kind")).toBe("custom kind");
    expect(t("constructor")).toBe("constructor");
    expect(t("__proto__")).toBe("__proto__");
    expect(metricLabel("问题")).toBe("问题");
    expect(metricLabel("accuracy")).toBe("Accuracy");
  });

  it("renders both languages and preserves research identities, text, state and counters", () => {
    const project = {
      id: "study",
      name: "Original study",
      revision: 2,
      createdAt: "",
      updatedAt: "",
      description: "",
      nodes: [
        {
          id: "question",
          title: "问题",
          summary: "原始研究内容",
          notes: "",
          kind: "question",
          status: "paused",
          pauseReason: "需要新的数据",
          resumeWhen: "数据可用时",
          parentId: null,
          nextAction: "",
          tags: [],
          collapsed: false,
          position: { x: 0, y: 0 },
        },
      ],
      edges: [],
      runs: [],
      observations: [],
      usageRecords: [],
      artifacts: [],
      assessments: [],
      decisions: [],
      activity: [],
    } satisfies Project;
    const before = JSON.stringify(project);
    const render = () => {
      const data = toCanvas(project, null, [], { onToggle() {}, onEnter() {} })
        .nodes[0].data;
      return renderToStaticMarkup(
        createElement(
          ReactFlowProvider,
          null,
          createElement(ResearchCard, { data, selected: false } as Parameters<
            typeof ResearchCard
          >[0]),
        ),
      );
    };
    const english = render();
    expect(english).toContain("Paused");
    expect(english).toContain("Resume: ");
    expect(english).toContain("原始研究内容");
    expect(english).toContain('title="问题"');
    const reference = nodeReference(
      project,
      project.nodes,
      "http://localhost:4317",
    );
    expect(reference).toContain(
      'Identity: {"project":"study","node":"question"}',
    );
    expect(reference).toContain("Node: 问题");
    expect(reference).toContain("status: Paused");
    setLocale("zh-CN");
    expect(render()).toContain("已暂停");
    expect(
      nodeReference(project, project.nodes, "http://localhost:4317"),
    ).toContain("暂停原因：需要新的数据");
    expect(JSON.stringify(project)).toBe(before);
  });

  it("copies agent instructions in the selected language while keeping paths and IDs exact", () => {
    const setup = {
      skillPath: "C:/My Skill/SKILL.md",
      clientPath: "client.py",
      pythonPath: "python",
      url: "http://127.0.0.1:4317",
      shell: "powershell" as const,
    };
    expect(agentPrompt(setup, "study-a")).toBe(
      "Read the Skill: C:/My Skill/SKILL.md\nService: http://127.0.0.1:4317\nExperiment ID: study-a\nContinue my research task, using the available experiment context.",
    );
    setLocale("zh-CN");
    expect(agentPrompt(setup, "study-a")).toContain("实验 ID：study-a");
  });
});

describe("interface translation coverage", () => {
  it("covers every built-in kind, state and relationship", () => {
    for (const label of [
      ...Object.values(kinds),
      ...Object.values(statuses),
      ...Object.values(relations),
    ]) {
      expect(englishMessages[label], label).toBeTruthy();
      expect(t(label)).not.toMatch(/[\u3400-\u9fff]/);
    }
  });

  it("keeps named placeholders intact in every English message", () => {
    const slots = (value: string) =>
      [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
    for (const [source, english] of Object.entries(englishMessages)) {
      expect(english.trim(), source).not.toBe("");
      expect(english, source).not.toMatch(/[\u3400-\u9fff]/);
      expect(slots(english), source).toEqual(slots(source));
    }
  });

  it("rejects missing literal translations and hardcoded Chinese JSX/attributes in the application", () => {
    const paths = [
      "src/App.tsx",
      "src/agent-command.ts",
      "src/node-reference.ts",
      "src/node-presentation.ts",
      "src/card-sizing.ts",
      "src/api.ts",
      ...readdirSync("src/components")
        .filter((name) => name.endsWith(".tsx"))
        .map((name) => join("src/components", name)),
    ];
    const missing: string[] = [];
    for (const path of paths) {
      const file = ts.createSourceFile(
        path,
        readFileSync(path, "utf8"),
        ts.ScriptTarget.Latest,
        true,
        path.endsWith("tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
      );
      const visit = (node: ts.Node) => {
        if (
          ts.isCallExpression(node) &&
          node.expression.getText(file) === "t" &&
          node.arguments[0] &&
          ts.isStringLiteralLike(node.arguments[0])
        ) {
          const key = node.arguments[0].text;
          if (/[\u3400-\u9fff]/.test(key) && !englishMessages[key])
            missing.push(`${path}: missing ${key}`);
        }
        // Language endonyms stay in their own script in either interface.
        const languageOption =
          node.parent &&
          ts.isJsxElement(node.parent) &&
          node.parent.openingElement.tagName.getText(file) === "option" &&
          node.parent.openingElement.attributes.properties.some(
            (attribute) =>
              ts.isJsxAttribute(attribute) &&
              attribute.name.getText(file) === "value" &&
              attribute.initializer &&
              ts.isStringLiteral(attribute.initializer) &&
              attribute.initializer.text === "zh-CN",
          );
        if (
          ts.isJsxText(node) &&
          /[\u3400-\u9fff]/.test(node.text) &&
          !languageOption
        )
          missing.push(`${path}: raw JSX ${node.text.trim()}`);
        if (
          ts.isJsxAttribute(node) &&
          node.initializer &&
          ts.isStringLiteral(node.initializer) &&
          /[\u3400-\u9fff]/.test(node.initializer.text)
        )
          missing.push(`${path}: raw attribute ${node.initializer.text}`);
        ts.forEachChild(node, visit);
      };
      visit(file);
    }
    expect(missing).toEqual([]);
  });
});
