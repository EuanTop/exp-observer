import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Box, ChevronDown, Clock3, Diamond, Layers, Minus } from "lucide-react";
import { kinds, type CanvasData } from "../model";
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
  const tokens = `Token ${formatTokens(usage?.totalTokens)}${usage?.totalTokens != null && usage.tokensPartial ? "+" : ""}`;
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
          usage?.tokensPartial
            ? "部分用量未采集；查看已记录的输入与输出 Token"
            : "查看输入与输出 Token 来源"
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
  const Icon = children ? Layers : kindIcon[n.kind] || Box;
  const presentation = data.presentation ?? {
    headline: n.title || "未命名节点",
    summary: n.summary || "",
    conclusion: "",
    source: "",
  };
  const processing = data.processing === true;
  return (
    <div
      className={`research-node ${selected ? "is-selected" : ""} ${processing ? "is-processing" : ""} ${n.importance === "critical" ? "is-critical" : ""} kind-${n.kind} ${expanded ? "container-expanded" : ""} ${children ? "is-container" : ""}`}
      aria-label={processing ? `${presentation.headline}，处理中` : undefined}
    >
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
          {children ? "探索容器" : kinds[n.kind] || n.kind || "研究节点"}
          {n.importance === "critical" && (
            <span
              className="node-critical-mark"
              title={n.importanceReason || "关键节点"}
            >
              <Diamond size={10} />
              关键
            </span>
          )}
        </div>
        <Badge status={n.status || "未记录"} />
      </div>
      <div
        className={`node-content ${presentation.conclusion ? "has-conclusion" : ""}`}
      >
        <h3 title={presentation.headline}>{presentation.headline}</h3>
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
          {children ? (
            <button
              className="expand-link nodrag"
              onClick={(e) => {
                e.stopPropagation();
                data.onToggle(n.id);
              }}
            >
              <Layers size={11} />
              {children} 子节点
              <ChevronDown size={10} />
            </button>
          ) : (
            <button
              className="node-stat nodrag"
              onClick={(e) => {
                e.stopPropagation();
                data.onInspect?.(n.id, "runs");
              }}
              title="查看该节点的运行记录"
            >
              {data.usage?.runCount ?? data.runs ?? 0} 次运行
            </button>
          )}
          <UsageStats data={data} />
        </div>
      )}
    </div>
  );
}
