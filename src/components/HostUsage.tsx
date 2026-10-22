import type { HostUsageRecord, Project } from "../model";
import { getProjectHostUsage } from "../usage";
import { date } from "./Primitives";

const tokens = (value: number | null) =>
  value === null ? "—" : value.toLocaleString("en-US");

export function ProjectHostUsage({ project }: { project: Project }) {
  const usage = getProjectHostUsage(project);
  if (!usage.recordCount) return null;
  return (
    <section className="project-host-usage">
      <div className="inspector-section-title">
        <span>关联会话实测用量</span>
        <span>{usage.recordCount} 次推理</span>
      </div>
      {usage.models.map((model) => (
        <div
          className="observation-card"
          key={`${model.provider}/${model.model}`}
        >
          <div className="observation-title">
            <strong>{model.model}</strong>
          </div>
          <div className="observation-meta">
            {model.provider} · {model.recordCount} 次推理
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
        口径为已关联会话的推理用量，包含未能归属具体节点的部分。
      </p>
      {usage.unassignedCount > 0 && (
        <p className="usage-scope">
          {usage.unassignedCount} 次推理尚未归属节点，保留在研究总量中。
        </p>
      )}
    </section>
  );
}

export function NodeHostUsage({ records }: { records: HostUsageRecord[] }) {
  if (!records.length) return null;
  return (
    <section>
      <div className="inspector-section-title">
        <span>宿主实测用量</span>
        <span>{records.length} 次推理</span>
      </div>
      <p className="usage-scope">
        仅计入能够明确归属的推理。缓存单列，不额外叠加。
      </p>
      {records.map((record) => (
        <div className="observation-card" key={record.id}>
          <div className="observation-title">
            <strong>{record.model}</strong>
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
            <time>{date(record.finishedAt)}</time>
            <span>{record.provider}</span>
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
}
