"use client";

import { Activity, Bell, ClipboardList, Search, Stethoscope } from "lucide-react";
import { Tabs } from "./ui/tabs";
import { IconButton } from "./ui/button";
import { StatusPill } from "./status-pill";
import type { ConnStatus, Tab } from "../lib/types";

interface AppBarProps {
  tab: Tab;
  onTabChange: (tab: Tab) => void;
  status: ConnStatus;
  eventCount: number;
}

export function AppBar({ tab, onTabChange, status, eventCount }: AppBarProps) {
  return (
    <header className="flex items-center justify-between gap-6 px-6 h-[72px] bg-surface border-b border-line shrink-0">
      <div className="flex items-center gap-2.5 min-w-0 w-[260px] shrink-0">
        <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-brand-600 text-white shadow-brand">
          <Stethoscope size={18} strokeWidth={2.25} />
        </div>
        <div className="min-w-0">
          <h1 className="text-[17px] font-semibold tracking-tight text-ink-primary leading-none">
            HealthSwarm
          </h1>
          <p className="text-2xs text-ink-tertiary mt-1 truncate">
            {tab === "outreach"
              ? "Outreach console"
              : `Live coordination · ${eventCount} events`}
          </p>
        </div>
      </div>

      <nav className="flex-1 flex justify-center">
        <Tabs
          value={tab}
          onChange={onTabChange}
          variant="pill"
          options={[
            { value: "outreach", label: "Outreach", icon: <ClipboardList size={15} /> },
            { value: "live",     label: "War room", icon: <Activity size={15} /> },
          ]}
        />
      </nav>

      <div className="flex items-center gap-2 w-[260px] justify-end shrink-0">
        <StatusPill status={status} />
        <IconButton aria-label="Search" className="hidden md:inline-flex">
          <Search size={16} />
        </IconButton>
        <IconButton aria-label="Notifications" className="hidden md:inline-flex">
          <Bell size={16} />
        </IconButton>
      </div>
    </header>
  );
}
