"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  type Edge,
  type Node,
} from "reactflow";

type Beacon = {
  src: string;
  dst: string;
  kind: string;
  payload: Record<string, unknown>;
  received_at: string;
};

const RELAY = process.env.NEXT_PUBLIC_RELAY_URL ?? "http://localhost:3001";

const nodeStyle = (border: string) => ({
  background: "#0f172a",
  color: "#f1f5f9",
  border: `2px solid ${border}`,
  borderRadius: 14,
  padding: "10px 16px",
  fontWeight: 600,
  fontSize: 13,
  width: 170,
  textAlign: "center" as const,
});

const baseNodes: Node[] = [
  { id: "patient",        position: { x: 400, y: 10 },   data: { label: "🧍 patient" },         style: nodeStyle("#64748b") },
  { id: "swarm-intake",   position: { x: 400, y: 110 },  data: { label: "🎯 swarm-intake" },    style: nodeStyle("#3b82f6") },
  { id: "swarm-profiler", position: { x: 100, y: 240 },  data: { label: "📋 swarm-profiler" },  style: nodeStyle("#8b5cf6") },
  { id: "swarm-finder",   position: { x: 400, y: 240 },  data: { label: "🔍 swarm-finder" },    style: nodeStyle("#10b981") },
  { id: "swarm-matcher",  position: { x: 700, y: 240 },  data: { label: "⚖️ swarm-matcher" },   style: nodeStyle("#f59e0b") },
  { id: "swarm-caller",   position: { x: 400, y: 380 },  data: { label: "📞 swarm-caller" },    style: nodeStyle("#ef4444") },
  { id: "clinic",         position: { x: 400, y: 510 },  data: { label: "🏥 clinic" },          style: { ...nodeStyle("#475569"), borderStyle: "dashed", color: "#94a3b8" } },
];

const KIND_COLOR: Record<string, string> = {
  LanguageDetected: "#f59e0b",
  CallStarted:      "#ef4444",
  BookingResult:    "#ef4444",
  ProfileLoaded:    "#8b5cf6",
  CandidatesFound:  "#10b981",
  ClinicMatched:    "#f59e0b",
};
const DEFAULT_EDGE_COLOR = "#22c55e";

const EDGE_TTL_MS = 4000;

export default function Dashboard() {
  const [edges, setEdges] = useState<Edge[]>([]);
  const [feed, setFeed] = useState<Beacon[]>([]);
  const [langAlert, setLangAlert] = useState<string | null>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "disconnected">("connecting");
  const counter = useRef(0);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;

    const connect = () => {
      es = new EventSource(`${RELAY}/stream`);
      es.onopen = () => setStatus("live");
      es.onerror = () => {
        if (cancelled) return;
        setStatus("disconnected");
        es?.close();
        setTimeout(() => !cancelled && connect(), 2000);
      };
      es.onmessage = (e) => {
        let evt: Beacon;
        try { evt = JSON.parse(e.data); } catch { return; }

        // Skip animating history (older than 5s) — still show in feed
        const age = Date.now() - new Date(evt.received_at).getTime();
        const isLive = age < 5000;

        if (isLive) {
          counter.current += 1;
          const id = `e-${counter.current}`;
          const color = KIND_COLOR[evt.kind] ?? DEFAULT_EDGE_COLOR;
          const newEdge: Edge = {
            id,
            source: evt.src,
            target: evt.dst,
            animated: true,
            label: evt.kind,
            style: { stroke: color, strokeWidth: 2.5 },
            labelStyle: { fill: "#cbd5e1", fontSize: 11, fontWeight: 600 },
            labelBgStyle: { fill: "#0f172a", fillOpacity: 0.85 },
            labelBgPadding: [4, 2],
            labelBgBorderRadius: 4,
            markerEnd: { type: MarkerType.ArrowClosed, color },
          };
          setEdges((prev) => [...prev.slice(-30), newEdge]);
          setTimeout(() => {
            setEdges((prev) => prev.filter((e) => e.id !== id));
          }, EDGE_TTL_MS);

          if (evt.kind === "LanguageDetected") {
            const lang = (evt.payload as { language?: string })?.language ?? "?";
            setLangAlert(`🌐 ${lang} detected — switching voice`);
            setTimeout(() => setLangAlert(null), 6000);
          }
        }

        setFeed((f) => [evt, ...f].slice(0, 60));
      };
    };

    connect();
    return () => {
      cancelled = true;
      es?.close();
    };
  }, []);

  const statusBadge = useMemo(() => {
    if (status === "live") return { color: "bg-emerald-500", text: "LIVE" };
    if (status === "connecting") return { color: "bg-slate-500", text: "connecting" };
    return { color: "bg-red-500", text: "disconnected" };
  }, [status]);

  return (
    <div className="flex h-screen bg-slate-950">
      <main className="relative w-2/3 h-full">
        <header className="absolute top-4 left-4 z-10 pointer-events-none">
          <h1 className="text-2xl font-bold tracking-tight">🏥 HealthSwarm — War Room</h1>
          <p className="text-xs text-slate-400 mt-1">live agent coordination · {feed.length} events</p>
        </header>

        <div className="absolute top-4 right-4 z-10 flex items-center gap-2 text-xs">
          <span className={`inline-block w-2 h-2 rounded-full ${statusBadge.color} ${status === "live" ? "animate-pulse" : ""}`} />
          <span className="uppercase tracking-wider text-slate-400">{statusBadge.text}</span>
        </div>

        {langAlert && (
          <div className="absolute top-16 right-4 z-10 bg-amber-500/15 border border-amber-500 text-amber-200 px-4 py-2 rounded-lg animate-pulse text-sm font-semibold shadow-lg">
            {langAlert}
          </div>
        )}

        <ReactFlow
          nodes={baseNodes}
          edges={edges}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1e293b" gap={22} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </main>

      <aside className="w-1/3 h-full overflow-auto p-4 border-l border-slate-800 bg-slate-900/40">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Live payloads
        </h2>
        {feed.length === 0 && (
          <p className="text-slate-600 text-sm">Waiting for agent activity…</p>
        )}
        {feed.map((evt, i) => (
          <div key={`${evt.received_at}-${i}`} className="mb-3">
            <div className="flex items-center gap-2 text-[11px] text-slate-500 mb-1">
              <span className="text-emerald-400">{evt.src}</span>
              <span>→</span>
              <span className="text-sky-400">{evt.dst}</span>
              <span
                className="ml-auto px-1.5 py-0.5 rounded text-[10px] font-semibold"
                style={{
                  background: `${KIND_COLOR[evt.kind] ?? DEFAULT_EDGE_COLOR}22`,
                  color: KIND_COLOR[evt.kind] ?? DEFAULT_EDGE_COLOR,
                }}
              >
                {evt.kind}
              </span>
            </div>
            <pre className="text-[11px] bg-slate-950 p-2 rounded border border-slate-800 overflow-x-auto leading-snug text-slate-300">
{JSON.stringify(evt.payload, null, 2)}
            </pre>
          </div>
        ))}
      </aside>
    </div>
  );
}
