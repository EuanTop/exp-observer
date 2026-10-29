import { Crosshair, ChevronDown, CircleDashed } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type FocusSnapshot, type RuntimeSnapshot } from "../api";
import {
  activeWorkNodeIds,
  currentWork,
  type WorkGroup,
} from "../current-work";
import { t, useLocale } from "../i18n";
import type { Project } from "../model";
import "./current-work.css";

export function WorkChoices({
  project,
  groups,
  onSelect,
}: {
  project: Project;
  groups: WorkGroup[];
  onSelect: (id: string) => void;
}) {
  return (
    <div className="current-work-choices">
      {groups.map((group) => (
        <section key={group.id} className={group.state}>
          <div className="current-work-owner">
            <strong>
              {group.source === "command"
                ? t("命令执行")
                : group.source === "external"
                  ? t("外部任务 · {title}", { title: group.label })
                  : group.label ||
                    t("对话 {id}", { id: group.ownerId.slice(-8) })}
            </strong>
            <span>
              {group.state === "active"
                ? group.source === "external"
                  ? t("任务未结束")
                  : group.source === "command"
                    ? t("运行中")
                    : t("正在聚焦")
                : t("已失联")}
            </span>
          </div>
          {group.nodeIds.map((id) => (
            <button key={id} onClick={() => onSelect(id)}>
              {group.state === "active" ? (
                <Crosshair size={14} />
              ) : (
                <CircleDashed size={14} />
              )}
              <span>{project.nodes.find((node) => node.id === id)?.title}</span>
            </button>
          ))}
        </section>
      ))}
      {!groups.length && <p>{t("当前没有聚焦节点")}</p>}
    </div>
  );
}

export function CurrentWork({
  project,
  runtime,
  onSelect,
}: {
  project: Project;
  runtime: RuntimeSnapshot | null;
  onSelect: (id: string) => void;
}) {
  useLocale();
  const [snapshot, setSnapshot] = useState<FocusSnapshot | null>(null);
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState({ left: 12, top: 100, width: 350 });
  const [clock, setClock] = useState(Date.now());
  const [unavailable, setUnavailable] = useState(false);
  const holder = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setSnapshot(null);
    setOpen(false);
    setUnavailable(false);
    const controller = new AbortController();
    let pending = false;
    const poll = async () => {
      if (pending || document.hidden || controller.signal.aborted) return;
      pending = true;
      try {
        const next = await api.focus(project.id, controller.signal);
        if (!controller.signal.aborted && next.projectId === project.id) {
          setSnapshot(next);
          setUnavailable(false);
        }
      } catch {
        if (!controller.signal.aborted) {
          setSnapshot(null);
          setUnavailable(true);
        }
      } finally {
        pending = false;
        if (!controller.signal.aborted) setClock(Date.now());
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 3000);
    const visible = () => void poll();
    document.addEventListener("visibilitychange", visible);
    return () => {
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [project.id]);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!holder.current?.contains(event.target as Node)) setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        event.stopPropagation();
        holder.current?.querySelector("button")?.focus();
      }
    };
    const resized = () => setOpen(false);
    window.addEventListener("resize", resized);
    document.addEventListener("pointerdown", dismiss);
    holder.current?.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("resize", resized);
      document.removeEventListener("pointerdown", dismiss);
      holder.current?.removeEventListener("keydown", key);
    };
  }, [open]);
  const groups = currentWork(project, snapshot, runtime, clock);
  const ids = activeWorkNodeIds(groups);
  const toggleChoices = () => {
    const rect = holder.current?.getBoundingClientRect();
    if (rect) {
      const width = Math.min(350, window.innerWidth - 24);
      setAnchor({
        width,
        left: Math.max(
          12,
          Math.min(rect.right - width, window.innerWidth - width - 12),
        ),
        top: rect.bottom + 9,
      });
    }
    setOpen(!open);
  };
  const jump = (id: string) => {
    setOpen(false);
    onSelect(id);
  };
  return (
    <div className="current-work" ref={holder}>
      <button
        className={`button current-work-button${ids.length ? " has-focus" : ""}`}
        title={t("定位当前工作节点")}
        aria-label={t("定位当前工作节点")}
        aria-expanded={open}
        onClick={() => (ids.length === 1 ? jump(ids[0]) : toggleChoices())}
      >
        <Crosshair size={15} />
        <span>{t("当前工作")}</span>
        {ids.length > 0 && <b>{ids.length}</b>}
        {ids.length !== 1 && <ChevronDown size={12} />}
      </button>
      {open && (
        <div
          className="current-work-popover"
          style={{
            ...anchor,
            maxHeight: `min(480px, calc(100dvh - ${anchor.top + 12}px))`,
          }}
          role="region"
          aria-label={t("当前工作节点")}
        >
          {unavailable && (
            <p className="current-work-unavailable">{t("聚焦状态暂不可用")}</p>
          )}
          <WorkChoices project={project} groups={groups} onSelect={jump} />
        </div>
      )}
    </div>
  );
}
