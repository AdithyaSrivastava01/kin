export const RELAY = process.env.NEXT_PUBLIC_RELAY_URL ?? "http://localhost:3001";

export const EDGE_TTL_MS = 4000;
export const LANG_ALERT_TTL_MS = 6000;
export const RECONNECT_DELAY_MS = 2000;
export const POLL_INTERVAL_MS = 3000;
export const FEED_CAP = 60;
export const EDGE_CAP = 30;
export const CANDIDATE_LIMIT = 5;

// Color tokens used by the graph (must match tailwind theme.agent.* hex)
export const AGENT_COLORS = {
  patient:  "#94A3B8",
  intake:   "#60A5FA",
  profiler: "#A78BFA",
  finder:   "#34D399",
  matcher:  "#FBBF24",
  caller:   "#F87171",
  clinic:   "#64748B",
} as const;

// Per-event accent — keys mirror the original agent-side beacon kinds.
export const KIND_COLOR: Record<string, string> = {
  LanguageDetected: "#FBBF24",
  CallStarted:      "#F87171",
  BookingResult:    "#F87171",
  ProfileLoaded:    "#A78BFA",
  CandidatesFound:  "#34D399",
  ClinicMatched:    "#FBBF24",
  ClinicRanked:     "#FBBF24",
};

export const DEFAULT_EDGE_COLOR = "#22D3EE";

export type OutcomeKey =
  | "booked"
  | "no_answer"
  | "language_mismatch"
  | "failed"
  | "in_progress";

export const OUTCOME_META: Record<
  OutcomeKey,
  { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }
> = {
  booked:            { label: "Booked",         tone: "success" },
  no_answer:         { label: "No answer",      tone: "neutral" },
  language_mismatch: { label: "Lang mismatch",  tone: "warning" },
  failed:            { label: "Failed",         tone: "danger"  },
  in_progress:       { label: "In progress",    tone: "info"    },
};
