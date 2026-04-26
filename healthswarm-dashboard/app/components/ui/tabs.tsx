"use client";

import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

interface TabsProps<T extends string> {
  value: T;
  onChange: (next: T) => void;
  options: { value: T; label: string; icon?: ReactNode }[];
  variant?: "pill" | "segmented";
  size?: "sm" | "md";
  className?: string;
}

export function Tabs<T extends string>({
  value,
  onChange,
  options,
  variant = "pill",
  size = "md",
  className,
}: TabsProps<T>) {
  if (variant === "segmented") {
    const sizeClass = size === "sm" ? "h-8 text-xs px-3" : "h-9 text-sm px-3.5";
    return (
      <div
        role="tablist"
        className={cn(
          "inline-flex items-center gap-0.5 p-1 bg-muted border border-line rounded-lg",
          className,
        )}
      >
        {options.map((opt) => {
          const active = opt.value === value;
          return (
            <button
              key={opt.value}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(opt.value)}
              className={cn(
                "inline-flex items-center gap-2 rounded-md font-medium transition-all duration-150",
                sizeClass,
                active
                  ? "bg-surface text-ink-primary shadow-soft"
                  : "text-ink-tertiary hover:text-ink-primary",
              )}
            >
              {opt.icon}
              <span>{opt.label}</span>
            </button>
          );
        })}
      </div>
    );
  }

  // Pill variant — modeled on the reference, no surrounding container
  const sizeClass = size === "sm" ? "h-9 text-xs px-3.5" : "h-10 text-sm px-4";
  return (
    <div role="tablist" className={cn("inline-flex items-center gap-1", className)}>
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              "inline-flex items-center gap-2 rounded-full font-medium transition-all duration-150",
              sizeClass,
              active
                ? "bg-brand-600 text-white shadow-brand"
                : "text-ink-tertiary hover:text-ink-primary hover:bg-muted",
            )}
          >
            {opt.icon}
            <span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
