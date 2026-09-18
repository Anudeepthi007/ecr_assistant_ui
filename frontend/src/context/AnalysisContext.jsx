import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import api from "@/services/api";

/**
 * Holds the ECR currently under analysis, the live agent event stream and the
 * finished analysis payload, so every page reads one source of truth.
 */
const AnalysisContext = createContext(null);

const STORAGE_KEY = "ecr.lastEcrId";

export function AnalysisProvider({ children }) {
  const [ecrId, setEcrId] = useState(() => localStorage.getItem(STORAGE_KEY) || "");
  const [status, setStatus] = useState("idle"); // idle | running | awaiting_approval | done | error
  const [workflowId, setWorkflowId] = useState(null);
  const [events, setEvents] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [error, setError] = useState(null);
  const [health, setHealth] = useState(null);
  const [startedAt, setStartedAt] = useState(null); // when the current run began (ms)
  const unsubscribeRef = useRef(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    return () => unsubscribeRef.current?.();
  }, []);

  useEffect(() => {
    if (ecrId) localStorage.setItem(STORAGE_KEY, ecrId);
  }, [ecrId]);

  const loadAnalysis = useCallback(async (id) => {
    try {
      const payload = await api.analysis(id);
      setAnalysis(payload);
      return payload;
    } catch (err) {
      if (err.status !== 404) setError(err);
      return null;
    }
  }, []);

  const analyze = useCallback(
    async (id, options = {}) => {
      const target = (id || "").trim().toUpperCase();
      if (!target) {
        toast.error("Enter an ECR number first");
        return;
      }
      unsubscribeRef.current?.();
      setEcrId(target);
      setEvents([]);
      setAnalysis(null);
      setError(null);
      setStatus("running");
      setStartedAt(Date.now());
      try {
        const started = await api.analyze(target, options);
        setWorkflowId(started.workflow_id);
        unsubscribeRef.current = api.streamWorkflow(started.workflow_id, {
          onAgent: (event) => setEvents((prev) => [...prev, event]),
          onDone: async (done) => {
            await loadAnalysis(target);
            setStatus(done.status === "FAILED" ? "error" : "done");
            if (done.status === "FAILED") {
              toast.error(`Analysis of ${target} failed`);
            } else {
              toast.success(`${target} analysed in ${Number(done.duration).toFixed(1)}s`);
            }
          },
          onError: async () => {
            // The stream can drop behind a proxy; the result is still on the API.
            const payload = await loadAnalysis(target);
            setStatus(payload ? "done" : "error");
          },
        });
      } catch (err) {
        setError(err);
        setStatus("error");
        toast.error(err.message);
      }
    },
    [loadAnalysis]
  );

  const selectEcr = useCallback(
    async (id) => {
      const target = (id || "").trim().toUpperCase();
      setEcrId(target);
      setEvents([]);
      setStatus("idle");
      const payload = await loadAnalysis(target);
      if (payload) setStatus("done");
      else setAnalysis(null);
    },
    [loadAnalysis]
  );

  const approve = useCallback(
    async (decision) => {
      if (!ecrId) return;
      await api.approve(ecrId, decision);
      toast.success(decision.approved ? "Test suite approved" : "Recommendation rejected");
    },
    [ecrId]
  );

  // The approval checkpoint announces itself on the event stream.
  useEffect(() => {
    const last = events[events.length - 1];
    if (last?.status === "AWAITING_APPROVAL") setStatus("awaiting_approval");
    else if (last && status === "awaiting_approval" && last.agent_key === "human_approval") {
      setStatus("running");
    }
  }, [events, status]);

  const value = useMemo(
    () => ({
      ecrId,
      setEcrId,
      status,
      workflowId,
      events,
      analysis,
      error,
      health,
      startedAt,
      analyze,
      selectEcr,
      approve,
      loadAnalysis,
      isDemoMode: Boolean(health?.demo_mode),
    }),
    [ecrId, status, workflowId, events, analysis, error, health, startedAt, analyze, selectEcr, approve, loadAnalysis]
  );

  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>;
}

export function useAnalysis() {
  const context = useContext(AnalysisContext);
  if (!context) throw new Error("useAnalysis must be used inside <AnalysisProvider>");
  return context;
}

export default AnalysisContext;
