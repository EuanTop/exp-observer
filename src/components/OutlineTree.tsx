import { Box, ChevronDown, ChevronRight, Layers } from "lucide-react";
import { useState } from "react";
import { type ResearchNode } from "../model";

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
  const [closed, setClosed] = useState<string[]>([]);
  return (
    <>
      {nodes
        .filter((n) => n.parentId === parentId)
        .map((n) => {
          const children = nodes.some((c) => c.parentId === n.id);
          const Icon = children ? Layers : kindIcon[n.kind] || Box;
          return (
            <div key={n.id}>
              <div
                className={`tree-row ${selected === n.id ? "selected" : ""} ${n.importance === "critical" ? "is-critical" : ""}`}
                style={{ paddingLeft: 12 + depth * 13 }}
              >
                <button
                  className="tree-expand"
                  aria-label={closed.includes(n.id) ? "展开路径" : "折叠路径"}
                  onClick={() =>
                    setClosed((p) =>
                      p.includes(n.id)
                        ? p.filter((id) => id !== n.id)
                        : [...p, n.id],
                    )
                  }
                >
                  {children ? (
                    closed.includes(n.id) ? (
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
              {children && !closed.includes(n.id) && (
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
