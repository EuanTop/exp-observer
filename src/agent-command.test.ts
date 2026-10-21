import { describe, expect, it } from "vitest";
import { agentCommand, agentPrompt } from "./agent-command";
import type { AgentSetup } from "./api";

const setup: AgentSetup = {
  skillPath: "/workspace/skills/exp-observer/SKILL.md",
  clientPath: "/workspace/exp_observer.py",
  pythonPath: "/usr/bin/python3",
  shell: "posix",
  url: "http://127.0.0.1:5432",
};

describe("agent client command", () => {
  it("preserves the selected experiment while research can continue without live context", () => {
    expect(agentPrompt(setup, "study")).toBe(
      `请读取 Skill：${setup.skillPath}\n服务：${setup.url}\n实验 ID：study\n按我的研究任务推进，参考可用的实验 context。`,
    );
    expect(agentPrompt(setup)).toBe(
      `请读取 Skill：${setup.skillPath}\n服务：${setup.url}\n按我的研究任务推进。`,
    );
  });
  it("quotes POSIX paths with spaces, apostrophes and shell metacharacters", () => {
    expect(
      agentCommand(
        {
          ...setup,
          pythonPath: "/opt/Python 3/bin/python3",
          clientPath: "/home/O'Reilly/$research; echo no/exp_observer.py",
        },
        "study",
      ),
    ).toBe(
      String.raw`'/opt/Python 3/bin/python3' '/home/O'\''Reilly/$research; echo no/exp_observer.py' --url 'http://127.0.0.1:5432' context --project 'study'`,
    );
  });

  it("uses the PowerShell call operator and literal quoting for Windows paths", () => {
    expect(
      agentCommand(
        {
          ...setup,
          shell: "powershell",
          pythonPath: String.raw`C:\Program Files\Python\python.exe`,
          clientPath: String.raw`C:\O'Reilly\$study & tools\exp_observer.py`,
        },
        "study",
      ),
    ).toBe(
      String.raw`& 'C:\Program Files\Python\python.exe' 'C:\O''Reilly\$study & tools\exp_observer.py' --url 'http://127.0.0.1:5432' context --project 'study'`,
    );
  });

  it("lists projects when no experiment is selected and keeps the actual server port", () => {
    expect(agentCommand(setup)).toBe(
      "'/usr/bin/python3' '/workspace/exp_observer.py' --url 'http://127.0.0.1:5432' projects",
    );
  });
});
