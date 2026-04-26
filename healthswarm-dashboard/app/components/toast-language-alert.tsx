import { Languages } from "lucide-react";

export function LanguageToast({ message }: { message: string }) {
  return (
    <div className="absolute top-5 left-1/2 z-30 animate-slide-down" style={{ transform: "translateX(-50%)" }}>
      <div className="flex items-center gap-3 pl-3 pr-5 py-2.5 rounded-full bg-surface border border-line shadow-pop">
        <span className="flex items-center justify-center w-7 h-7 rounded-full bg-amber-50 text-amber-600">
          <Languages size={15} />
        </span>
        <span className="text-sm font-medium text-ink-primary">{message}</span>
      </div>
    </div>
  );
}
