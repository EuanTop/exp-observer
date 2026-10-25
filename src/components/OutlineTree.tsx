import { t, useLocale } from "../i18n";
import { Box, ChevronDown, ChevronRight, Layers } from "lucide-react";
import { useState } from "react";
import { isVisualContainer, type ResearchNode } from "../model";

import { kindIcon, StatusMark } from "./Primitives";
export function OutlineTree({
  nodes,
  parentId,
  selected,
  onSelect,
  depth = 0,
}: {
  nodes: ResearchNode[];
  parentId: string | null;
  selected?: string;
  onSelect: (id: string) => void;
  depth?: number;
}) {
  useLocale();
  const [opened, setOpened] = useState<string[]>([]);
  return (
    <>
      {nodes
        .filter((n) => n.parentId === parentId)
        .map((n) => {
          const children = nodes.some((c) => c.parentId === n.id);
          const Icon =
            children || isVisualContainer(n) ? Layers : kindIcon[n.kind] || Box;
          return (
            <div key={n.id}>
              <div
                className={`tree-row ${selected === n.id ? "selected" : ""}`}
                style={{ paddingLeft: 12 + depth * 13 }}
              >
                <button
                  className="tree-expand"
                  aria-label={
                    !opened.includes(n.id) ? t("展开路径") : t("折叠路径")
                  }
                  onClick={() =>
                    setOpened((p) =>
                      p.includes(n.id)
                        ? p.filter((id) => id !== n.id)
                        : [...p, n.id],
                    )
                  }
                >
                  {children ? (
                    !opened.includes(n.id) ? (
                      <ChevronRight size={11} />
                    ) : (
                      <ChevronDown size={11} />
                    )
                  ) : (
                    <span />
                  )}
                </button>
                <button className="tree-node" onClick={() => onSelect(n.id)}>
                  <Icon size={13} />
                  <span>{n.title}</span>
                  <StatusMark status={n.status} className="tree-status" />
                </button>
              </div>
              {children && opened.includes(n.id) && (
                <OutlineTree
                  nodes={nodes}
                  parentId={n.id}
                  selected={selected}
                  onSelect={onSelect}
                  depth={depth + 1}
                />
              )}
            </div>
          );
        })}
    </>
  );
}
