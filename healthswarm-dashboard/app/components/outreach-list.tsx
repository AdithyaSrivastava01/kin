"use client";

import { useEffect, useState } from "react";
import {
  Calendar,
  CheckCircle2,
  Clock,
  Inbox,
  Languages,
  MapPin,
  PhoneCall,
  PhoneOff,
  Phone,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import { StatCard } from "./stat-card";
import { StatusText } from "./ui/badge";
import { fmtTimeAgo } from "../lib/format";
import {
  OUTCOME_META,
  POLL_INTERVAL_MS,
  RELAY,
  type OutcomeKey,
} from "../lib/constants";
import type { Outreach, OutreachStats } from "../lib/types";

export function OutreachList() {
  const [stats, setStats] = useState<OutreachStats | null>(null);
  const [list, setList] = useState<Outreach[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      try {
        const [s, l] = await Promise.all([
          fetch(`${RELAY}/outreach/stats`).then((r) => r.json()),
          fetch(`${RELAY}/outreach?limit=50`).then((r) => r.json()),
        ]);
        if (!alive) return;
        setStats(s);
        setList(l);
        setLoading(false);
      } catch {
        /* keep last good values */
      }
    };
    refresh();
    const t = setInterval(refresh, POLL_INTERVAL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <div className="absolute inset-0 overflow-auto">
      <div className="px-7 py-6 space-y-6 max-w-[1400px]">
        <section>
          <h2 className="text-xs font-semibold text-ink-tertiary uppercase tracking-[0.08em] mb-3">
            Today at a glance
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
            <StatCard
              label="Total reach-outs"
              value={stats?.total ?? 0}
              tone="neutral"
              icon={<PhoneCall size={16} strokeWidth={2} />}
            />
            <StatCard
              label="Booked"
              value={stats?.booked ?? 0}
              tone="success"
              icon={<CheckCircle2 size={16} strokeWidth={2} />}
            />
            <StatCard
              label="No answer"
              value={stats?.no_answer ?? 0}
              tone="neutral"
              icon={<PhoneOff size={16} strokeWidth={2} />}
            />
            <StatCard
              label="Lang mismatch"
              value={stats?.language_mismatch ?? 0}
              tone="warning"
              icon={<TriangleAlert size={16} strokeWidth={2} />}
            />
            <StatCard
              label="In progress"
              value={stats?.in_progress ?? 0}
              tone="info"
              icon={<Clock size={16} strokeWidth={2} />}
            />
          </div>
        </section>

        <section className="bg-surface border border-line rounded-2xl shadow-card overflow-hidden">
          <div className="flex items-center justify-between px-6 h-14 border-b border-line">
            <div>
              <h2 className="text-sm font-semibold text-ink-primary leading-none">
                Recent outreach
              </h2>
              <p className="text-2xs text-ink-tertiary mt-1">
                Per-attempt summary across every clinic call
              </p>
            </div>
            <span className="text-xs text-ink-tertiary font-mono">
              {list.length} {list.length === 1 ? "row" : "rows"}
            </span>
          </div>

          {loading ? (
            <EmptyState icon={<Clock size={20} />} title="Loading…" />
          ) : list.length === 0 ? (
            <EmptyState
              icon={<Inbox size={20} />}
              title="No outreach attempts yet"
              hint={
                <>
                  Run{" "}
                  <code className="font-mono text-brand-700 bg-brand-50 border border-brand-100 px-1.5 py-0.5 rounded text-2xs">
                    python scripts/demo_rehearsal.py
                  </code>{" "}
                  to seed activity.
                </>
              }
            />
          ) : (
            <ul className="divide-y divide-line">
              {list.map((o) => (
                <OutreachRow key={o.outreach_id} o={o} />
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function OutreachRow({ o }: { o: Outreach }) {
  const key = (o.outcome ?? "in_progress") as OutcomeKey;
  const meta = OUTCOME_META[key] ?? OUTCOME_META.in_progress;

  return (
    <li className="px-6 py-4 hover:bg-muted/60 transition-colors">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <Avatar name={o.patient_name ?? o.patient_id ?? "?"} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold text-ink-primary truncate">
                {o.patient_name ?? o.patient_id ?? "Unknown patient"}
              </span>
              <span className="text-ink-faint">·</span>
              <span className="text-sm text-ink-secondary truncate">
                {o.clinic_name ?? "No clinic"}
              </span>
              {o.specialty && (
                <span className="text-2xs text-ink-tertiary px-1.5 h-5 inline-flex items-center bg-muted rounded-full">
                  {o.specialty}
                </span>
              )}
            </div>
            {o.ai_summary && (
              <p className="text-[13px] text-ink-secondary mt-1.5 leading-relaxed line-clamp-2">
                {o.ai_summary}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2.5">
              {o.language_request && (
                <Meta icon={<Languages size={12} />}>
                  <span className="text-ink-secondary">{o.language_request}</span>
                  {o.language_detected && (
                    <>
                      <span className="text-ink-faint mx-1.5">·</span>
                      <span className={o.language_match ? "text-emerald-600" : "text-amber-600"}>
                        detected {o.language_detected}
                        {o.language_match === false && " (mismatch)"}
                      </span>
                    </>
                  )}
                </Meta>
              )}
              {o.candidates_count !== undefined && (
                <Meta icon={<MapPin size={12} />}>
                  <span className="font-mono text-ink-secondary">{o.candidates_count}</span>{" "}
                  candidates
                </Meta>
              )}
              {o.clinic_phone && (
                <Meta icon={<Phone size={12} />}>
                  <span className="font-mono text-ink-secondary">{o.clinic_phone}</span>
                </Meta>
              )}
              {o.booking_when && (
                <Meta icon={<Calendar size={12} />}>
                  <span className="text-emerald-600 font-medium">{o.booking_when}</span>
                </Meta>
              )}
            </div>
            {o.clinic_address && (
              <div className="text-2xs text-ink-tertiary mt-1.5 truncate flex items-center gap-1.5">
                <MapPin size={11} className="shrink-0 text-ink-muted" />
                {o.clinic_address}
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          <StatusText tone={meta.tone}>
            {key === "booked" && <CheckCircle2 size={13} />}
            {key === "failed" && <XCircle size={13} />}
            {key === "language_mismatch" && <TriangleAlert size={13} />}
            {key === "no_answer" && <PhoneOff size={13} />}
            {key === "in_progress" && <Clock size={13} />}
            {meta.label}
          </StatusText>
          <span className="text-2xs text-ink-tertiary font-mono inline-flex items-center gap-1">
            <Clock size={11} className="text-ink-muted" />
            {fmtTimeAgo(o.started_at)}
          </span>
        </div>
      </div>
    </li>
  );
}

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <div className="shrink-0 flex items-center justify-center w-10 h-10 rounded-full bg-brand-50 text-brand-700 text-xs font-semibold border border-brand-100">
      {initials || "?"}
    </div>
  );
}

function Meta({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-2xs">
      <span className="text-ink-muted">{icon}</span>
      <span className="text-ink-tertiary">{children}</span>
    </span>
  );
}

function EmptyState({
  icon,
  title,
  hint,
}: {
  icon: React.ReactNode;
  title: string;
  hint?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <span className="flex items-center justify-center w-12 h-12 rounded-full bg-muted text-ink-tertiary mb-3">
        {icon}
      </span>
      <p className="text-sm font-medium text-ink-primary">{title}</p>
      {hint && <p className="text-xs text-ink-tertiary mt-1.5 max-w-md">{hint}</p>}
    </div>
  );
}
