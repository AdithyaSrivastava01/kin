import { memo, type ReactNode } from "react";
import { Handle, Position } from "reactflow";
import {
  Building2,
  ClipboardList,
  PhoneCall,
  Scale,
  Search,
  Target,
  User,
} from "lucide-react";

export type AgentRole =
  | "patient"
  | "intake"
  | "profiler"
  | "finder"
  | "matcher"
  | "caller"
  | "clinic"
  | "candidate";

interface NodeData {
  role: AgentRole;
  title: string;
  subtitle?: string;
}

const STYLE: Record<AgentRole, { color: string; soft: string; icon: ReactNode; label: string }> = {
  patient:   { color: "#475569", soft: "#F1F5F9", icon: <User size={14} />,          label: "Patient" },
  intake:    { color: "#2563EB", soft: "#EFF6FF", icon: <Target size={14} />,        label: "Intake" },
  profiler:  { color: "#7C3AED", soft: "#F5F3FF", icon: <ClipboardList size={14} />, label: "Profiler" },
  finder:    { color: "#059669", soft: "#ECFDF5", icon: <Search size={14} />,        label: "Finder" },
  matcher:   { color: "#D97706", soft: "#FFFBEB", icon: <Scale size={14} />,         label: "Matcher" },
  caller:    { color: "#DC2626", soft: "#FEF2F2", icon: <PhoneCall size={14} />,     label: "Caller" },
  clinic:    { color: "#64748B", soft: "#F1F5F9", icon: <Building2 size={14} />,     label: "Clinic" },
  candidate: { color: "#94A3B8", soft: "#F8FAFC", icon: <Building2 size={12} />,     label: "Candidate" },
};

export const AgentNode = memo(({ data }: { data: NodeData }) => {
  const s = STYLE[data.role];
  const isCandidate = data.role === "candidate";

  return (
    <div
      className="relative flex items-stretch min-w-[180px] rounded-xl overflow-hidden bg-surface border"
      style={{
        borderColor: "#E5E7EB",
        boxShadow: `0 1px 2px rgba(16,24,40,0.04), 0 6px 18px -4px ${s.color}1F`,
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-1.5 !h-1.5 !bg-ink-faint !border-0"
        style={{ top: -3 }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-1.5 !h-1.5 !bg-ink-faint !border-0"
        style={{ bottom: -3 }}
      />

      <div className="w-[3px] shrink-0" style={{ background: s.color }} />
      <div className="flex items-center gap-2.5 px-3 py-2.5 flex-1 min-w-0">
        <span
          className="flex items-center justify-center w-8 h-8 rounded-lg shrink-0"
          style={{ background: s.soft, color: s.color }}
        >
          {s.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div
            className="text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: s.color }}
          >
            {isCandidate ? "Candidate" : s.label}
          </div>
          <div
            className={`font-medium text-ink-primary truncate ${
              isCandidate ? "text-xs" : "text-[13px]"
            }`}
          >
            {data.title}
          </div>
          {data.subtitle && (
            <div className="text-2xs text-ink-tertiary truncate">{data.subtitle}</div>
          )}
        </div>
      </div>
    </div>
  );
});
AgentNode.displayName = "AgentNode";

export const nodeTypes = { agent: AgentNode };
