import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type Tone = "success" | "warning" | "danger" | "info" | "neutral" | "brand";

const TONE: Record<Tone, string> = {
  success: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200",
  warning: "bg-amber-50  text-amber-700  ring-1 ring-inset ring-amber-200",
  danger:  "bg-red-50    text-red-700    ring-1 ring-inset ring-red-200",
  info:    "bg-sky-50    text-sky-700    ring-1 ring-inset ring-sky-200",
  neutral: "bg-muted     text-ink-secondary ring-1 ring-inset ring-line",
  brand:   "bg-brand-50  text-brand-700  ring-1 ring-inset ring-brand-200",
};

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ tone = "neutral", className, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 h-5 rounded-full text-2xs font-semibold",
        TONE[tone],
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}

const DOT_TONE: Record<Tone, string> = {
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  danger:  "bg-red-500",
  info:    "bg-sky-500",
  neutral: "bg-ink-muted",
  brand:   "bg-brand-500",
};

interface StatusTextProps extends HTMLAttributes<HTMLSpanElement> {
  tone: Tone;
}

export function StatusText({ tone, className, children, ...props }: StatusTextProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-sm font-medium",
        tone === "success" && "text-emerald-600",
        tone === "warning" && "text-amber-600",
        tone === "danger"  && "text-red-600",
        tone === "info"    && "text-sky-600",
        tone === "neutral" && "text-ink-tertiary",
        tone === "brand"   && "text-brand-600",
        className,
      )}
      {...props}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full", DOT_TONE[tone])} />
      {children}
    </span>
  );
}
