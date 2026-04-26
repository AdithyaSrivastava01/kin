import { ArrowRight, Radio } from "lucide-react";
import { DEFAULT_EDGE_COLOR, KIND_COLOR } from "../lib/constants";
import type { Beacon } from "../lib/types";

export function EventFeed({ events }: { events: Beacon[] }) {
  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <span className="flex items-center justify-center w-12 h-12 rounded-full bg-muted text-ink-tertiary mb-3">
          <Radio size={20} className="animate-pulse-soft" />
        </span>
        <p className="text-sm font-medium text-ink-primary">Waiting for activity</p>
        <p className="text-2xs text-ink-tertiary mt-1">
          Live beacons will appear here as they stream.
        </p>
      </div>
    );
  }

  return (
    <ul className="space-y-2.5">
      {events.map((evt, i) => {
        const color = KIND_COLOR[evt.kind] ?? DEFAULT_EDGE_COLOR;
        return (
          <li
            key={`${evt.received_at}-${i}`}
            className="bg-surface border border-line rounded-xl overflow-hidden shadow-soft"
          >
            <div className="flex items-center gap-2 px-3 h-9 border-b border-line bg-muted/40">
              <span className="font-mono text-2xs text-ink-secondary truncate">
                {evt.src}
              </span>
              <ArrowRight size={11} className="text-ink-muted shrink-0" />
              <span className="font-mono text-2xs text-ink-secondary truncate">
                {evt.dst}
              </span>
              <span
                className="ml-auto inline-flex items-center px-2 h-5 rounded-full text-2xs font-semibold font-mono shrink-0"
                style={{
                  background: `${color}15`,
                  color,
                  boxShadow: `inset 0 0 0 1px ${color}33`,
                }}
              >
                {evt.kind}
              </span>
            </div>
            <pre className="font-mono text-2xs text-ink-secondary p-3 overflow-x-auto leading-relaxed">
              {JSON.stringify(evt.payload, null, 2)}
            </pre>
          </li>
        );
      })}
    </ul>
  );
}
