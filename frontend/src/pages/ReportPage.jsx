import React from "react";
import { Download, ExternalLink, FileJson, FileText } from "lucide-react";
import api from "@/services/api";
import { useAnalysis } from "@/context/AnalysisContext";
import EmptyState from "@/components/common/EmptyState";
import { Button } from "@/components/ui/button";

export default function ReportPage() {
  const { analysis, ecrId } = useAnalysis();
  const report = analysis?.report;

  if (!report) {
    return (
      <EmptyState
        title="No report yet"
        hint={`Analyse ${ecrId || "an ECR"} to generate its intelligence report.`}
      />
    );
  }

  const confidence = report.confidence || {};
  const metrics = report.metrics || {};

  return (
    <div className="space-y-6">
      <section className="surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="eyebrow-label">ECR Intelligence Report</div>
            <h2 className="mt-1 text-xl font-semibold tracking-tight">
              {report.ecr_id} - {report.title}
            </h2>
            <div className="mt-1 text-xs text-muted-foreground">
              Generated {new Date(report.generated_at).toLocaleString()} - workflow{" "}
              <span className="font-mono">{report.workflow_id}</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild size="sm" variant="outline" className="gap-2">
              <a href={api.reportUrl(report.ecr_id, "html")} target="_blank" rel="noreferrer">
                <ExternalLink className="h-3.5 w-3.5" /> HTML
              </a>
            </Button>
            <Button asChild size="sm" variant="outline" className="gap-2">
              <a href={api.reportUrl(report.ecr_id, "markdown")} target="_blank" rel="noreferrer">
                <FileText className="h-3.5 w-3.5" /> Markdown
              </a>
            </Button>
            <Button asChild size="sm" variant="outline" className="gap-2">
              <a href={api.reportUrl(report.ecr_id, "json")} target="_blank" rel="noreferrer">
                <FileJson className="h-3.5 w-3.5" /> JSON
              </a>
            </Button>
            <Button
              size="sm"
              className="gap-2"
              onClick={() => window.print()}
              title="Print or save as PDF"
            >
              <Download className="h-3.5 w-3.5" /> PDF
            </Button>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <Metric
            label="Confidence"
            value={`${Math.round((confidence.overall || 0) * 100)}%`}
            hint={confidence.band}
          />
          <Metric
            label="Recommended tests"
            value={`${metrics.selected_tests || 0} / ${metrics.total_tests || 0}`}
            hint={`${Number(metrics.reduction_percentage || 0).toFixed(0)}% reduction`}
          />
          <Metric
            label="Correlated artifacts"
            // reports saved before the artefact -> artifact rename
            value={metrics.correlated_artifacts ?? metrics.correlated_artefacts ?? 0}
            hint={`${metrics.correlated_links || 0} typed links`}
          />
        </div>

        {confidence.penalties?.length > 0 && (
          <div className="mt-4 rounded-lg border border-[#fab219]/30 bg-[#fab219]/5 p-3 text-xs text-[#fab219]">
            Confidence reduced: {confidence.penalties.join("; ")}
          </div>
        )}
      </section>

      <section className="space-y-4">
        {report.sections
          ?.filter((section) => section.key !== "execution_trace")
          .map((section) => (
            <div key={section.key} className="surface p-5">
              <h3 className="text-sm font-semibold">{section.title}</h3>
              {/* Mitigations' body is the same list as its data (kept for text exports); show it once. */}
              {section.body && !(section.key === "mitigations" && section.data?.mitigations?.length) && (
                <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                  {section.body}
                </p>
              )}
              <SectionData section={section} />
            </div>
          ))}
      </section>
    </div>
  );
}

function Metric({ label, value, hint, color }) {
  return (
    <div className="rounded-lg border border-border/70 bg-background/40 p-3">
      <div className="eyebrow-label">{label}</div>
      <div className="mt-1 text-xl font-semibold" style={color ? { color } : undefined}>
        {value}
      </div>
      {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

const MATCH_LABELS = {
  TRACEABILITY: "Linked",
  COMPONENT_LINK: "Via component",
  SEMANTIC: "Similar text",
  KEYWORD: "Keyword",
};

// A requirement found through several channels carries a combined type ("TRACEABILITY+SEMANTIC").
function matchLabel(matchType) {
  return (matchType || "SEMANTIC")
    .split("+")
    .map((part) => MATCH_LABELS[part] || part)
    .join(" + ");
}

function SectionData({ section }) {
  const { key, data } = section;
  if (key === "affected_requirements" && data.requirements?.length) {
    return (
      <ul className="mt-3 space-y-1.5 text-xs">
        {data.requirements.map((requirement) => (
          <li key={requirement.requirement_id} className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono text-primary">{requirement.requirement_id}</span>
            <span className="text-foreground">{requirement.title}</span>
            <span className="rounded border border-border/70 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
              {matchLabel(requirement.match_type)}
            </span>
            <span className="text-muted-foreground">
              {Math.round(requirement.relevance)}% - {requirement.reason}
            </span>
          </li>
        ))}
      </ul>
    );
  }
  if (key === "recommended_tests" && data.selected?.length) {
    return (
      <div className="scroll-thin mt-3 max-h-72 overflow-y-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wide text-muted-foreground">
              <th className="pb-1.5 font-medium">Test</th>
              <th className="pb-1.5 font-medium">Priority</th>
              <th className="pb-1.5 font-medium">Relevance</th>
              <th className="pb-1.5 font-medium">Why</th>
            </tr>
          </thead>
          <tbody>
            {data.selected.slice(0, 40).map((test) => (
              <tr key={test.test_case_id} className="border-t border-border/50 align-top">
                <td className="py-1.5 font-mono">{test.test_case_id}</td>
                <td className="py-1.5">{test.priority}</td>
                <td className="py-1.5 tabular-nums">{Math.round(test.relevance_score)}%</td>
                <td className="py-1.5 text-muted-foreground">{test.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (key === "historical_defects" && data.defects?.length) {
    return (
      <ul className="mt-3 space-y-2 text-xs">
        {data.defects.map((defect) => (
          <li key={defect.defect_id}>
            <span className="font-mono text-primary">{defect.defect_id}</span>{" "}
            <span className="text-foreground">{defect.title}</span>
            {defect.chance_of_recurrence && (
              <span className="text-muted-foreground"> - can it happen again: {defect.chance_of_recurrence}</span>
            )}
            {defect.what_to_check && <div className="mt-0.5 text-muted-foreground">{defect.what_to_check}</div>}
          </li>
        ))}
      </ul>
    );
  }
  if (key === "mitigations" && data.mitigations?.length) {
    return (
      <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
        {data.mitigations.map((item, index) => (
          <li key={index}>- {item}</li>
        ))}
      </ul>
    );
  }
  if (key === "team_signals") {
    return (
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {["decisions", "risks"].map((bucket) =>
          data[bucket]?.length ? (
            <div key={bucket}>
              <div className="eyebrow-label">{bucket}</div>
              <ul className="mt-1.5 space-y-1.5 text-xs text-muted-foreground">
                {data[bucket].slice(0, 4).map((item) => (
                  <li key={item.comment_id}>
                    <span className="text-foreground">{item.author}</span>: {item.text}
                  </li>
                ))}
              </ul>
            </div>
          ) : null
        )}
      </div>
    );
  }
  return null;
}
