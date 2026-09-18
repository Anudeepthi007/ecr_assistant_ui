import React from "react";
import { NavLink } from "react-router-dom";
import { FileText, LayoutDashboard, Search } from "lucide-react";
import { useAnalysis } from "@/context/AnalysisContext";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/analyze", label: "ECR Analysis", icon: Search },
  { to: "/report", label: "Report", icon: FileText },
];

const STATUS_TEXT = {
  idle: "Idle",
  running: "Agents running",
  awaiting_approval: "Waiting for approval",
  done: "Analysis complete",
  error: "Analysis failed",
};

export default function AppShell({ children }) {
  const { ecrId, status, health, isDemoMode } = useAnalysis();

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="flex min-h-screen">
        <aside className="hidden w-56 shrink-0 border-r border-border/70 bg-card/40 lg:flex lg:flex-col">
          <div className="px-5 py-5">
            <div className="text-sm font-semibold">ECR Assistant</div>
            <div className="text-xs text-muted-foreground">3 agents</div>
          </div>

          <nav className="flex-1 space-y-1 px-3 py-2">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
                  )
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="space-y-1.5 border-t border-border/70 px-4 py-4 text-xs text-muted-foreground">
            <div>Backend: {health ? "connected" : "offline"}</div>
            <div>Reasoning: {isDemoMode ? "rule-based (offline)" : health?.llm?.effective_provider || "-"}</div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-border/70 bg-background/90 backdrop-blur">
            <div className="flex items-center justify-between gap-4 px-5 py-3 text-sm">
              <span className="truncate font-medium">{ecrId || "No ECR selected"}</span>
              <span className="text-muted-foreground">{STATUS_TEXT[status] || STATUS_TEXT.idle}</span>
            </div>
          </header>
          <main className="flex-1 px-5 py-6">{children}</main>
        </div>
      </div>
    </div>
  );
}
