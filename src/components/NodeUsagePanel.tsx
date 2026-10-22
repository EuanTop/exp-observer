import { Clock3, Play, Square } from "lucide-react";
import {
  getNodeUsage,
  formatDuration,
  formatTokens,
  formatUsageTime,
} from "../usage";
import { uid, type Operation, type Project, type ResearchNode } from "../model";
import { NodeHostUsage } from "./HostUsage";

export function NodeUsagePanel({
  project,
  node,
  busy,
  mutate,
}: {
  project: Project;
  node: ResearchNode;
  busy: boolean;
  mutate: (operations: Operation[]) => Promise<boolean>;
}) {
  const usage = getNodeUsage(project, node.id);
  const ownRunning = usage.observations.filter(
    (o) => o.nodeId === node.id && o.status === "running",
  );
  const children = project.nodes.some((n) => n.parentId === node.id);
  return (
    <div className="node-usage-panel">
      <div className="usage-summary">
        <div>
          <span>记录计时</span>
          <strong>
            {formatDuration(usage.elapsedMs)}
            {usage.elapsedPartial && usage.elapsedMs !== null ? "+" : ""}
          </strong>
        </div>
        <div>
          <span>输入 Token</span>
          <strong>{formatTokens(usage.inputTokens)}</strong>
        </div>
        <div>
          <span>输出 Token</span>
          <strong>{formatTokens(usage.outputTokens)}</strong>
        </div>
      </div>
      <p className="usage-scope">
        {usage.tokenScope === "execution"
          ? "被测任务用量，非主研究Agent完整成本"
          : "关联会话用量（含手工记录）；与被测任务用量分开列示，不相加"}
      </p>
      <div className="usage-scope">
        <span>
          {children
            ? "含子节点，重叠计时已合并"
            : usage.isRunning
              ? "计时中"
              : "已记录用量"}
        </span>
        {usage.runCount > 0 && (
          <span>
            {usage.runCount} 次运行 · 执行 {formatDuration(usage.runMs)}
          </span>
        )}
      </div>
      {usage.tokensPartial && usage.totalTokens !== null && (
        <div className="usage-scope">部分 Token 未采集</div>
      )}
      <button
        className="button wide"
        disabled={busy || ownRunning.length > 0}
        onClick={() =>
          void mutate([
            {
              op: "observation.start",
              data: { id: uid("obs"), nodeId: node.id, title: node.title },
            },
          ])
        }
      >
        <Play size={12} />
        开始计时
      </button>
      {!usage.observations.length && !usage.hostUsage.length && (
        <div className="small-empty">
          该节点尚无可确认归属的步骤计时或 Token 数据
        </div>
      )}
      <NodeHostUsage records={usage.hostUsage} />
      {usage.observations.map((o) => (
        <div className="observation-card" key={o.id}>
          <div className="observation-title">
            <Clock3 size={12} />
            <strong>{o.title}</strong>
            <span>
              {o.status === "running" ? "计时中" : formatDuration(o.durationMs)}
            </span>
          </div>
          {o.nodeId !== node.id && (
            <div className="observation-node">
              {project.nodes.find((n) => n.id === o.nodeId)?.title}
            </div>
          )}
          <div className="observation-tokens">
            <span>输入 {formatTokens(o.inputTokens)}</span>
            <span>输出 {formatTokens(o.outputTokens)}</span>
          </div>
          <div className="observation-meta">
            <time>{formatUsageTime(o.startedAt)}</time>
            <span>{o.usageSource || "Token 未采集"}</span>
            {o.usageRef && <span>{o.usageRef}</span>}
          </div>
          {o.nodeId === node.id && o.status === "running" && (
            <button
              className="button subtle wide"
              disabled={busy}
              onClick={() =>
                void mutate([{ op: "observation.finish", data: { id: o.id } }])
              }
            >
              <Square size={11} />
              结束计时
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
