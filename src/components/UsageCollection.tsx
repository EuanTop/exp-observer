import { t } from "../i18n";
import { useEffect, useState } from "react";
import { api, type UsageCollection as Collection } from "../api";

const labels: Record<string, string> = {
  "no-captures": "尚无可关联的研究记录",
  "log-not-found": "未找到宿主日志",
  "log-unreadable": "宿主日志无法读取",
  "receipt-unmatched": "尚未匹配记录回执",
  "no-usage": "宿主尚未报告用量",
  "awaiting-checkpoint": "等待记录区间闭合",
  collected: "已采集",
  error: "采集异常",
};

export function UsageCollection({ projectId }: { projectId: string }) {
  const [snapshot, setSnapshot] = useState<Collection | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false,
      pending = false;
    setSnapshot(null);
    setFailed(false);
    const poll = async () => {
      if (pending || document.hidden) return;
      pending = true;
      try {
        const next = await api.usageStatus(projectId);
        if (!cancelled) {
          setSnapshot(next);
          setFailed(false);
        }
      } catch {
        if (!cancelled) setFailed(true);
      } finally {
        pending = false;
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [projectId]);
  return (
    <details className="usage-collection">
      <summary>
        {t("Token 采集")} ·{" "}
        {failed
          ? t("状态暂不可用")
          : snapshot?.adapters[0]
            ? t(labels[snapshot.adapters[0].state] || "待检查")
            : snapshot?.available === false
              ? t("服务未启用采集")
              : t("等待采集检查")}
      </summary>
      {snapshot?.adapters.map((adapter) => (
        <div key={adapter.source}>
          <div className="observation-meta">
            {adapter.source === "codex-session"
              ? t("Codex 宿主日志")
              : adapter.source}
          </div>
          <dl className="host-usage-values">
            <div>
              <dt>{t("关联记录")}</dt>
              <dd>{adapter.eligibleCaptures ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("已读日志")}</dt>
              <dd>{adapter.readableLogs ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("用量事件")}</dt>
              <dd>{adapter.nativeUsageRecords ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("匹配回执")}</dt>
              <dd>{adapter.matchedReceipts ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("已采集")}</dt>
              <dd>{adapter.collectedRecords ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("节点未分配")}</dt>
              <dd>{adapter.unassignedRecords ?? "—"}</dd>
            </div>
          </dl>
          {adapter.message && (
            <p className="usage-scope">{t(adapter.message)}</p>
          )}
        </div>
      ))}
    </details>
  );
}
