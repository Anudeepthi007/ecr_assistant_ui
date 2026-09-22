import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, Copy, Play, Search, Send, ShieldCheck, XCircle } from "lucide-react";
import { toast } from "sonner";
import api from "@/services/api";
import { useAnalysis } from "@/context/AnalysisContext";
import AgentPipeline, { AGENT_NAMES, STEP_LABELS } from "@/components/agents/AgentPipeline";
import { DataTable, Expander, KeyValues, titleCase } from "@/components/common/Sections";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { chanceColor, priorityColor } from "@/theme/viz";

// Long lists show this many rows; the rest sit behind a "Show all" button.
const PREVIEW_ROWS = 5;

/** A table that shows the first few rows and hides the rest behind "Show all". */
function PreviewTable({ rows = [], noun = "items", limit = PREVIEW_ROWS, ...tableProps }) {
  const [showAll, setShowAll] = useState(false);
  const hidden = rows.length - limit;
  return (
    <div className="space-y-3">
      <DataTable {...tableProps} rows={showAll ? rows : rows.slice(0, limit)} />
      {hidden > 0 && (
        <Button size="sm" variant="outline" onClick={() => setShowAll((value) => !value)}>
          {showAll ? "Show fewer" : `Show all ${rows.length} ${noun} (${hidden} more)`}
        </Button>
      )}
    </div>
  );
}

/**
 * ECR analysis as a readable answer: a lookup box, then a few collapsible
 * sections of plain facts - no charts, no scores.
 */
export default function AnalyzePage() {
  const { ecrId, setEcrId, analyze, analysis, status, events, selectEcr, approve, startedAt } = useAnalysis();
  const [ecrs, setEcrs] = useState([]);
  const [hitl, setHitl] = useState(false);
  const loadedFor = useRef(null);

  useEffect(() => {
    api.listEcrs().then(setEcrs).catch(() => setEcrs([]));
  }, []);

  // Show an existing analysis as soon as a known ECR id is entered.
  useEffect(() => {
    if (status !== "idle" || !ecrs.some((item) => item.ecr_id === ecrId)) return;
    if (loadedFor.current === ecrId) return;
    loadedFor.current = ecrId;
    selectEcr(ecrId);
  }, [ecrId, ecrs, status, selectEcr]);

  const running = status === "running" || status === "awaiting_approval";
  const current = analysis && analysis.ecr_id === ecrId ? analysis : null;
  const record = ecrs.find((item) => item.ecr_id === ecrId) || current?.report?.ecr_overview;

  const impact = current?.impact_analysis;
  const selection = current?.test_selection;
  const tests = current?.test_prioritization?.prioritized_tests || selection?.selected_tests || [];
  const requirements = current?.requirement_analysis?.matched_requirements || [];
  const review = current?.correlation_review;
  const findings = [...(review?.conflicts || []), ...(review?.gaps || [])];

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <header className="pb-2">
        <h2 className="text-3xl font-semibold tracking-tight">AI ECR Analysis Assistant</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Trace an Engineering Change Request to its requirements, tests and past defects.
        </p>
      </header>

      {/* Lookup */}
      <div className="surface flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label htmlFor="ecr-id" className="mb-1.5 block text-sm font-medium">
            ECR ID
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="ecr-id"
              value={ecrId}
              onChange={(event) => setEcrId(event.target.value.toUpperCase())}
              onKeyDown={(event) => event.key === "Enter" && !running && analyze(ecrId, { human_in_the_loop: hitl })}
              placeholder="ECR-2026-001"
              className="h-10 pl-9"
              list="ecr-options"
            />
            <datalist id="ecr-options">
              {ecrs.map((item) => (
                <option key={item.ecr_id} value={item.ecr_id}>
                  {item.title}
                </option>
              ))}
            </datalist>
          </div>
        </div>
        <label className="flex h-10 cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={hitl} onChange={(event) => setHitl(event.target.checked)} />
          Require approval
        </label>
        <Button
          onClick={() => analyze(ecrId, { human_in_the_loop: hitl })}
          disabled={running || !ecrId}
          className="h-10 gap-2 px-6"
        >
          <Play className="h-4 w-4" />
          {running ? "Analyzing..." : "Analyze"}
        </Button>
      </div>
      <p className="px-1 text-xs text-muted-foreground">
        Data source: CSV files{ecrs.length > 0 && ` - ${ecrs.length} ECRs available`}
      </p>

      {!record && !running && (
        <p className="px-1 text-sm text-muted-foreground">Enter an ECR ID and press Analyze.</p>
      )}

      {running && (
        <Expander title="Agents running">
          <AgentPipeline events={events} skipped={current?.skipped_steps || []} startedAt={startedAt} />
          {status === "awaiting_approval" && <ApprovalPanel selection={selection} onDecide={approve} />}
        </Expander>
      )}

      {current && impact && (
        <>
          <Expander title="Execution Trace">
            <ExecutionTrace trace={current.execution_trace || []} duration={current.duration} />
          </Expander>

          <Expander title="ECR Summary">
            <SummaryCard ecr={record} analysis={current} />
          </Expander>
        </>
      )}

      {record && (
        <Expander title="ECR Details" defaultOpen={!current}>
          <KeyValues rows={ecrDetailRows(record)} />
        </Expander>
      )}

      {current && impact && (
        <>
          <Expander title="Requirements">
            <PreviewTable
              noun="requirements"
              rows={requirements}
              rowKey={(row) => row.requirement_id}
              empty="No requirement could be traced to this ECR."
              columns={[
                { key: "requirement_id", label: "Requirement ID" },
                { key: "title", label: "Title" },
                { key: "reason", label: "Why it is linked", className: "text-muted-foreground" },
              ]}
            />
          </Expander>

          <Expander title="Recommended Test Cases">
            <TestsSection tests={tests} selection={selection} />
          </Expander>

          <Expander title="Impacted Components">
            <div className="space-y-4 text-sm">
              <ComponentList title="Changed directly" items={impact.directly_impacted_components} />
              <ComponentList title="Reached through dependencies" items={impact.indirectly_impacted_components} />
              {impact.mitigations?.length > 0 && (
                <div>
                  <div className="font-semibold">Recommended actions</div>
                  <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-foreground/90">
                    {impact.mitigations.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          </Expander>

          <Expander title="Defect Analysis">
            <DefectSection
              insights={current.defect_insights}
              summary={current.defect_summary}
              similar={current.defect_analysis?.similar_defects}
            />
          </Expander>

          {findings.length > 0 && (
            <Expander title="Conflicts and Gaps">
              <ul className="list-disc space-y-1 pl-5 text-sm text-foreground/90">
                {findings.map((item) => (
                  <li key={item.text}>{item.text}</li>
                ))}
              </ul>
            </Expander>
          )}

          <Expander title="Review Comments and Evidence" defaultOpen={false}>
            <div className="space-y-4">
              <DataTable
                rows={current.comments}
                rowKey={(row) => row.comment_id}
                empty="No review comments are attached to this ECR."
                columns={[
                  { key: "author", label: "Author" },
                  { key: "body", label: "Comment", className: "text-muted-foreground" },
                ]}
              />
              <DataTable
                rows={current.evidence}
                rowKey={(row) => row.evidence_id}
                empty="No evidence is attached to this ECR."
                columns={[
                  { key: "title", label: "Evidence" },
                  { key: "outcome", label: "Outcome", render: (row) => titleCase(row.outcome) },
                ]}
              />
            </div>
          </Expander>

          <Expander title="Ask a Question" defaultOpen={false}>
            <FollowUp ecrId={ecrId} />
          </Expander>
        </>
      )}
    </div>
  );
}

const joined = (values) => (values || []).join(", ");

/**
 * ECR fields in display order. Records imported from the change-tracking export
 * (ECR-1, ECR-2 ...) carry extra columns; a row only appears when it has a value.
 */
function ecrDetailRows(record) {
  const exported = Boolean(record.lifecycle_status || record.severity || record.affected_test_cases?.length);
  const rows = [
    ["Type", exported ? record.record_type : ""],
    ["Summary", record.title],
    ["Status", record.lifecycle_status],
    ["Severity", record.severity],
    ["Priority", exported ? "" : titleCase(record.priority)],
    ["Assigned Testers", joined(record.assigned_testers)],
    ["Actual Modified Software Objects", joined(record.actual_modified_objects)],
    ["Planned Modified Software Objects", joined(record.planned_modified_objects)],
    ["Build Resolved In", record.build_resolved_in],
    ["Test Estimate (Archived)", record.test_estimate_archived],
    ["Estimate", record.estimate],
    ["Test Estimate", record.test_estimate],
    ["Creation Date", record.creation_date],
    ["Modified Date", record.modified_date],
    ["Software Integration Test Assigned Testers", joined(record.sit_assigned_testers)],
    ["Test Actual Time", record.test_actual_time],
    ["Description", record.description],
    ["Affected Test Cases", joined(record.affected_test_cases)],
    ["Steps to Reproduce", record.steps_to_reproduce?.trim() || "No steps to reproduce provided for this ECR."],
    ["Observed Behavior", record.observed_behavior],
    ["Expected Behavior", record.expected_behavior],
    ["Attachments", joined(record.attachments)],
    ["Business Domain", record.business_domain],
    ["Requested By", exported ? "" : record.requested_by],
    ["Changed Files", joined(record.changed_files)],
    ["Linked Requirements", joined(record.linked_requirements)],
  ];
  return rows.filter(([, value]) => value);
}

/** What ran, in order, and how long it took. */
function ExecutionTrace({ trace, duration }) {
  const steps = trace.filter((row) => !String(row.agent_key || "").endsWith("_agent"));
  const agents = AGENT_NAMES.filter((name) =>
    trace.some((entry) => entry.agent === name && entry.status === "completed")
  );
  return (
    <div className="space-y-3 text-sm">
      <DataTable
        minWidth={480}
        rows={steps}
        empty="No steps were recorded for this run."
        columns={[
          { key: "step", label: "Step", render: (row) => STEP_LABELS[row.agent_key] || row.action },
          { key: "agent", label: "Agent", className: "text-muted-foreground" },
          { key: "status", label: "Status", render: (row) => titleCase(row.status) },
          {
            key: "duration",
            label: "Time",
            render: (row) => `${Number(row.duration || 0).toFixed(1)}s`,
            className: "tabular-nums text-muted-foreground",
          },
        ]}
      />
      <p className="text-muted-foreground">
        {agents.length ? `${agents.join(", ")} completed` : "No agent completed"}
        {duration != null && ` in ${Number(duration).toFixed(1)}s`}.
      </p>
    </div>
  );
}

function SummaryCard({ ecr, analysis }) {
  const [copied, setCopied] = useState(false);
  const impact = analysis.impact_analysis;
  const selection = analysis.test_selection || {};
  const distribution = selection.priority_distribution || {};
  const concerns = analysis.collaboration_analysis?.open_concerns || [];
  const direct = (impact.directly_impacted_components || []).map((c) => c.name);
  const indirect = (impact.indirectly_impacted_components || []).map((c) => c.name);
  const selected = selection.selected_tests?.length || 0;
  const defectInfo = analysis.defect_insights;

  const lines = [
    ["ECR", `${ecr?.ecr_id || analysis.ecr_id} - ${ecr?.title || ""}`],
    ["Change Type", titleCase(analysis.ecr_analysis?.change_type)],
    ["AI Summary", analysis.answer],
    [
      "Impacted",
      `${direct.join(", ") || "None identified"}` +
        (indirect.length ? ` (also reaches ${indirect.join(", ")})` : ""),
    ],
    [
      "Recommended Tests",
      `${selected} of ${selection.total_available || 0} (${Math.round(selection.reduction_percentage || 0)}% fewer), ` +
        `${distribution.P0 || 0} P0 and ${distribution.P1 || 0} P1`,
    ],
    [
      "Past Defects",
      defectInfo?.total
        ? `${defectInfo.total} related, ${defectInfo.high} could happen again`
        : "None related",
    ],
  ];

  const markdown = useMemo(() => {
    const out = lines.map(([label, value]) => `**${label}:** ${value || "-"}`);
    if (concerns.length) {
      out.push("", "**Open Concerns:**", ...concerns.map((c) => `- ${c.author}: ${c.text}`));
    }
    if (impact.mitigations?.length) {
      out.push("", "**Recommended Actions:**", ...impact.mitigations.map((m, i) => `${i + 1}. ${m}`));
    }
    return out.join("\n");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis, ecr]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      toast.success("Copied - paste it straight into Teams");
      setTimeout(() => setCopied(false), 1800);
    } catch {
      toast.error("Clipboard unavailable in this browser");
    }
  };

  return (
    <div className="space-y-3 text-sm leading-relaxed">
      {lines.map(([label, value]) => (
        <p key={label}>
          <span className="font-semibold">{label}:</span> {value || "-"}
        </p>
      ))}
      {concerns.length > 0 && (
        <div>
          <div className="font-semibold">Open Concerns:</div>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {concerns.map((concern) => (
              <li key={concern.comment_id}>
                {concern.author}: {concern.text}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex justify-end pt-1">
        <Button size="sm" variant="outline" className="gap-2" onClick={copy}>
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          Copy for Teams
        </Button>
      </div>
    </div>
  );
}

function TestsSection({ tests, selection }) {
  return (
    <div className="space-y-3">
      {selection && (
        <p className="text-sm">
          {selection.selected_tests?.length || 0} of {selection.total_available} tests recommended
          {selection.reduction_percentage
            ? ` - ${Math.round(selection.reduction_percentage)}% fewer to run.`
            : "."}
        </p>
      )}
      <PreviewTable
        noun="tests"
        minWidth={640}
        rows={tests}
        rowKey={(row) => row.test_case_id}
        empty="No test cases were selected."
        columns={[
          { key: "test_case_id", label: "Test Case ID" },
          { key: "title", label: "Title" },
          {
            key: "priority",
            label: "Priority",
            render: (row) => (
              <span className="font-medium" style={{ color: priorityColor(row.priority) }}>
                {row.priority}
              </span>
            ),
          },
          { key: "reason", label: "Why", className: "text-muted-foreground" },
        ]}
      />
    </div>
  );
}

function DefectSection({ insights, summary, similar = [] }) {
  const rows = insights?.defects || [];
  const history = insights?.component_history || [];
  const openNow = insights?.open_defects || [];
  // Analyses saved before defect analysis existed only carry the similar-defect list.
  const legacy = insights ? [] : similar || [];

  if (!summary && !rows.length && !history.length && !openNow.length && !legacy.length) {
    return <p className="text-sm text-muted-foreground">No defects are recorded for this ECR or the components it touches.</p>;
  }

  return (
    <div className="space-y-5">
      {summary && <p className="text-sm leading-relaxed">{summary}</p>}

      {rows.length > 0 && (
        <PreviewTable
          noun="defects"
          minWidth={680}
          rows={rows}
          rowKey={(row) => row.defect_id}
          columns={[
            { key: "defect_id", label: "Defect ID" },
            { key: "title", label: "What went wrong" },
            {
              key: "chance_of_recurrence",
              label: "Can it happen again?",
              render: (row) => (
                <span className="font-medium" style={{ color: chanceColor(row.chance_of_recurrence) }}>
                  {row.chance_of_recurrence}
                </span>
              ),
            },
            { key: "what_to_check", label: "What to check", className: "text-muted-foreground" },
          ]}
        />
      )}

      {legacy.length > 0 && (
        <DataTable
          minWidth={520}
          rows={legacy}
          rowKey={(row) => row.defect_id}
          columns={[
            { key: "defect_id", label: "Defect ID" },
            { key: "title", label: "What went wrong" },
            { key: "root_cause", label: "Cause", className: "text-muted-foreground" },
          ]}
        />
      )}

      {openNow.length > 0 && (
        <Block title="Still open in the affected area">
          <DataTable
            minWidth={520}
            rows={openNow}
            rowKey={(row) => row.defect_id}
            columns={[
              { key: "defect_id", label: "Defect ID" },
              { key: "title", label: "What is wrong" },
              { key: "component_name", label: "Component" },
              { key: "status", label: "Status", render: (row) => titleCase(row.status) },
            ]}
          />
        </Block>
      )}

      {/* Component history is only needed when no past defect matched the change itself. */}
      {!rows.length && history.length > 0 && (
        <Block title="Defect history of the affected components">
          <DataTable
            minWidth={520}
            rows={history}
            rowKey={(row) => row.component}
            columns={[
              { key: "component_name", label: "Component" },
              { key: "total", label: "Past defects", className: "tabular-nums" },
              { key: "open", label: "Still open", className: "tabular-nums" },
              { key: "top_cause", label: "Usual cause", className: "text-muted-foreground" },
            ]}
          />
        </Block>
      )}
    </div>
  );
}

function ComponentList({ title, items = [] }) {
  return (
    <div>
      <div className="font-semibold">{title}</div>
      {items.length ? (
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-foreground/90">
          {items.map((component) => (
            <li key={component.component_id}>
              {component.name}
              {component.reasons?.length ? ` - ${component.reasons.join("; ")}` : ""}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-muted-foreground">None identified.</p>
      )}
    </div>
  );
}

function FollowUp({ ecrId }) {
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [history, setHistory] = useState([]);

  const ask = async (event) => {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    setAsking(true);
    setQuestion("");
    try {
      const response = await api.ask(ecrId, text);
      setHistory((prev) => [...prev, { question: text, answer: response.answer, citations: response.citations }]);
    } catch (error) {
      toast.error(error.message);
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="space-y-3 text-sm">
      {history.map((entry, index) => (
        <div key={index}>
          <p className="font-semibold">Q: {entry.question}</p>
          <p className="mt-1 whitespace-pre-line">{entry.answer}</p>
          {entry.citations?.length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">Sources: {entry.citations.join(", ")}</p>
          )}
        </div>
      ))}
      <form onSubmit={ask} className="flex gap-2">
        <Input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={`Ask about ${ecrId} - e.g. why was the top test selected?`}
          disabled={asking}
        />
        <Button type="submit" disabled={asking || !question.trim()} className="gap-2">
          <Send className="h-4 w-4" />
          {asking ? "Thinking..." : "Ask"}
        </Button>
      </form>
    </div>
  );
}

function ApprovalPanel({ selection, onDecide }) {
  const [busy, setBusy] = useState(false);
  const decide = async (approved) => {
    setBusy(true);
    try {
      await onDecide({ approved, decided_by: "qa.lead@enterprise.com", comment: "" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4 text-sm">
      <p>
        {selection?.selected_tests?.length ?? "The"} recommended tests are ready. Approve to publish the report, or
        reject to withhold the recommendation.
      </p>
      <div className="flex gap-2">
        <Button size="sm" disabled={busy} onClick={() => decide(true)} className="gap-2">
          <ShieldCheck className="h-4 w-4" /> Approve
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => decide(false)} className="gap-2">
          <XCircle className="h-4 w-4" /> Reject
        </Button>
      </div>
    </div>
  );
}

function Block({ title, children }) {
  return (
    <div>
      <div className="mb-1 font-semibold">{title}</div>
      <div className="text-foreground/90">{children}</div>
    </div>
  );
}
