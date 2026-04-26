"use client";

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-600 hover:bg-brand-700 active:bg-brand-700 text-white shadow-brand disabled:bg-brand-200 disabled:text-white disabled:shadow-none",
  secondary:
    "bg-surface hover:bg-muted text-ink-primary border border-line hover:border-line-strong shadow-soft disabled:opacity-50",
  ghost:
    "bg-transparent hover:bg-muted text-ink-secondary hover:text-ink-primary",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-lg",
  md: "h-10 px-4 text-sm gap-2 rounded-lg",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center font-medium transition-all duration-150",
        "disabled:cursor-not-allowed",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";

export const IconButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement>
>(({ className, ...props }, ref) => (
  <button
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center w-10 h-10 rounded-full",
      "bg-surface border border-line text-ink-tertiary",
      "hover:bg-muted hover:text-ink-primary hover:border-line-strong",
      "transition-colors shadow-soft",
      className,
    )}
    {...props}
  />
));
IconButton.displayName = "IconButton";
