"use client";

import { forwardRef, type InputHTMLAttributes, type SelectHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

const fieldClass = cn(
  "w-full bg-surface border border-line rounded-lg px-3.5 h-10",
  "text-sm text-ink-primary placeholder:text-ink-muted",
  "transition-colors hover:border-line-strong",
  "focus:border-brand-500 focus:outline-none",
  "disabled:opacity-50 disabled:cursor-not-allowed",
);

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(fieldClass, className)} {...props} />
  ),
);
Input.displayName = "Input";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        fieldClass,
        "appearance-none bg-no-repeat bg-right pr-10 cursor-pointer",
        className,
      )}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239CA3AF' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E\")",
        backgroundPosition: "right 14px center",
      }}
      {...props}
    >
      {children}
    </select>
  ),
);
Select.displayName = "Select";
