import {
  Braces,
  CheckCircle2,
  FileText,
  FlaskConical,
  Layers,
  Lightbulb,
  ListTree,
  Target,
} from "lucide-react";
import type { ReactNode } from "react";
import { statuses } from "../model";
export const kindIcon: Record<string, typeof Target> = {
  goal: Target,
  question: Lightbulb,
  hypothesis: Lightbulb,
  experiment: FlaskConical,
  algorithm: Braces,
  finding: Lightbulb,
  decision: CheckCircle2,
  group: Layers,
  reference: FileText,
  plan: ListTree,
};
export const time = (s?: string | null) =>
  s
    ? new Date(s).toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
export const date = (s?: string | null) =>
  s
    ? new Date(s).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
export function IconButton({
  label,
  children,
  onClick,
  active = false,
  disabled = false,
}: {
  label: string;
  children: ReactNode;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      className={`icon-button ${active ? "active" : ""}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}
export function StatusMark({
  status,
  className = "",
  decorative = false,
}: {
  status: string;
  className?: string;
  decorative?: boolean;
}) {
  const state = status === "running" ? "active" : status;
  const ring = (
    <circle
      cx="8"
      cy="8"
      r="6.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeDasharray="2 2"
    />
  );
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      className={`status-symbol status-${status} ${className}`}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : statuses[status] || status}
      aria-hidden={decorative || undefined}
    >
      {state === "completed" ? (
        <>
          <circle cx="8" cy="8" r="7" fill="currentColor" />
          <path
            d="m4.7 8 2.1 2.2 4.5-4.6"
            fill="none"
            stroke="#fff"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      ) : state === "rejected" ? (
        <path
          d="M3 8h10"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      ) : state === "failed" ? (
        <path
          d="m4 4 8 8M12 4l-8 8"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      ) : state === "paused" ? (
        <>
          {ring}
          <path
            d="M6.2 5.6v4.8M9.8 5.6v4.8"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </>
      ) : state === "active" ? (
        <>
          <circle
            className="status-spinner"
            cx="8"
            cy="8"
            r="6.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeDasharray="28 13"
            transform="rotate(-90 8 8)"
          />
          <circle cx="8" cy="8" r="2" fill="currentColor" />
        </>
      ) : state === "invalid" ? (
        <>
          <circle
            cx="8"
            cy="8"
            r="6.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
          />
          <path d="m4 12 8-8" stroke="currentColor" strokeWidth="1.5" />
        </>
      ) : (
        ring
      )}
    </svg>
  );
}
export function Badge({ status }: { status: string }) {
  return (
    <span className={`status-badge status-${status}`}>
      <StatusMark status={status} decorative />
      {statuses[status] || status}
    </span>
  );
}
