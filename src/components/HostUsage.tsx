import type { HostUsageRecord, Project } from "../model";
import { getProjectHostUsage, formatUsageTime } from "../usage";

const tokens = (value: number | null) =>
  value === null ? "—" : value.toLocaleString("en-US");
const modelName = (model: string) =>
  !model || model === "unknown" ? "未知模型" : model;

export function ProjectHostUsage({ project }: { project: Project }) {
  const usage = getProjectHostUsage(project);
  if (!usage.recordCount) return null;
  return (
    <section className="project-host-usage">
      <div className="inspector-section-title">
        <span>分口径实测用量</span>
        <span>{usage.recordCount} 条用量记录</span>
      </div>
      {usage.models.map((model) => (
        <div
          className="observation-card"
          key={`${model.scope}/${model.provider}/${model.model}`}
        >
          <div className="observation-title">
            <strong>{modelName(model.model)}</strong>
          </div>
          <div className="observation-meta">
            {model.scope === "execution" ? "被测任务用量" : "关联会话用量"} ·{" "}
            {model.provider || "未知提供商"} · {model.recordCount} 条记录
          </div>
          <dl className="host-usage-values">
            <div>
              <dt>输入 Token</dt>
              <dd>{tokens(model.inputTokens)}</dd>
            </div>
            <div>
              <dt>输出 Token</dt>
              <dd>{tokens(model.outputTokens)}</dd>
            </div>
            <div>
              <dt>缓存读取</dt>
              <dd>{tokens(model.cacheReadTokens)}</dd>
            </div>
            <div>
              <dt>缓存写入</dt>
              <dd>{tokens(model.cacheWriteTokens)}</dd>
            </div>
          </dl>
        </div>
      ))}
      <p className="usage-scope">
        保留宿主原始计数，缓存单列，不额外叠加到输入 Token。
      </p>
      <p className="usage-scope">
        关联会话与被测任务分开列示，不相加。被测任务用量，非主研究Agent完整成本。
      </p>
      {usage.unassignedCount > 0 && (
        <p className="usage-scope">
          {usage.unassignedCount} 条记录尚未归属节点，保留在对应口径中。
        </p>
      )}
    </section>
  );
}

export function NodeHostUsage({ records }: { records: HostUsageRecord[] }) {
  if (!records.length) return null;
  return (
    <>
      {(["agent", "execution"] as const).map((scope) => {
        const scoped = records.filter(
          (record) => (record.scope ?? "agent") === scope,
        );
        if (!scoped.length) return null;
        return (
          <section key={scope}>
            <div className="inspector-section-title">
              <span>
                {scope === "execution" ? "被测任务用量" : "关联会话用量"}
              </span>
              <span>{scoped.length} 条记录</span>
            </div>
            <p className="usage-scope">
              仅计入能够明确归属的推理。缓存单列，不额外叠加。
              {scope === "execution" && "被测任务用量，非主研究Agent完整成本。"}
            </p>
            {scoped.map((record) => (
              <div className="observation-card" key={record.id}>
                <div className="observation-title">
                  <strong>{modelName(record.model)}</strong>
                </div>
                <div className="observation-tokens">
                  <span>输入 {tokens(record.inputTokens)}</span>
                  <span>输出 {tokens(record.outputTokens)}</span>
                </div>
                <div className="observation-meta">
                  <span>缓存读取 {tokens(record.cacheReadTokens)}</span>
                  <span>缓存写入 {tokens(record.cacheWriteTokens)}</span>
                </div>
                <div className="observation-meta">
                  <span>
                    开始 <time>{formatUsageTime(record.startedAt)}</time>
                  </span>
                  <span>
                    结束 <time>{formatUsageTime(record.finishedAt)}</time>
                  </span>
                  <span>{record.provider || "未知提供商"}</span>
                </div>
                <details>
                  <summary>来源记录</summary>
                  <p className="usage-scope">
                    {record.source.startsWith("happy-sqlite:")
                      ? "Happy 宿主"
                      : record.source}{" "}
                    · {record.sourceRef}
                  </p>
                </details>
              </div>
            ))}
          </section>
        );
      })}
    </>
  );
}
