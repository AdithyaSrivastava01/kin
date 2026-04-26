import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas:    "#F5F7FA",
        surface:   "#FFFFFF",
        muted:     "#F9FAFB",
        elevated:  "#FFFFFF",

        line: {
          subtle:  "#F1F2F5",
          DEFAULT: "#E5E7EB",
          strong:  "#D1D5DB",
        },
        ink: {
          primary:   "#111827",
          secondary: "#4B5563",
          tertiary:  "#6B7280",
          muted:     "#9CA3AF",
          faint:     "#D1D5DB",
        },
        brand: {
          50:  "#EFF6FF",
          100: "#DBEAFE",
          200: "#BFDBFE",
          300: "#93C5FD",
          400: "#60A5FA",
          500: "#3B82F6",
          600: "#2563EB",
          700: "#1D4ED8",
          800: "#1E40AF",
          900: "#1E3A8A",
        },
        agent: {
          intake:   "#3B82F6",
          profiler: "#8B5CF6",
          finder:   "#10B981",
          matcher:  "#F59E0B",
          caller:   "#EF4444",
          patient:  "#64748B",
          clinic:   "#94A3B8",
        },
        status: {
          success: "#10B981",
          warning: "#F59E0B",
          danger:  "#EF4444",
          info:    "#3B82F6",
          neutral: "#6B7280",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
      },
      borderRadius: {
        xs: "4px",
        sm: "6px",
        DEFAULT: "8px",
        md: "10px",
        lg: "14px",
        xl: "18px",
        "2xl": "22px",
      },
      boxShadow: {
        "soft":   "0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 1px rgba(16, 24, 40, 0.03)",
        "card":   "0 1px 2px rgba(16, 24, 40, 0.04), 0 4px 12px -4px rgba(16, 24, 40, 0.06)",
        "elev":   "0 4px 16px -4px rgba(16, 24, 40, 0.08), 0 2px 6px -2px rgba(16, 24, 40, 0.05)",
        "pop":    "0 12px 32px -8px rgba(16, 24, 40, 0.16), 0 4px 12px -4px rgba(16, 24, 40, 0.08)",
        "brand":  "0 6px 20px -4px rgba(59, 130, 246, 0.35)",
      },
      keyframes: {
        "pulse-soft": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.45", transform: "scale(0.85)" },
        },
        "slide-down": {
          "0%": { opacity: "0", transform: "translate(-50%, -8px)" },
          "100%": { opacity: "1", transform: "translate(-50%, 0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        "pulse-soft": "pulse-soft 2s ease-in-out infinite",
        "slide-down": "slide-down 220ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        "fade-in":    "fade-in 180ms ease-out",
      },
    },
  },
  plugins: [animate],
};

export default config;
