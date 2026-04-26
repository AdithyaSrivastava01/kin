import type { ReactNode } from "react";
import { cn } from "../lib/cn";

type Tone = "neutral" | "success" | "warning" | "info" | "danger";

const ICON_TONE: Record<Tone, string> = {
  neutral: "bg-muted text-ink-tertiary",
  success: "bg-emerald-50 text-emerald-600",
  warning: "bg-amber-50  text-amber-600",
  info:    "bg-sky-50    text-sky-600",
  danger:  "bg-red-50    text-red-600",
};

interface StatCardProps {
  label: string;
  value: number | string;
  tone?: Tone;
  icon?: ReactNode;
  hint?: string;
}

export function StatCard({ label, value, tone = "neutral", icon, hint }: StatCardProps) {
  return (
    <div className="relative bg-surface border border-line rounded-2xl shadow-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-ink-tertiary truncate">{label}</p>
          <p className="font-mono text-[28px] font-semibold tabular-nums text-ink-primary leading-none mt-3">
            {value}
          </p>
          {hint && (
            <p className="text-2xs text-ink-muted mt-2 truncate">{hint}</p>
          )}
        </div>
        {icon && (
          <span
            className={cn(
              "shrink-0 flex items-center justify-center w-9 h-9 rounded-xl",
              ICON_TONE[tone],
            )}
          >
            {icon}
          </span>
        )}
      </div>
    </div>
  );
}
