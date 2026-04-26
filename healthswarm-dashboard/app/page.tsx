"use client";

import { useEffect, useRef, useState } from "react";
import { MarkerType, type Edge, type Node } from "reactflow";
import { Inbox, Radio, Upload as UploadIcon } from "lucide-react";
import { AppBar } from "./components/app-bar";
import { OutreachList } from "./components/outreach-list";
import { GraphCanvas } from "./components/graph-canvas";
import { UploadPanel } from "./components/upload-panel";
import { EventFeed } from "./components/event-feed";
import { LanguageToast } from "./components/toast-language-alert";
import { Tabs } from "./components/ui/tabs";
import { clinicId } from "./lib/format";
import {
  CANDIDATE_LIMIT,
  DEFAULT_EDGE_COLOR,
  EDGE_CAP,
  EDGE_TTL_MS,
  FEED_CAP,
  KIND_COLOR,
  LANG_ALERT_TTL_MS,
  RECONNECT_DELAY_MS,
  RELAY,
} from "./lib/constants";
import type { Beacon, ConnStatus, Tab } from "./lib/types";

type SidebarTab = "upload" | "feed";

export default function Dashboard() {
  const [mounted, setMounted] = useState(false);
  const [tab, setTab] = useState<Tab>("outreach");
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>("upload");
  const [edges, setEdges] = useState<Edge[]>([]);
  const [candidateNodes, setCandidateNodes] = useState<Node[]>([]);
  const [feed, setFeed] = useState<Beacon[]>([]);
  const [langAlert, setLangAlert] = useState<string | null>(null);
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const counter = useRef(0);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    let es: EventSource | null = null;
    let cancelled = false;

    const connect = () => {
      es = new EventSource(`${RELAY}/stream`);
      es.onopen = () => setStatus("live");
      es.onerror = () => {
        if (cancelled) return;
        setStatus("disconnected");
        es?.close();
        setTimeout(() => !cancelled && connect(), RECONNECT_DELAY_MS);
      };
      es.onmessage = (e) => {
        let evt: Beacon;
        try {
          evt = JSON.parse(e.data);
        } catch {
          return;
        }

        const age = Date.now() - new Date(evt.received_at).getTime();
        const isLive = age < 5000;

        if (isLive) {
          if (evt.kind === "CandidatesFound") {
            const names = ((evt.payload as { top?: string[] })?.top ?? []).slice(
              0,
              CANDIDATE_LIMIT,
            );
            setCandidateNodes(
              names.map((name, i) => ({
                id: clinicId(name),
                type: "agent",
                position: { x: 110 + i * 175, y: 530 },
                data: { role: "candidate", title: name },
              })),
            );
          }

          counter.current += 1;
          const id = `e-${counter.current}`;
          const color = KIND_COLOR[evt.kind] ?? DEFAULT_EDGE_COLOR;
          const newEdge: Edge = {
            id,
            source: evt.src,
            target: evt.dst,
            animated: true,
            label: evt.kind,
            style: { stroke: color, strokeWidth: 1.75 },
            labelStyle: {
              fill: color,
              fontSize: 11,
              fontWeight: 600,
              fontFamily: "var(--font-mono)",
            },
            labelBgStyle: {
              fill: "#FFFFFF",
              fillOpacity: 1,
              stroke: color,
              strokeOpacity: 0.4,
              strokeWidth: 1,
            },
            labelBgPadding: [6, 4],
            labelBgBorderRadius: 6,
            markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
          };
          setEdges((prev) => [...prev.slice(-EDGE_CAP), newEdge]);
          setTimeout(() => {
            setEdges((prev) => prev.filter((e) => e.id !== id));
          }, EDGE_TTL_MS);

          if (evt.kind === "LanguageDetected") {
            const lang = (evt.payload as { language?: string })?.language ?? "?";
            setLangAlert(`${lang} detected — switching voice`);
            setTimeout(() => setLangAlert(null), LANG_ALERT_TTL_MS);
          }

          if (evt.kind === "ClinicRanked") {
            const top = (
              (evt.payload as { top?: Array<{ name?: string; score?: number }> })?.top ?? []
            ).slice(0, CANDIDATE_LIMIT);
            const rankedEdges: Edge[] = top
              .filter((c) => c.name)
              .map((c, i) => ({
                id: `rank-${counter.current}-${i}`,
                source: "swarm-matcher",
                target: clinicId(c.name as string),
                animated: true,
                label: `${c.score ?? "?"}/100`,
                style: { stroke: "#D97706", strokeWidth: 1.5 },
                labelStyle: {
                  fill: "#92400E",
                  fontSize: 10,
                  fontWeight: 600,
                  fontFamily: "var(--font-mono)",
                },
                labelBgStyle: {
                  fill: "#FFFFFF",
                  fillOpacity: 1,
                  stroke: "#D97706",
                  strokeOpacity: 0.35,
                  strokeWidth: 1,
                },
                labelBgPadding: [4, 3],
                labelBgBorderRadius: 6,
                markerEnd: {
                  type: MarkerType.ArrowClosed,
                  color: "#D97706",
                  width: 14,
                  height: 14,
                },
              }));
            setEdges((prev) => [...prev.slice(-EDGE_CAP), ...rankedEdges]);
            setTimeout(() => {
              setEdges((prev) => prev.filter((e) => !rankedEdges.some((r) => r.id === e.id)));
            }, EDGE_TTL_MS);
          }
        }

        setFeed((f) => [evt, ...f].slice(0, FEED_CAP));
      };
    };

    connect();
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [mounted]);

  if (!mounted) {
    return <div className="h-screen bg-canvas" />;
  }

  return (
    <div className="flex flex-col h-screen bg-canvas">
      <AppBar tab={tab} onTabChange={setTab} status={status} eventCount={feed.length} />

      <div className="flex flex-1 min-h-0">
        <main className="relative flex-1 min-w-0 flex flex-col">
          {langAlert && <LanguageToast message={langAlert} />}

          <div className="flex-1 relative overflow-hidden">
            {tab === "outreach" ? (
              <OutreachList />
            ) : (
              <GraphCanvas edges={edges} candidateNodes={candidateNodes} />
            )}
          </div>
        </main>

        <aside className="w-[400px] shrink-0 h-full flex flex-col border-l border-line bg-surface">
          <div className="px-5 pt-5 pb-4 shrink-0">
            <Tabs
              value={sidebarTab}
              onChange={setSidebarTab}
              variant="segmented"
              size="sm"
              className="w-full"
              options={[
                { value: "upload", label: "Upload",   icon: <UploadIcon size={13} /> },
                { value: "feed",   label: "Payloads", icon: <Radio size={13} /> },
              ]}
            />
          </div>

          <div className="flex-1 overflow-auto px-5 pb-5">
            {sidebarTab === "upload" ? (
              <UploadPanel />
            ) : feed.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <span className="flex items-center justify-center w-12 h-12 rounded-full bg-muted text-ink-tertiary mb-3">
                  <Inbox size={20} />
                </span>
                <p className="text-sm font-medium text-ink-primary">No events yet</p>
                <p className="text-2xs text-ink-tertiary mt-1">
                  Live beacons will appear as agents emit them.
                </p>
              </div>
            ) : (
              <EventFeed events={feed} />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
