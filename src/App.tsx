import {
  Background,
  BackgroundVariant,
  ConnectionMode,
  MiniMap,
  ReactFlow,
  SelectionMode,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import {
  Activity,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  Files,
  FlaskConical,
  FolderOpen,
  FolderPlus,
  History,
  Layers,
  LayoutGrid,
  Maximize2,
  Moon,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Sun,
  Terminal,
  Upload,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import {
  ancestry,
  descendants,
  kinds,
  NODE_SIZE,
  isExecutionRun,
  toCanvas,
  uid,
  type Artifact,
  type CanvasData,
  type NodeTab,
  type Operation,
  type Project,
  type ProjectSummary,
} from "./model";

import {
  ArtifactDialog,
  CreateDialog,
  SkillPanel,
  type DialogState,
} from "./components/Dialogs";
import {
  EdgeInspector,
  NodeInspector,
  ProjectInspector,
} from "./components/Inspectors";
import { OutlineTree } from "./components/OutlineTree";
import { date, IconButton, time } from "./components/Primitives";
import { ResearchCard } from "./components/ResearchCard";
import { ResearchEdge } from "./components/ResearchEdge";
import { CompareView, EvidenceView, RunsView } from "./components/Views";
const nodeTypes = { research: ResearchCard };
const edgeTypes = { research: ResearchEdge };
type View = "graph" | "runs" | "compare" | "evidence";

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]),
    [project, setProject] = useState<Project | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [view, setView] = useState<View>("graph"),
    [selected, setSelected] = useState<string[]>([]),
    [edgeId, setEdgeId] = useState<string | null>(null),
    [scope, setScope] = useState<string | null>(null),
    [outline, setOutline] = useState(() => window.innerWidth >= 900),
    [inspector, setInspector] = useState(false),
    [activity, setActivity] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<NodeTab>("overview");
  const [dialog, setDialog] = useState<DialogState>(null),
    [projectMenu, setProjectMenu] = useState(false),
    [palette, setPalette] = useState(false),
    [query, setQuery] = useState(""),
    [toast, setToast] = useState(""),
    [busy, setBusy] = useState(false),
    [artifact, setArtifact] = useState<Artifact | null>(null),
    [history, setHistory] = useState<any[] | null>(null),
    [theme, setTheme] = useState(
      localStorage.getItem("exp-observer-theme") || "light",
    );
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CanvasData>>([]),
    [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const selectionRef = useRef(selected);
  selectionRef.current = selected;
  const pRef = useRef(project),
    busyRef = useRef(false),
    dragging = useRef(false),
    fileInput = useRef<HTMLInputElement>(null),
    loadedId = useRef("");
  const flow = useReactFlow();
  const selectedNode = project?.nodes.find((n) => n.id === selected[0]);
  const selectedEdge = project?.edges.find((e) => e.id === edgeId);
  useEffect(() => {
    pRef.current = project;
  }, [project]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("exp-observer-theme", theme);
  }, [theme]);
  const notify = useCallback((message: string) => {
    setToast(message);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 4200);
    return () => clearTimeout(t);
  }, [toast]);
  const load = useCallback(
    async (id: string) => {
      loadedId.current = id;
      setLoading(true);
      try {
        const p = await api.project(id);
        if (loadedId.current !== id) return;
        pRef.current = p;
        setProject(p);
        setSelected([]);
        setScope(null);
        setEdgeId(null);
        localStorage.setItem("exp-observer-project", id);
        setError("");
        setTimeout(() => flow.fitView({ padding: 0.2, duration: 400 }), 180);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [flow],
  );
  useEffect(() => {
    api
      .list()
      .then(({ projects: ps }) => {
        setProjects(ps);
        const saved = localStorage.getItem("exp-observer-project");
        if (ps.length)
          void load(ps.find((p) => p.id === saved)?.id || ps[0].id);
        else setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);
  useEffect(() => {
    const t = setInterval(async () => {
      if (busyRef.current || dragging.current || document.hidden) return;
      try {
        const { projects: ps } = await api.list();
        setProjects(ps);
        const p = pRef.current;
        const revision = ps.find((x) => x.id === p?.id)?.revision;
        if (p && revision !== undefined && revision !== p.revision) {
          const updated = await api.project(p.id);
          if (
            pRef.current?.id === p.id &&
            !busyRef.current &&
            !dragging.current
          ) {
            pRef.current = updated;
            setProject(updated);
          }
        }
        setError("");
      } catch {
        setError("连接中断，正在重连");
      }
    }, 1800);
    return () => clearInterval(t);
  }, []);
  const mutate = useCallback(
    async (operations: Operation[]) => {
      const p = pRef.current;
      if (!p || busyRef.current) return false;
      busyRef.current = true;
      setBusy(true);
      try {
        const updated = await api.batch(p, operations);
        if (pRef.current?.id === updated.id) {
          pRef.current = updated;
          setProject(updated);
        }
        return true;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          const updated = await api.project(p.id);
          pRef.current = updated;
          setProject(updated);
          notify("记录已被更新，请重试这次修改");
        } else notify((e as Error).message);
        return false;
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [notify],
  );
  const toggle = useCallback(
    (id: string) => {
      const n = pRef.current?.nodes.find((n) => n.id === id);
      if (n)
        void mutate([
          { op: "node.update", data: { id, collapsed: !n.collapsed } },
        ]);
    },
    [mutate],
  );
  const enter = useCallback(
    (id: string) => {
      setScope(id);
      setSelected([]);
      setTimeout(() => flow.fitView({ padding: 0.22, duration: 350 }), 100);
    },
    [flow],
  );
  const inspectNode = useCallback((id: string, tab: NodeTab) => {
    setSelected([id]);
    setEdgeId(null);
    setInspectorTab(tab);
    setInspector(true);
    setNodes((current) =>
      current.map((n) => ({ ...n, selected: n.id === id })),
    );
  }, []);
  useEffect(() => {
    if (!project) return;
    const canvas = toCanvas(project, scope, selectionRef.current, {
      onToggle: toggle,
      onEnter: enter,
      onInspect: inspectNode,
    });
    setNodes(canvas.nodes);
    setEdges(canvas.edges as any);
  }, [project, scope, toggle, enter, inspectNode]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPalette((v) => !v);
        return;
      }
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      if (e.key === "Escape") {
        setPalette(false);
        setDialog(null);
        setArtifact(null);
        setHistory(null);
        setSelected([]);
        setEdgeId(null);
      }
      if (e.key.toLowerCase() === "n" && !e.metaKey && !e.ctrlKey)
        setDialog({ type: "node", parentId: scope });
      if (e.key.toLowerCase() === "f")
        void flow.fitView({ padding: 0.18, duration: 350 });
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "g") {
        e.preventDefault();
        if (selected.length) setDialog({ type: "group" });
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [scope, selected, flow]);
  const handleSelection = useCallback(
    ({ nodes }: { nodes: Node[] }) =>
      setSelected((prev) => {
        const next = nodes.map((n) => n.id);
        return next.join() === prev.join() ? prev : next;
      }),
    [],
  );
  const selectNode = (id: string) => {
    setInspectorTab("overview");
    const n = project?.nodes.find((n) => n.id === id);
    if (!n) return;
    const ancestors = ancestry(project!.nodes, n.id);
    const hiddenAncestor = ancestors.slice(0, -1).find((a) => a.collapsed);
    if (hiddenAncestor) {
      setScope(n.parentId || null);
      setSelected([n.id]);
    } else {
      if (scope && !descendants(project!.nodes, scope).includes(id))
        setScope(n.parentId || null);
      setSelected([id]);
    }
    setNodes((current) =>
      current.map((item) => ({ ...item, selected: item.id === id })),
    );
    setEdgeId(null);
    setInspector(true);
    setView("graph");
    setPalette(false);
    setQuery("");
    setTimeout(() => {
      const target = flow.getNode(id);
      if (target)
        void flow.fitView({
          nodes: [target],
          padding: 1,
          duration: 350,
          maxZoom: 1,
        });
    }, 120);
  };
  const onConnect = (c: Connection) => {
    if (c.source === c.target) return;
    void mutate([
      {
        op: "edge.add",
        data: {
          id: uid("edge"),
          source: c.source,
          target: c.target,
          relation: "leads_to",
          basis: "hypothesis",
        },
      },
    ]);
  };
  const saveDrag = (_: unknown, moved: Node, movedNodes: Node[]) => {
    dragging.current = false;
    const p = pRef.current;
    if (!p) return;
    const byId = new Map(flow.getNodes().map((n) => [n.id, n]));
    function absolute(n: Node): { x: number; y: number } {
      if (!n.parentId) return n.position;
      const parent = byId.get(n.parentId);
      const pp = parent ? absolute(parent) : { x: 0, y: 0 };
      return { x: pp.x + n.position.x, y: pp.y + n.position.y };
    }
    const moving = movedNodes?.length ? movedNodes : [moved];
    const movingIds = new Set(moving.map((n) => n.id));
    const roots = moving.filter(
      (n) =>
        !ancestry(p.nodes, n.id)
          .slice(0, -1)
          .some((a) => movingIds.has(a.id)),
    );
    const changes = new Map<string, Operation>();
    for (const root of roots) {
      const original = p.nodes.find((n) => n.id === root.id);
      if (!original) continue;
      const pos = absolute(root);
      const dx = pos.x - original.position.x,
        dy = pos.y - original.position.y;
      for (const id of [root.id, ...descendants(p.nodes, root.id)]) {
        const existing = p.nodes.find((n) => n.id === id)!;
        changes.set(id, {
          op: "node.update",
          data: {
            id,
            position: {
              x: Math.round(existing.position.x + dx),
              y: Math.round(existing.position.y + dy),
            },
          },
        });
      }
    }
    void mutate([...changes.values()]);
  };
  const layout = async () => {
    if (!project) return;
    const module = await import("@dagrejs/dagre");
    const dagre = (module.default || module) as any;
    const positions = new Map<string, { x: number; y: number }>();
    const dimensions = new Map<string, { w: number; h: number }>();
    const arrange = (parentId: string | null) => {
      const group = project.nodes.filter((n) => n.parentId === parentId);
      for (const n of group) arrange(n.id);
      const g = new dagre.graphlib.Graph();
      g.setGraph({
        rankdir: "TB",
        nodesep: 65,
        ranksep: 100,
        marginx: 30,
        marginy: parentId ? 85 : 40,
      });
      g.setDefaultEdgeLabel(() => ({}));
      for (const n of group) {
        const d = dimensions.get(n.id) || NODE_SIZE;
        g.setNode(n.id, { width: d.w, height: d.h });
      }
      for (const e of project.edges)
        if (
          group.some((n) => n.id === e.source) &&
          group.some((n) => n.id === e.target)
        )
          g.setEdge(e.source, e.target);
      if (!group.length) return;
      dagre.layout(g);
      for (const n of group) {
        const a = g.node(n.id);
        positions.set(n.id, { x: a.x - a.width / 2, y: a.y - a.height / 2 });
      }
      if (parentId) {
        dimensions.set(parentId, {
          w: g.graph().width + 30,
          h: g.graph().height + 25,
        });
      }
    };
    arrange(scope);
    const absolute = (id: string): { x: number; y: number } => {
      const n = project.nodes.find((n) => n.id === id)!;
      const pos = positions.get(id) || n.position;
      if (!n.parentId || n.parentId === scope) return pos;
      const parent = absolute(n.parentId);
      return { x: parent.x + pos.x, y: parent.y + pos.y };
    };
    const ops = project.nodes
      .filter((n) => positions.has(n.id))
      .map((n) => ({
        op: "node.update",
        data: { id: n.id, position: absolute(n.id) },
      }));
    if (await mutate(ops))
      setTimeout(() => flow.fitView({ padding: 0.2, duration: 400 }), 120);
  };
  const exportProject = () => {
    if (!project) return;
    const blob = new Blob([JSON.stringify(project, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${project.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const importProject = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const p = await api.import(JSON.parse(await file.text()));
      setProjects((await api.list()).projects);
      await load(p.id);
      notify("研究已导入");
    } catch (e) {
      notify((e as Error).message);
    }
    e.target.value = "";
  };
  const openHistory = async () => {
    if (!project) return;
    try {
      const result = await api.history(project.id);
      setHistory(
        Array.isArray(result)
          ? result
          : result.history || result.revisions || [],
      );
    } catch (e) {
      notify((e as Error).message);
    }
  };
  const deleteSelected = async () => {
    const ops: Operation[] = edgeId
      ? [{ op: "edge.delete", data: { id: edgeId } }]
      : selected.map((id) => ({ op: "node.delete", data: { id } }));
    if (ops.length && (await mutate(ops))) {
      setSelected([]);
      setEdgeId(null);
      notify("已移除，可从历史版本恢复");
    }
  };
  const graphCount = project?.nodes.length || 0;
  const running =
    project?.runs.filter((r) => r.status === "running").length || 0;
  const mainTabs: { id: View; label: string; icon: typeof Network }[] = [
    { id: "graph", label: "研究图", icon: Network },
    { id: "runs", label: "运行", icon: FlaskConical },
    { id: "compare", label: "对比", icon: LayoutGrid },
    { id: "evidence", label: "证据", icon: Files },
  ];

  return (
    <div className="app-shell">
      <div className="workspace">
        <header className="topbar">
          <div className="wordmark">ExpObserver</div>
          <span className="topbar-divider" />
          <div className="project-switcher">
            <button
              className="project-switch"
              onClick={() => setProjectMenu(!projectMenu)}
            >
              <FolderOpen size={15} />
              <span>{project?.name || "选择研究项目"}</span>
              <ChevronDown size={13} />
            </button>
            {projectMenu && (
              <>
                <div
                  className="dismiss"
                  onClick={() => setProjectMenu(false)}
                />
                <div className="dropdown project-dropdown">
                  <div className="dropdown-caption">研究项目</div>
                  {projects.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => {
                        void load(p.id);
                        setProjectMenu(false);
                      }}
                    >
                      <span className="project-dot" />
                      <span>{p.name}</span>
                      {p.id === project?.id && <Check size={14} />}
                    </button>
                  ))}
                  <div className="dropdown-line" />
                  <button
                    onClick={() => {
                      setDialog({ type: "project" });
                      setProjectMenu(false);
                    }}
                  >
                    <Plus size={15} />
                    新建研究
                  </button>
                  <button
                    onClick={() => {
                      fileInput.current?.click();
                      setProjectMenu(false);
                    }}
                  >
                    <Upload size={15} />
                    导入 JSON
                  </button>
                </div>
              </>
            )}
          </div>
          <nav className="top-nav" aria-label="研究视图">
            {mainTabs.map((t) => (
              <button
                key={t.id}
                aria-pressed={view === t.id}
                className={view === t.id ? "selected" : ""}
                onClick={() => setView(t.id)}
              >
                <t.icon size={15} />
                {t.label}
                {t.id === "runs" &&
                  !!project?.runs.filter(isExecutionRun).length && (
                    <span>{project.runs.filter(isExecutionRun).length}</span>
                  )}
              </button>
            ))}
          </nav>
          <div className="topbar-right">
            <span className={`connection ${error ? "disconnected" : ""}`}>
              <span />
              {error ? "重新连接" : busy ? "保存中" : "已保存至本地"}
            </span>
            <button
              className="search-trigger"
              onClick={() => {
                setPalette(true);
                setQuery("");
              }}
            >
              <Search size={14} />
              <span>搜索</span>
              <kbd>⌘ K</kbd>
            </button>
            <IconButton
              label="连接 Agent"
              onClick={() => {
                setPalette(true);
                setQuery(">skill");
              }}
            >
              <Terminal size={17} />
            </IconButton>
            <IconButton
              label={theme === "dark" ? "浅色外观" : "深色外观"}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </IconButton>
            <IconButton
              label="导出研究 JSON"
              onClick={exportProject}
              disabled={!project}
            >
              <Download size={17} />
            </IconButton>
            <IconButton
              label="版本历史"
              onClick={() => void openHistory()}
              disabled={!project}
            >
              <History size={17} />
            </IconButton>
          </div>
        </header>
        <div className="work-area">
          {outline && (
            <aside className="outline">
              <div className="outline-heading">
                <span>
                  研究目录 <small>{graphCount}</small>
                </span>
                <IconButton label="收起导航" onClick={() => setOutline(false)}>
                  <PanelLeftClose size={14} />
                </IconButton>
              </div>
              <button
                className="workspace-item selected"
                onClick={() => {
                  setScope(null);
                  setView("graph");
                  setTimeout(
                    () => flow.fitView({ padding: 0.2, duration: 300 }),
                    100,
                  );
                }}
              >
                <Network size={15} />
                <span>研究全景</span>
                <span className="count">{graphCount}</span>
              </button>
              <div className="outline-tree">
                {project && (
                  <OutlineTree
                    nodes={project.nodes}
                    parentId={null}
                    selected={selected[0]}
                    onSelect={selectNode}
                  />
                )}
              </div>
              <div className="outline-footer">
                <span className="tiny-dot accent" />
                <span>
                  {project?.runs.filter(isExecutionRun).length || 0} 次运行
                </span>
                <span className="outline-footer-right">
                  {project?.artifacts.length || 0} 份证据
                </span>
              </div>
            </aside>
          )}
          <main className="main-area">
            <div className="work-toolbar">
              <IconButton
                label={outline ? "收起研究目录" : "展开研究目录"}
                onClick={() => setOutline(!outline)}
              >
                <PanelLeftOpen size={16} />
              </IconButton>
              <h1>
                {view === "graph" && scope
                  ? project?.nodes.find((n) => n.id === scope)?.title
                  : mainTabs.find((t) => t.id === view)?.label}
              </h1>
              {view === "graph" && (
                <span className="toolbar-count">{graphCount} 个节点</span>
              )}
              {project?.id === "retrieval-demo" && (
                <span className="origin-tag">模拟研究</span>
              )}
              <div className="view-tab-right">
                {running > 0 && (
                  <span className="live-indicator">
                    <span />
                    {running} 个运行中
                  </span>
                )}
                {view === "graph" && (
                  <>
                    <IconButton
                      label="自动布局"
                      onClick={() => void layout()}
                      disabled={!project}
                    >
                      <LayoutGrid size={15} />
                    </IconButton>
                    <IconButton
                      label="切换详情面板"
                      active={inspector}
                      onClick={() => setInspector(!inspector)}
                    >
                      <Settings2 size={15} />
                    </IconButton>
                  </>
                )}
                <button
                  className="button primary compact-add"
                  onClick={() =>
                    setDialog(
                      project
                        ? { type: "node", parentId: scope }
                        : { type: "project" },
                    )
                  }
                >
                  <Plus size={14} />
                  {project ? "添加节点" : "新建研究"}
                </button>
              </div>
            </div>
            {error && !project ? (
              <div className="empty-state">
                <Network size={34} />
                <h2>连接本地工作空间</h2>
                <p>{error}</p>
                <button className="button" onClick={() => location.reload()}>
                  <RefreshCw size={14} />
                  重新连接
                </button>
              </div>
            ) : loading && !project ? (
              <div className="empty-state">
                <span className="spinner" />
                <p>正在打开研究…</p>
              </div>
            ) : !project ? (
              <div className="empty-state">
                <Network size={38} />
                <h2>从一个问题开始</h2>
                <button
                  className="button primary"
                  onClick={() => setDialog({ type: "project" })}
                >
                  <Plus size={15} />
                  新建研究
                </button>
                <button
                  className="text-button"
                  onClick={() => fileInput.current?.click()}
                >
                  导入已有研究
                </button>
              </div>
            ) : (
              <div className="view-body">
                {view === "graph" ? (
                  <>
                    <div className="graph-canvas">
                      <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        nodeTypes={nodeTypes}
                        edgeTypes={edgeTypes}
                        connectionMode={ConnectionMode.Loose}
                        onNodesChange={onNodesChange}
                        onEdgesChange={onEdgesChange}
                        onConnect={onConnect}
                        onSelectionChange={handleSelection}
                        onNodeClick={(_, n) => {
                          setInspectorTab("overview");
                          setSelected([n.id]);
                          setEdgeId(null);
                          setInspector(true);
                        }}
                        onEdgeClick={(_, e) => {
                          setEdgeId(e.id);
                          setSelected([]);
                          setInspector(true);
                        }}
                        onPaneClick={() => {
                          setEdgeId(null);
                        }}
                        onNodeDoubleClick={(_, n) => {
                          if (project.nodes.some((c) => c.parentId === n.id))
                            enter(n.id);
                        }}
                        onNodeDragStart={() => {
                          dragging.current = true;
                        }}
                        onNodeDragStop={saveDrag}
                        onMoveEnd={(_, viewport) =>
                          localStorage.setItem(
                            `exp-observer-viewport-${project.id}-${scope}`,
                            JSON.stringify(viewport),
                          )
                        }
                        defaultViewport={JSON.parse(
                          localStorage.getItem(
                            `exp-observer-viewport-${project.id}-${scope}`,
                          ) || '{"x":0,"y":0,"zoom":0.8}',
                        )}
                        fitView
                        fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
                        minZoom={0.15}
                        maxZoom={1.8}
                        selectionMode={SelectionMode.Partial}
                        selectionOnDrag
                        panOnDrag={[1, 2]}
                        panOnScroll
                        zoomOnScroll={false}
                        deleteKeyCode={null}
                        colorMode={theme === "light" ? "light" : "dark"}
                        proOptions={{ hideAttribution: true }}
                        aria-label="研究图画布"
                      >
                        <Background
                          variant={BackgroundVariant.Dots}
                          gap={22}
                          size={1}
                          color={theme === "light" ? "#d4d4d8" : "#303036"}
                        />
                        <MiniMap
                          pannable
                          zoomable
                          nodeColor={(n) =>
                            n.selected
                              ? "#2563eb"
                              : theme === "light"
                                ? "#a1a1aa"
                                : "#52525b"
                          }
                          maskColor={
                            theme === "light" ? "#fafafacc" : "#18181bcc"
                          }
                          style={{ background: "var(--panel)" }}
                        />
                      </ReactFlow>
                      <div className="canvas-top-left">
                        {scope ? (
                          <div className="canvas-crumb">
                            <button
                              onClick={() => {
                                setScope(null);
                                setTimeout(
                                  () =>
                                    flow.fitView({
                                      padding: 0.2,
                                      duration: 300,
                                    }),
                                  80,
                                );
                              }}
                            >
                              全景
                            </button>
                            {ancestry(project.nodes, scope).map((n) => (
                              <span key={n.id}>
                                <ChevronRight size={11} />
                                <button onClick={() => enter(n.id)}>
                                  {n.title}
                                </button>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="canvas-label">
                            <span className="tiny-dot accent" />
                            探索视图
                          </span>
                        )}
                      </div>
                      {!nodes.length && (
                        <div className="canvas-empty">
                          <Plus size={24} />
                          <span>添加第一个研究节点</span>
                          <button
                            className="button"
                            onClick={() =>
                              setDialog({ type: "node", parentId: scope })
                            }
                          >
                            添加节点
                          </button>
                        </div>
                      )}
                      <div className="canvas-controls">
                        <IconButton
                          label="放大"
                          onClick={() => flow.zoomIn({ duration: 180 })}
                        >
                          <ZoomIn size={16} />
                        </IconButton>
                        <IconButton
                          label="缩小"
                          onClick={() => flow.zoomOut({ duration: 180 })}
                        >
                          <ZoomOut size={16} />
                        </IconButton>
                        <span className="control-divider" />
                        <IconButton
                          label="适应画布 · F"
                          onClick={() =>
                            flow.fitView({ padding: 0.2, duration: 350 })
                          }
                        >
                          <Maximize2 size={15} />
                        </IconButton>
                        <span className="control-divider" />
                        <button
                          className="activity-toggle"
                          onClick={() => setActivity(!activity)}
                        >
                          <Activity size={14} />
                          动态
                          {project.activity?.length > 0 && (
                            <span>{project.activity.length}</span>
                          )}
                        </button>
                      </div>
                      {selected.length > 1 && (
                        <div className="selection-toolbar">
                          <span>已选择 {selected.length} 个节点</span>
                          <button onClick={() => setDialog({ type: "group" })}>
                            <Layers size={14} />
                            放入容器
                          </button>
                        </div>
                      )}
                    </div>
                    {inspector && (
                      <aside className="inspector">
                        {selectedNode ? (
                          <NodeInspector
                            key={selectedNode.id}
                            node={selectedNode}
                            project={project}
                            busy={busy}
                            tab={inspectorTab}
                            onTabChange={setInspectorTab}
                            mutate={mutate}
                            onClose={() => setInspector(false)}
                            onBranch={() =>
                              setDialog({
                                type: "branch",
                                source: selectedNode.id,
                                parentId: selectedNode.parentId,
                              })
                            }
                            onChild={() =>
                              setDialog({
                                type: "node",
                                parentId: selectedNode.id,
                              })
                            }
                            onDelete={() => void deleteSelected()}
                            onArtifact={setArtifact}
                            onSelect={selectNode}
                            onConnect={() =>
                              setDialog({
                                type: "connect",
                                source: selectedNode.id,
                              })
                            }
                          />
                        ) : selectedEdge ? (
                          <EdgeInspector
                            edge={selectedEdge}
                            mutate={mutate}
                            onDelete={() => void deleteSelected()}
                          />
                        ) : (
                          <ProjectInspector
                            project={project}
                            onAdd={() =>
                              setDialog({ type: "node", parentId: scope })
                            }
                            onSelect={selectNode}
                            onClose={() => setInspector(false)}
                          />
                        )}
                      </aside>
                    )}
                  </>
                ) : view === "runs" ? (
                  <RunsView
                    project={project}
                    onArtifact={setArtifact}
                    onNode={selectNode}
                  />
                ) : view === "compare" ? (
                  <CompareView project={project} />
                ) : (
                  <EvidenceView
                    project={project}
                    onOpen={setArtifact}
                    onAdd={() => setDialog({ type: "artifact" })}
                  />
                )}
              </div>
            )}
            {activity && project && (
              <div className="activity-drawer">
                <div className="drawer-heading">
                  <span>
                    <Activity size={14} />
                    研究动态
                  </span>
                  <IconButton
                    label="关闭动态"
                    onClick={() => setActivity(false)}
                  >
                    <X size={14} />
                  </IconButton>
                </div>
                <div className="activity-list">
                  {[...project.activity]
                    .reverse()
                    .slice(0, 40)
                    .map((a, i) => (
                      <div key={a.id || i}>
                        <span className="activity-dot" />
                        <time>{time(a.at)}</time>
                        <span>
                          {a.message ||
                            a.operations
                              ?.map(
                                (o) =>
                                  ({
                                    "node.add": "新增节点",
                                    "node.update": "更新节点",
                                    "run.add": "开始运行",
                                    "run.update": "更新运行",
                                    "run.event": "运行事件",
                                    "assessment.add": "登记评估",
                                    "edge.add": "连接节点",
                                    "decision.add": "记录结论",
                                    "project.update": "更新项目",
                                  })[o.op] || o.op,
                              )
                              .join(" · ") ||
                            a.type ||
                            "研究已更新"}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            )}
            <footer className="statusbar">
              <span>
                <span className="tiny-dot accent" />
                ExpObserver
              </span>
              <span>{project ? `r${project.revision}` : "本地工作空间"}</span>
              <div />
              <span className="statusbar-hint">
                拖动平移 · Shift 框选 · F 适应画布
              </span>
              <button
                onClick={() => {
                  setPalette(true);
                  setQuery(">skill");
                }}
              >
                <Terminal size={12} />
                Agent 接入
                <ArrowUpRight size={11} />
              </button>
            </footer>
          </main>
        </div>
      </div>
      <input
        ref={fileInput}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={importProject}
      />
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={16} />
          {toast}
          <button onClick={() => setToast("")}>
            <X size={13} />
          </button>
        </div>
      )}
      {dialog && (
        <CreateDialog
          dialog={dialog}
          project={project}
          selected={selected}
          onClose={() => setDialog(null)}
          mutate={mutate}
          onCreated={async (p) => {
            setProjects((await api.list()).projects);
            await load(p.id);
          }}
          onNodeCreated={(id) => {
            setView("graph");
            setSelected([id]);
            setInspector(true);
          }}
          notify={notify}
          flowCenter={() =>
            flow.screenToFlowPosition({
              x: window.innerWidth / 2,
              y: window.innerHeight / 2,
            })
          }
        />
      )}
      {palette && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setPalette(false);
          }}
        >
          <div className="command-palette">
            <div className="palette-input">
              <Search size={18} />
              <input
                autoFocus
                placeholder="搜索节点、研究，或输入操作…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <kbd onClick={() => setPalette(false)}>Esc</kbd>
            </div>
            {query.startsWith(">skill") ? (
              <SkillPanel project={project} notify={notify} />
            ) : (
              <div className="palette-results">
                {!query && (
                  <>
                    <button
                      onClick={() => {
                        setPalette(false);
                        setDialog({ type: "node", parentId: scope });
                      }}
                    >
                      <Plus size={16} />
                      添加研究节点<kbd>N</kbd>
                    </button>
                    <button
                      onClick={() => {
                        setPalette(false);
                        setDialog({ type: "project" });
                      }}
                    >
                      <FolderPlus size={16} />
                      新建研究
                    </button>
                    <button onClick={() => setQuery(">skill")}>
                      <Terminal size={16} />
                      连接 Agent 与 Skill
                    </button>
                    <div className="dropdown-caption">研究节点</div>
                  </>
                )}
                {project?.nodes
                  .filter((n) =>
                    `${n.title} ${n.summary} ${n.tags.join(" ")}`
                      .toLowerCase()
                      .includes(query.toLowerCase()),
                  )
                  .slice(0, 12)
                  .map((n) => (
                    <button key={n.id} onClick={() => selectNode(n.id)}>
                      <span
                        className={`tiny-dot ${n.status === "active" ? "accent" : ""}`}
                      />
                      <span>{n.title}</span>
                      <small>{kinds[n.kind] || n.kind}</small>
                    </button>
                  ))}
                {query &&
                  projects
                    .filter((p) =>
                      p.name.toLowerCase().includes(query.toLowerCase()),
                    )
                    .map((p) => (
                      <button
                        key={p.id}
                        onClick={() => {
                          void load(p.id);
                          setPalette(false);
                        }}
                      >
                        <FolderOpen size={16} />
                        {p.name}
                      </button>
                    ))}
              </div>
            )}
          </div>
        </div>
      )}
      {artifact && project && (
        <ArtifactDialog
          artifact={artifact}
          project={project}
          onClose={() => setArtifact(null)}
        />
      )}
      {history && project && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setHistory(null);
          }}
        >
          <div className="modal history-modal">
            <div className="modal-heading">
              <h2>版本历史</h2>
              <IconButton label="关闭" onClick={() => setHistory(null)}>
                <X size={17} />
              </IconButton>
            </div>
            <div className="history-list">
              {[...history].reverse().map((h, i) => (
                <div key={i}>
                  <History size={16} />
                  <div>
                    <strong>版本 {h.revision}</strong>
                    <span>
                      {date(h.at || h.updatedAt || h.createdAt)}
                      {h.message ? ` · ${h.message}` : ""}
                    </span>
                  </div>
                  <button
                    className="button subtle"
                    disabled={h.revision === project.revision}
                    onClick={async () => {
                      try {
                        const p = await api.restore(project, h.revision);
                        pRef.current = p;
                        setProject(p);
                        setHistory(null);
                        notify("已恢复为新版本");
                      } catch (e) {
                        notify((e as Error).message);
                      }
                    }}
                  >
                    {h.revision === project.revision ? "当前版本" : "恢复"}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
