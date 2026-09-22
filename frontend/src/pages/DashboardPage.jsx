import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/services/api";
import { useAnalysis } from "@/context/AnalysisContext";
import { DataTable, Expander, KeyValues, titleCase } from "@/components/common/Sections";

/** Every ECR and the latest analysis of each, as plain tables. */
export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const { selectEcr } = useAnalysis();
  const navigate = useNavigate();

  useEffect(() => {
    api.dashboardStats().then(setStats).catch(setError);
  }, []);

  const openEcr = async (ecrId) => {
    await selectEcr(ecrId);
    navigate("/analyze");
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <header className="pb-2">
        <h2 className="text-3xl font-semibold tracking-tight">ECR Dashboard</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Every Engineering Change Request and the latest analysis of each.
        </p>
      </header>

      {error && <p className="surface p-4 text-sm text-[#d03b3b]">{error.message}</p>}
      {!stats && !error && <p className="px-1 text-sm text-muted-foreground">Loading...</p>}

      {stats && (
        <>
          <Expander title="Overview">
            <KeyValues
              rows={[
                ["Total ECRs", stats.total_ecrs],
                ["Analysed ECRs", stats.analysed_ecrs],
                [
                  "Average analysis time",
                  stats.analysed_ecrs ? `${Number(stats.average_analysis_seconds).toFixed(1)}s` : "-",
                ],
                ["Test cases in the catalogue", stats.catalogue?.test_cases],
              ]}
            />
          </Expander>

          <Expander title="Recent Analyses">
            <DataTable
              rows={stats.recent_analyses}
              rowKey={(row) => row.workflow_id}
              onRowClick={(row) => openEcr(row.ecr_id)}
              empty="No analyses yet. Open ECR Analysis and analyse an ECR."
              columns={[
                { key: "ecr_id", label: "ECR ID" },
                {
                  key: "tests",
                  label: "Tests",
                  render: (row) => `${row.selected_tests}`,
                  className: "tabular-nums",
                },
                {
                  key: "time",
                  label: "Time",
                  render: (row) => `${Number(row.execution_time).toFixed(1)}s`,
                  className: "tabular-nums text-muted-foreground",
                },
              ]}
            />
          </Expander>

          <Expander title="ECRs">
            <DataTable
              rows={stats.recent_ecrs}
              rowKey={(row) => row.ecr_id}
              onRowClick={(row) => openEcr(row.ecr_id)}
              columns={[
                { key: "ecr_id", label: "ECR ID" },
                { key: "title", label: "Title" },
                { key: "business_domain", label: "Domain" },
                { key: "status", label: "Status", render: (row) => row.lifecycle_status || titleCase(row.status) },
              ]}
            />
          </Expander>
        </>
      )}
    </div>
  );
}
