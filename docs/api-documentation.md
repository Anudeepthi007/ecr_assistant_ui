# API documentation

Base URL: `http://localhost:8000`, prefix `/api`. Interactive docs at `/docs`.

Authentication is off by default. Set `API_KEY` and every call must send
`X-API-Key: <value>`. Set `RATE_LIMIT_PER_MINUTE` to enable the per-client
limiter.

---

## Health

### `GET /api/health`

Liveness plus an honest picture of every subsystem - including whether the LLM
circuit breaker is open and which embedder built the index.

```json
{
  "status": "ok",
  "environment": "development",
  "database": { "ok": true, "dialect": "sqlite" },
  "llm": {
    "provider": "openai",
    "effective_provider": "openai",
    "mock": false,
    "circuit_open": false,
    "cooldown_seconds": 120.0
  },
  "demo_mode": false,
  "vector_store": {
    "indexed": true,
    "embedding_mode": "local",
    "store": { "collections": { "requirements": 60, "test_cases": 239 } }
  },
  "code_analysis": { "modules": 18, "import_edges": 30 }
}
```

### `GET /api/health/data`

Row counts of the seeded corpus.

---

## ECRs

### `GET /api/ecr?search=currency&limit=50`

### `POST /api/ecr`

```json
{
  "title": "Modify payment validation for multi-currency",
  "description": "Reject unsupported currency codes before funds are reserved.",
  "business_domain": "Payments",
  "priority": "HIGH",
  "linked_requirements": ["REQ-1003"],
  "changed_files": ["payment/validator.py"]
}
```

`ecr_id` is optional - omit it and the next `ECR-<year>-NNN` is allocated.
Returns `201`, or `409` if the id already exists.

### `GET /api/ecr/{ecr_id}`

Case-insensitive. `404` when unknown.

### `GET /api/ecr/{ecr_id}/sources`

The raw multi-source view *before* correlation: the change record, every review
comment, every evidence artifact and the last analysis summary.

### `GET /api/ecr/{ecr_id}/history`

Previous analyses of this ECR.

---

## Analysis

### `POST /api/ecr/{ecr_id}/analyze`

```json
{
  "human_in_the_loop": false,
  "force_full_analysis": false,
  "description_override": null,
  "demo_mode": false
}
```

Returns `202` immediately with the workflow id and the SSE URL:

```json
{
  "workflow_id": "WF-083adfc28714",
  "ecr_id": "ECR-2026-001",
  "status": "QUEUED",
  "stream_url": "/api/workflows/WF-083adfc28714/stream"
}
```

Add `?wait=true` to block until the workflow finishes (useful for scripts and
tests; the UI streams instead).

### `GET /api/ecr/{ecr_id}/analysis`

The complete payload: `answer`, `citations`, `ecr_analysis`,
`requirement_analysis`, `defect_analysis`, `code_impact`, `dependency_analysis`,
`collaboration_analysis`, `correlation`, `impact_analysis`, `test_selection`,
`test_prioritization`, `comments`, `evidence`, `plan`, `plan_detail`, `skipped_steps`,
`execution_trace`, `errors`, `report`.

Falls back to the last persisted report when the live run has been evicted.

### `GET /api/ecr/{ecr_id}/impact`

```json
{
  "impact": {
    "directly_impacted_components": [ { "component_id": "CMP-004", "name": "Payment Validator",
                                        "impact_type": "DIRECT", "reasons": ["..."] } ],
    "indirectly_impacted_components": [],
    "mitigations": ["..."]
  },
  "dependency": { "blast_radius": 5, "critical_dependency_paths": [["CMP-001","CMP-002","CMP-003"]] },
  "code_impact": { "directly_impacted_files": ["payment/validator.py"] },
  "defects": { "similar_defects": [], "defect_prone_components": ["CMP-005"] }
}
```

### `GET /api/ecr/{ecr_id}/tests?priority=P0,P1`

```json
{
  "total_available": 170,
  "selected": 67,
  "reduction_percentage": 60.6,
  "priority_distribution": { "P0": 9, "P1": 24, "P2": 34, "P3": 0 },
  "waves": { "P0": ["TC-1020"], "P1": [], "P2": [], "P3": [] },
  "tests": [
    {
      "test_case_id": "TC-1020",
      "title": "Validate payment with a supported currency",
      "priority": "P0",
      "relevance_score": 96.4,
      "execution_order": 1,
      "breakdown": { "requirement_match": 28.5, "component_match": 25.0,
                     "dependency_relevance": 15.0, "historical_failure": 12.9,
                     "semantic_similarity": 15.0 },
      "reasons": ["covers impacted requirement REQ-1004 (95% relevance)", "..."],
      "reason": "Covers impacted requirement REQ-1004 ... Relevance 96%."
    }
  ]
}
```

### `GET /api/ecr/{ecr_id}/workflow`

Run summary, every event, the execution trace, the skipped steps and the static
graph topology for the visualisation.

### `POST /api/ecr/{ecr_id}/approve`

```json
{ "approved": true, "decided_by": "qa.lead@enterprise.com",
  "comment": "", "excluded_test_ids": ["TC-1099"] }
```

Resumes a workflow paused at the checkpoint. `409` when it is not awaiting a
decision. Excluded tests are removed from the recommendation before the report is
generated.

### `GET /api/ecr/{ecr_id}/report?format=json|markdown|html`

`422` for any other format.

---

## Live progress (SSE)

### `GET /api/workflows/{workflow_id}/stream`

```
event: connected
data: {"workflow_id":"WF-...","ecr_id":"ECR-2026-001"}

event: agent
data: {"agent":"Retrieval Agent","agent_key":"retrieval_agent","status":"running",
       "action":"Retrieving ECR details, requirements, tests, defects, comments and evidence"}

event: agent
data: {"agent":"Retrieval Agent","agent_key":"requirements",
       "status":"completed","duration":1.84,"confidence":0.93,
       "payload":{"matched":10,"searched":30,"step":true}}

event: ping
data: {"progress":0.45,"status":"RUNNING"}

event: done
data: {"workflow_id":"WF-...","status":"COMPLETED","duration":74.1,"confidence":0.89}
```

Events with `payload.step = true` are steps: `agent` is the owning agent (one of
the three) and `agent_key` is the step. The others are agent-level transitions.
Workflow start/finish and the approval checkpoint use `"agent": "Workflow"`. A `ping` every 10 idle seconds keeps proxies from
closing the connection.

```js
const source = new EventSource(`${API}/workflows/${workflowId}/stream`);
source.addEventListener("agent", (e) => render(JSON.parse(e.data)));
source.addEventListener("done", () => source.close());
```

---

## Natural language

### `POST /api/chat/query`

```json
{ "query": "Analyze ECR-2026-001 and tell me which regression tests to run" }
```

```json
{
  "answer": "...",
  "intent": "TEST_RECOMMENDATION",
  "ecr_id": "ECR-2026-001",
  "citations": ["REQ-1003", "BUG-201", "TC-1020"],
  "analysis_available": true
}
```

Intents: `ANALYZE`, `TEST_RECOMMENDATION`, `EXPLAIN_ARTIFACT`, `QUESTION`,
`SEARCH`. The ECR is resolved from an explicit id first, then by semantic search;
when neither works the assistant says so rather than guessing.

### `POST /api/ecr/{ecr_id}/ask`

```json
{ "question": "Why was TC-1042 selected?" }
```

Named artifacts are pulled into a `focus` block (score breakdown, reasons,
linked requirement) so the answer is specific.

### `GET /api/chat/intent?query=...`

Intent detection alone.

---

## Agents & telemetry

| Endpoint | Returns |
|---|---|
| `GET /api/agents` | The three agents with purpose, tools, steps, plus graph topology |
| `GET /api/agents/tools` | Every registered tool with its description |
| `GET /api/agents/runs?workflow_id=...` | Persisted per-step telemetry |

## Dashboard & catalogue

| Endpoint | Returns |
|---|---|
| `GET /api/dashboard/stats` | Totals, averages, recent ECRs and analyses |
| `GET /api/components` | Component catalogue |
| `GET /api/components/graph` | Full landscape graph (nodes, edges, stats) |
| `GET /api/reports` | Persisted report summaries |

## Feedback

`POST /api/feedback`

```json
{ "ecr_id": "ECR-2026-001", "target_type": "TEST_SELECTION",
  "target_id": "TC-1020", "useful": true, "comment": "" }
```

---

## Errors

| Status | Meaning |
|---|---|
| 400 | Malformed request |
| 401 | Missing/invalid `X-API-Key` (only when `API_KEY` is set) |
| 404 | Unknown ECR, workflow or missing analysis |
| 409 | Duplicate ECR id, or approving a workflow that is not paused |
| 422 | Schema validation failure |
| 429 | Rate limit exceeded (only when enabled) |
| 500 | Unhandled error - logged with the path, never leaking internals |
