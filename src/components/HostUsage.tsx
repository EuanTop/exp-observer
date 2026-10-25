import { t, intlLocale } from "../i18n";
import { UsageCollection } from "./UsageCollection";
import type { HostUsageRecord, Project } from "../model";
import { getProjectHostUsage, formatUsageTime } from "../usage";

const tokens = (value: number | null) =>
  value === null ? "—" : value.toLocaleString(intlLocale());
const modelName = (model: string) =>
  !model || model === "unknown" ? t("未知模型") : model;

export function ProjectHostUsage({ project }: { project: Project }) {
  const usage = getProjectHostUsage(project);
  if (!usage.recordCount) return <UsageCollection projectId={project.id} />;
  return (
    <section className="project-host-usage">
      <div className="inspector-section-title">
        <span>{t("实测用量")}</span>
        <span>{t("{count} 条用量记录", { count: usage.recordCount })}</span>
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
            {model.scope === "execution"
              ? t("被测任务用量")
              : t("研究 Agent 用量")}{" "}
            · {model.provider || t("未知提供商")} ·{" "}
            {t("{count} 条记录", { count: model.recordCount })}
          </div>
          <dl className="host-usage-values">
            <div>
              <dt>{t("输入 Token")}</dt>
              <dd>{tokens(model.inputTokens)}</dd>
            </div>
            <div>
              <dt>{t("输出 Token")}</dt>
              <dd>{tokens(model.outputTokens)}</dd>
            </div>
            <div>
              <dt>{t("缓存读取")}</dt>
              <dd>{tokens(model.cacheReadTokens)}</dd>
            </div>
            <div>
              <dt>{t("缓存写入")}</dt>
              <dd>{tokens(model.cacheWriteTokens)}</dd>
            </div>
          </dl>
        </div>
      ))}
      <UsageCollection projectId={project.id} />
      <p className="usage-scope">
        {t("保留宿主原始计数，缓存单列，不额外叠加到输入 Token。")}
      </p>

      {usage.unassignedCount > 0 && (
        <p className="usage-scope">
          {t("{count} 条记录尚未归属节点，保留在对应口径中。", {
            count: usage.unassignedCount,
          })}
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
                {scope === "execution"
                  ? t("被测任务用量")
                  : t("研究 Agent 用量")}
              </span>
              <span>{t("{count} 条记录", { count: scoped.length })}</span>
            </div>
            <p className="usage-scope">
              {scoped.some((r) => r.attribution === "recorded-work-window")
                ? t("宿主实测 · 按研究记录区间归属")
                : t("宿主实测 · 缓存单列")}
            </p>
            {scoped.map((record) => (
              <div className="observation-card" key={record.id}>
                <div className="observation-title">
                  <strong>{modelName(record.model)}</strong>
                </div>
                <div className="observation-tokens">
                  <span>
                    {t("输入 {count}", { count: tokens(record.inputTokens) })}
                  </span>
                  <span>
                    {t("输出 {count}", { count: tokens(record.outputTokens) })}
                  </span>
                </div>
                <div className="observation-meta">
                  <span>
                    {t("缓存读取 {count}", {
                      count: tokens(record.cacheReadTokens),
                    })}
                  </span>
                  <span>
                    {t("缓存写入 {count}", {
                      count: tokens(record.cacheWriteTokens),
                    })}
                  </span>
                </div>
                <div className="observation-meta">
                  {record.source === "codex-session" ? (
                    <span>
                      {t("记录时间")}{" "}
                      <time>{formatUsageTime(record.finishedAt)}</time>
                    </span>
                  ) : (
                    <>
                      <span>
                        {t("开始")}{" "}
                        <time>{formatUsageTime(record.startedAt)}</time>
                      </span>
                      <span>
                        {t("结束")}{" "}
                        <time>{formatUsageTime(record.finishedAt)}</time>
                      </span>
                    </>
                  )}
                  <span>{record.provider || t("未知提供商")}</span>
                </div>
                <details>
                  <summary>{t("来源记录")}</summary>
                  <p className="usage-scope">
                    {record.source === "codex-session"
                      ? t("Codex 宿主日志")
                      : record.source.startsWith("happy-sqlite:")
                        ? t("Happy 宿主")
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
