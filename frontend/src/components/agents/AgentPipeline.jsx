import React, { useEffect, useMemo, useState } from "react";
import { Check, Loader2, Minus, X } from "lucide-react";

/**
 * The three agents and the steps each one runs. Keys match the backend step
 * keys, so live events mark the right rows. There are no other agents.
 */
export const AGENTS = [
  {
    key: "retrieval_agent",
    name: "Retrieval Agent",
    steps: [
      ["understand_ecr", "Understand the ECR"],
      ["gather_evidence", "Gather evidence"],
    ],
  },
  {
    key: "correlation_agent",
    name: "Correlation Agent",
    steps: [
      ["assess_impact", "Assess impact"],
      ["select_tests", "Select regression tests"],
    ],
  },
  {
    key: "summarization_agent",
    name: "Summarization Agent",
    steps: [["summarize", "Summarize and report"]],
  },
];

/** Evidence the Gather step may collect; the planner can skip the optional ones. */
export const INVESTIGATION_LABELS = {
  requirements: "Impacted requirements",
  historical_defects: "Similar historical defects",
  dependencies: "Component dependencies",
  collaboration_retrieval: "Review comments and evidence",
};

export const AGENT_NAMES = AGENTS.map((agent) => agent.name);

export const STEP_LABELS = Object.fromEntries(AGENTS.flatMap((agent) => agent.steps));

export const STEP_OWNER = Object.fromEntries(
  AGENTS.flatMap((agent) => agent.steps.map(([key]) => [key, agent.name]))
);

function useStatuses(events) {
  return useMemo(() => {
    const statuses = {};
    events.forEach((event) => {
      if (!event.agent_key) return;
      statuses[event.agent_key] = {
        status: String(event.status || "").toLowerCase(),
        duration: event.duration ?? statuses[event.agent_key]?.duration,
      };
    });
    return statuses;
  }, [events]);
}

/** Seconds since ``startedAt``, ticking while the run is in progress. */
function useElapsed(startedAt) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAt) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(timer);
  }, [startedAt]);
  return startedAt ? Math.max(0, (now - startedAt) / 1000) : null;
}

const LABEL = { running: "Running", completed: "Done", failed: "Failed", skipped: "Not needed" };

function Mark({ status }) {
  if (status === "completed") return <Check className="h-3.5 w-3.5 text-[#0ca30c]" />;
  if (status === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-[#3987e5]" />;
  if (status === "failed") return <X className="h-3.5 w-3.5 text-[#d03b3b]" />;
  return <Minus className="h-3.5 w-3.5 text-muted-foreground/60" />;
}

/** Live progress as a plain checklist: three agents, their steps, a status each. */
export default function AgentPipeline({ events = [], skipped = [], startedAt = null }) {
  const statuses = useStatuses(events);
  const awaitingApproval = statuses.human_approval?.status === "awaiting_approval";
  const elapsed = useElapsed(startedAt);

  return (
    <div className="space-y-4 text-sm">
      {elapsed != null && (
        <p className="text-xs tabular-nums text-muted-foreground">Running for {elapsed.toFixed(1)}s</p>
      )}
      {AGENTS.map((agent, index) => {
        const agentStatus = statuses[agent.key]?.status || "waiting";
        return (
          <div key={agent.key}>
            <div className="flex items-center justify-between font-semibold">
              <span>
                {index + 1}. {agent.name}
              </span>
              <span className="text-xs font-normal text-muted-foreground">
                {LABEL[agentStatus] || "Waiting"}
              </span>
            </div>
            <ul className="mt-1.5 space-y-1 pl-4">
              {agent.steps.map(([key, label]) => {
                const status = skipped.includes(key) ? "skipped" : statuses[key]?.status || "waiting";
                return (
                  <li key={key} className="flex items-center gap-2">
                    <Mark status={status} />
                    <span className={status === "waiting" || status === "skipped" ? "text-muted-foreground" : ""}>
                      {label}
                    </span>
                    <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                      {status === "skipped"
                        ? "Not needed"
                        : statuses[key]?.duration != null
                          ? `${Number(statuses[key].duration).toFixed(1)}s`
                          : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      {awaitingApproval && (
        <p className="text-[#fab219]">
          Approval requested - waiting for a human decision before the report is published.
        </p>
      )}
    </div>
  );
}
