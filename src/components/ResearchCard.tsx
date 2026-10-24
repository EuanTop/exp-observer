import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import {
  Activity,
  Box,
  ChevronDown,
  ChevronRight,
  Clock3,
  Layers,
  Minus,
} from "lucide-react";
import { kinds, type CanvasData } from "../model";
import type { NodePresentation } from "../node-presentation";
import { formatDuration, formatTokens } from "../usage";
import { Badge, kindIcon } from "./Primitives";

function UsageStats({ data }: { data: CanvasData }) {
  const usage = data.usage;
  const elapsed = usage?.isRunning
    ? "计时中"
    : usage?.elapsedMs != null
      ? `计时 ${formatDuration(usage.elapsedMs)}`
      : usage?.runMs != null
        ? `执行 ${formatDuration(usage.runMs)}`
        : "计时 —";
  const tokens = `${usage?.tokenScope === "execution" ? "执行 Token" : "Token"} ${formatTokens(usage?.totalTokens)}${usage?.totalTokens != null && usage.tokensPartial ? "+" : ""}`;
  return (
    <>
      <button
        className="node-stat nodrag"
        title="查看步骤计时与执行耗时"
        onClick={(e) => {
          e.stopPropagation();
          data.onInspect?.(data.node.id, "usage");
        }}
      >
        <Clock3 size={10} />
        {elapsed}
      </button>
      <button
        className="node-stat nodrag"
        title={
          usage?.tokenScope === "execution"
            ? "被测任务用量；查看输入与输出 Token 来源"
            : usage?.tokensPartial
              ? "部分用量未采集；查看已记录的输入与输出 Token"
              : "研究 Agent 用量；查看输入与输出 Token 来源"
        }
        onClick={(e) => {
          e.stopPropagation();
          data.onInspect?.(data.node.id, "usage");
        }}
      >
        {tokens}
      </button>
    </>
  );
}

export function ResearchCard({ data, selected }: NodeProps<Node<CanvasData>>) {
  const { node: n, children, expanded } = data;
  const container = data.container === true;
  const Icon = container ? Layers : kindIcon[n.kind] || Box;
  const presentation: NodePresentation = data.presentation ?? {
    headline: n.title || "未命名节点",
    context: "",
    summary: n.summary || "",
    conclusion: "",
    source: "",
  };
  const processing = data.processing === true;
  const hasPause = !!(
    presentation.pauseReason ||
    presentation.resumeWhen ||
    presentation.nextAction
  );
  return (
    <div
      className={`research-node ${selected ? "is-selected" : ""} ${processing ? "is-processing" : ""} ${(container || !processing) && n.status === "failed" ? "state-failed" : ""} ${(container || !processing) && n.status === "paused" ? "state-paused" : ""} kind-${n.kind} ${expanded ? "container-expanded" : ""} ${container ? "is-container" : ""}`}
      aria-label={processing ? `${presentation.headline}，处理中` : undefined}
    >
      {processing && (
        <svg className="processing-outline" aria-hidden="true">
          <rect className="processing-outline-track" pathLength="100" />
          <rect className="processing-outline-blue" pathLength="100" />
          <rect className="processing-outline-green" pathLength="100" />
        </svg>
      )}
      {(
        [Position.Top, Position.Right, Position.Bottom, Position.Left] as const
      ).map((position) => (
        <Handle
          key={position}
          id={position}
          type="source"
          position={position}
        />
      ))}
      <div className="node-grip">
        <div className="node-type">
          <span className="node-kind-icon">
            <Icon size={13} />
          </span>
          {kinds[n.kind] || n.kind || "研究节点"}
          {container && n.kind !== "group" ? " · 容器" : ""}
          {container && processing && (
            <span title="容器内有执行正在运行" aria-label="内部执行中">
              <Activity size={12} />
            </span>
          )}
        </div>
        <Badge
          status={processing && !container ? "running" : n.status || "未记录"}
        />
        {!expanded && container && children > 0 && (
          <button
            className="node-inline-expand nodrag"
            title="就地展开容器"
            onClick={(e) => {
              e.stopPropagation();
              data.onToggle(n.id);
            }}
          >
            <ChevronDown size={13} />
          </button>
        )}
      </div>
      <div
        className={`node-content ${presentation.conclusion ? "has-conclusion" : ""} ${hasPause ? "has-pause" : ""}`}
      >
        <h3 title={presentation.headline}>{presentation.headline}</h3>
        {!expanded && hasPause && (
          <div className="node-pause-details">
            {presentation.pauseReason && (
              <p title={presentation.pauseReason}>
                <span>暂停：</span>
                {presentation.pauseReason}
              </p>
            )}
            {(presentation.resumeWhen || presentation.nextAction) && (
              <p title={presentation.resumeWhen || presentation.nextAction}>
                <span>{presentation.resumeWhen ? "恢复：" : "下一步："}</span>
                {presentation.resumeWhen || presentation.nextAction}
              </p>
            )}
          </div>
        )}
        {!expanded && presentation.summary && (
          <p title={presentation.summary}>{presentation.summary}</p>
        )}
        {!expanded && presentation.conclusion && (
          <p className="node-conclusion" title={presentation.conclusion}>
            {presentation.source || "结论"}：{presentation.conclusion}
          </p>
        )}
      </div>
      {expanded ? (
        <>
          <div className="container-actions nodrag">
            <span>{children} 个节点</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                data.onToggle(n.id);
              }}
              title="折叠容器"
            >
              <Minus size={12} />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                data.onEnter(n.id);
              }}
              title="进入容器"
            >
              进入
            </button>
          </div>
          <div className="container-usage">
            <UsageStats data={data} />
          </div>
        </>
      ) : (
        <div className="node-footer">
          {container ? (
            <button
              className="expand-link nodrag"
              onClick={(e) => {
                e.stopPropagation();
                data.onEnter(n.id);
              }}
            >
              <ChevronRight size={11} />
              进入 · {children} 个节点
            </button>
          ) : (
            <button
              className="node-stat nodrag"
              onClick={(e) => {
                e.stopPropagation();
                data.onInspect?.(n.id, "runs");
              }}
              title="查看平台捕获的命令执行"
            >
              {(data.usage?.runCount ?? data.runs ?? 0) > 0
                ? `${data.usage?.runCount ?? data.runs} 次执行`
                : "未采集执行"}
            </button>
          )}
          <UsageStats data={data} />
        </div>
      )}
    </div>
  );
}
