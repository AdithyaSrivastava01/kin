import { cn } from "../lib/cn";
import type { ConnStatus } from "../lib/types";

const STATE: Record<
  ConnStatus,
  { label: string; dot: string; ring: string; text: string }
> = {
  live: {
    label: "Live",
    dot:  "bg-emerald-500",
    ring: "bg-emerald-500/40",
    text: "text-emerald-700",
  },
  connecting: {
    label: "Connecting",
    dot:  "bg-amber-500",
    ring: "bg-amber-500/40",
    text: "text-amber-700",
  },
  disconnected: {
    label: "Offline",
    dot:  "bg-red-500",
    ring: "bg-red-500/40",
    text: "text-red-700",
  },
};

export function StatusPill({ status }: { status: ConnStatus }) {
  const s = STATE[status];
  return (
    <div className="inline-flex items-center gap-2 h-9 pl-2.5 pr-3.5 rounded-full bg-surface border border-line shadow-soft">
      <span className="relative inline-flex items-center justify-center w-2 h-2">
        <span className={cn("relative z-10 w-2 h-2 rounded-full", s.dot)} />
        {status === "live" && (
          <span className={cn("absolute inset-0 rounded-full animate-pulse-soft", s.ring)} />
        )}
      </span>
      <span className={cn("text-xs font-semibold tracking-tight", s.text)}>
        {s.label}
      </span>
    </div>
  );
}
