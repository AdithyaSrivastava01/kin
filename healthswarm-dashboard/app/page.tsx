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

type Patient = {
  patient_id: string;
  name: string;
  primary_language?: string;
  insurance_id?: string;
};

type DocMeta = {
  doc_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  description?: string | null;
  uploaded_at?: string | null;
};

const RELAY = process.env.NEXT_PUBLIC_RELAY_URL ?? "http://localhost:3001";

function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

const nodeStyle = (border: string) => ({
  background: "#0f172a",
  color: "#f1f5f9",
  border: `3px solid ${border}`,
  borderRadius: 14,
  padding: "12px 18px",
  fontWeight: 700,
  fontSize: 15,
  width: 190,
  textAlign: "center" as const,
  boxShadow: `0 0 16px ${border}33`,
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
            style: { stroke: color, strokeWidth: 3 },
            labelStyle: { fill: "#f1f5f9", fontSize: 13, fontWeight: 700 },
            labelBgStyle: { fill: "#0f172a", fillOpacity: 0.92, stroke: color, strokeWidth: 1 },
            labelBgPadding: [6, 4],
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
          <div className="absolute top-16 right-4 z-10 bg-amber-500/20 border-2 border-amber-400 text-amber-100 px-5 py-3 rounded-lg animate-pulse text-base font-bold shadow-2xl shadow-amber-500/30">
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
        <UploadPanel />

        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 mt-6">
          Live payloads
        </h2>
        {feed.length === 0 && (
          <p className="text-slate-600 text-sm">Waiting for agent activity…</p>
        )}
        {feed.map((evt, i) => (
          <div key={`${evt.received_at}-${i}`} className="mb-3">
            <div className="flex items-center gap-2 text-[13px] text-slate-400 mb-1">
              <span className="text-emerald-400 font-semibold">{evt.src}</span>
              <span>→</span>
              <span className="text-sky-400 font-semibold">{evt.dst}</span>
              <span
                className="ml-auto px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider"
                style={{
                  background: `${KIND_COLOR[evt.kind] ?? DEFAULT_EDGE_COLOR}22`,
                  color: KIND_COLOR[evt.kind] ?? DEFAULT_EDGE_COLOR,
                }}
              >
                {evt.kind}
              </span>
            </div>
            <pre className="text-[13px] bg-slate-950 p-2.5 rounded border border-slate-800 overflow-x-auto leading-snug text-slate-200">
{JSON.stringify(evt.payload, null, 2)}
            </pre>
          </div>
        ))}
      </aside>
    </div>
  );
}

function UploadPanel() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [docs, setDocs] = useState<DocMeta[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Load patient roster once
  useEffect(() => {
    fetch(`${RELAY}/patients`)
      .then((r) => r.json())
      .then((rows: Patient[]) => {
        setPatients(rows);
        if (rows.length && !selected) setSelected(rows[0].patient_id);
      })
      .catch((e) => setError(`couldn't load patients: ${e}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refresh document list whenever the selected patient changes
  useEffect(() => {
    if (!selected) return;
    fetch(`${RELAY}/documents/${selected}`)
      .then((r) => r.json())
      .then(setDocs)
      .catch(() => setDocs([]));
  }, [selected]);

  const upload = async () => {
    if (!file || !selected) return;
    setBusy(true); setError(null); setSuccess(null);
    try {
      const fd = new FormData();
      fd.append("patient_id", selected);
      fd.append("file", file);
      if (description) fd.append("description", description);

      const r = await fetch(`${RELAY}/upload`, { method: "POST", body: fd });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? `HTTP ${r.status}`);

      setSuccess(`uploaded ${body.filename} (${fmtBytes(body.size_bytes)})`);
      setFile(null);
      setDescription("");

      // Refresh list
      const r2 = await fetch(`${RELAY}/documents/${selected}`);
      setDocs(await r2.json());
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const selectedPatient = patients.find((p) => p.patient_id === selected);

  return (
    <section>
      <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
        📄 Upload patient document
      </h2>

      <div className="space-y-2">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200"
        >
          {patients.map((p) => (
            <option key={p.patient_id} value={p.patient_id}>
              {p.name} ({p.patient_id} · {p.primary_language})
            </option>
          ))}
        </select>

        <input
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-xs text-slate-300
                     file:mr-3 file:py-1.5 file:px-3 file:rounded
                     file:border-0 file:bg-emerald-600 file:text-white
                     file:font-semibold hover:file:bg-emerald-500
                     file:cursor-pointer"
        />

        <input
          type="text"
          placeholder="optional description (e.g. lab report, intake form)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-200 placeholder-slate-500"
        />

        <button
          onClick={upload}
          disabled={busy || !file || !selected}
          className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700
                     disabled:cursor-not-allowed text-white font-semibold py-1.5 rounded text-sm"
        >
          {busy ? "uploading…" : "Upload"}
        </button>

        {error && (
          <div className="text-[11px] text-red-300 bg-red-900/30 border border-red-700 px-2 py-1 rounded">
            {error}
          </div>
        )}
        {success && (
          <div className="text-[11px] text-emerald-300 bg-emerald-900/30 border border-emerald-700 px-2 py-1 rounded">
            ✓ {success}
          </div>
        )}
      </div>

      {selectedPatient && (
        <div className="mt-3">
          <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-1">
            {selectedPatient.name}'s documents ({docs.length})
          </div>
          {docs.length === 0 ? (
            <p className="text-slate-600 text-xs italic">no documents uploaded yet</p>
          ) : (
            <ul className="space-y-1">
              {docs.map((d) => (
                <li
                  key={d.doc_id}
                  className="flex items-center gap-2 bg-slate-950 border border-slate-800 px-2 py-1.5 rounded text-xs"
                >
                  <a
                    href={`${RELAY}/document/${d.doc_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-emerald-300 hover:text-emerald-200 hover:underline truncate flex-1"
                    title={d.description ?? ""}
                  >
                    {d.filename}
                  </a>
                  <span className="text-slate-500 shrink-0">
                    {fmtBytes(d.size_bytes)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
