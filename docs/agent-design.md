# Agent design

Exactly three agents - Retrieval, Correlation, Summarization - running five steps. Each step is independently traced, independently
degradable and returns a validated Pydantic contract.

## The five steps

| Agent | Step | Key | Parts it runs |
|---|---|---|---|
| Retrieval | Understand the ECR | `understand_ecr` | classify the change, plan which evidence to gather |
| Retrieval | Gather evidence | `gather_evidence` | requirements, code impact, related defects, dependencies *(optional)*, review comments and evidence |
| Correlation | Assess impact | `assess_impact` | directly and indirectly impacted components, recommended actions |
| Correlation | Select regression tests | `select_tests` | discover, select and order tests, link every artefact to the ECR, analyse each related defect |
| Summarization | Summarize and report | `summarize` | cited answer, plain-language defect summary, full report |

### Defect analysis

Every analysis also explains the past defects related to the ECR, using the same
three agents:

1. **Retrieval** finds the related defects (similar text or the same components).
2. **Correlation** (`defect_insights` part) checks each defect against this change:
   *why it matters here* (same component, shared requirement, reached production),
   *can it happen again* (High / Medium / Low from severity, similarity, whether the
   change touches its component, production escape and reopen count), and *what to
   check* (the recommended tests that cover its component or requirements, or a
   manual check when none do).
3. **Summarization** (`defect_summary` part) writes 3-4 plain sentences from those
   facts only. Offline, a deterministic summary is used.

The page shows this as one *Defect Analysis* section: the summary and a single table.

Only the five steps are traced and shown in the UI. The tables below describe
the parts inside them; a failing part is recorded, lowers confidence, and the
step continues.

---

## Agent 1 - Retrieval Agent

**Purpose.** Given an ECR number, gather everything that exists about it.

**Critical.** Yes - the workflow cannot continue without it.

| Part | Key | What it does | Tools | Optional |
|---|---|---|---|---|
| Understand the ECR | `ecr_understanding` | Deterministic change classification, entity/feature/keyword extraction, risk indicators, complexity | `classify_change`, `extract_entities` | no |
| Plan the search | `retrieval_planning` | **LLM request 1**: search terms and behaviours that could break, which widen the requirement and defect searches; may ask for the dependency walk | `llm.plan_retrieval` | no |
| Plan | `planning` | Decides which optional steps run for *this* change | `build_plan` | no |
| Requirements | `requirements` | Traceability + hybrid semantic + keyword retrieval, merged and re-ranked | `trace_requirements`, `semantic_requirement_search`, `keyword_requirement_search` | no |
| Code impact | `code_impact` | Python AST parse, module import graph walk, direct/indirect components, API surface | `analyze_changed_files`, `walk_import_graph`, `repository_stats` | no |
| Historical defects | `historical_defects` | Similar incidents, root-cause clustering | `semantic_defect_search`, `defects_by_component`, `cluster_root_causes` | no |
| Dependencies | `dependencies` | Downstream/upstream walk, decayed propagation, critical paths | `build_graph`, `downstream_walk`, `upstream_walk`, `critical_paths` | **yes** |
| Comments & evidence | `collaboration_retrieval` | Review threads and evidence artefacts, decisions/risks/scope extraction, evidence gaps | `comments_for_ecr`, `evidence_for_ecr`, `extract_comment_signals`, `evidence_gaps` | no |

### Change classification

Deterministic first: each change type has a signal vocabulary, and changed-file
paths and extensions add weight. When the top two types are within 0.08 of each
other the result is `MIXED_CHANGE` (or `API_AND_BACKEND` for that specific pair).
With an LLM configured, the model plans what to search for and may rewrite the
plain-English summary. It may not change the type, the complexity, the
confidence, the extracted keywords or the risk indicators - those stay
rule-based. Its search terms only widen the semantic query, whose relevance
threshold still decides what is kept.

### Planning policy

```python
run_dependency = force_full or change_type in DEPENDENCY_HEAVY or risk_indicators & HIGH_SIGNAL
```

Related defects are always gathered and analysed. `DEPENDENCY_HEAVY` covers
database, API, backend, integration, security, infrastructure and mixed changes.
A UI-only change with no risk indicators skips the dependency walk - and the
skip, with its rationale, is recorded in the trace and the report. Every planned and skipped step gets a written
reason, recorded with the run.

A step is not an agent: it has no graph node, cannot route the workflow, and is
labelled on the event stream with the name of the agent that owns it.

---

## Agent 2 - Correlation Agent

**Purpose.** Turn separate findings into one correlated picture.

| Part | Key | What it does | Tools |
|---|---|---|---|
| Impacted components | `impact_assessment` | Direct/indirect component impact with reasons, recommended actions | `component_impact`, `llm.narrate` (only with `LLM_NARRATION`) |
| Test discovery | `test_discovery` | Requirement traceability + component coverage + semantic search, domain-scoped | `tests_by_requirement`, `tests_by_component`, `semantic_test_search`, `resolve_domain` |
| Selection | `test_selection` | Weighted 0-100 relevance per test, threshold filter, P0-P3 banding | `selection_engine.select` |
| Prioritisation | `test_prioritization` | Priority-first execution order with fastest-feedback tie-break | `selection_engine.prioritise` |
| Artefact links | `correlation` | Typed, explained edges between the ECR and every artefact; cross-source corroboration | `build_correlation_graph` |
| Bundle review | `correlation_review` | **LLM request 2**: contradictions, gaps and key links across the correlated sources; every identifier is checked against the bundle and unknown ones are dropped | `llm.review_correlation` |

### Blast radius vs. reachability

Everything downstream in the dependency graph is *reachable*. Only what the
change meaningfully *propagates to* is treated as impacted: components whose
decayed propagation falls below `INDIRECT_PROPAGATION_FLOOR` (0.25) are recorded
as weakly coupled and kept out of both the impact list and the test scope.
Without that floor, a two-hop async edge drags an unrelated critical service into
the blast radius of a copy tweak.

### Correlation edges

| Relation | From -> To |
|---|---|
| `IMPACTS_REQUIREMENT` | ECR -> requirement |
| `IMPLEMENTED_BY` | requirement -> component |
| `SIMILAR_HISTORY` | ECR -> defect |
| `AFFECTED` | defect -> component |
| `RECOMMENDED_TEST` | ECR -> test case |
| `VERIFIED_BY` | requirement -> test case |
| `DISCUSSED_IN` | artefact -> comment |
| `REFERENCES` | comment -> artefact |
| `EVIDENCED_BY` | artefact -> evidence |
| `IMPACTS_COMPONENT` / `TOUCHES_COMPONENT` | ECR -> component |

Every edge carries a `reason` string and a weight, which is what makes the final
answer citable rather than merely plausible.

---

## Agent 3 - Summarization Agent

**Purpose.** Answer the user and publish the report.

| Part | Key | What it does |
|---|---|---|
| Answer + defect summary | `summarization` | **LLM request 3**: builds the grounded bundle, answers the question (default: "what do I need to know, and what should we test?"), explains the related past defects and collects citations - one reply carries both texts |
| Report | `report` | The full ECR Intelligence Report: every section, metrics, confidence and the complete trace |

The answer prompt is constrained: the model sees only the correlated bundle -
including the contradictions and gaps the Correlation Agent found - and is told
never to invent an identifier, number or decision. Both texts come back in one
structured reply, so the agent costs a single request. With no LLM configured, or
when the call fails, both are composed deterministically from the same bundle.
The prompt itself lives in `app/prompts.py`.

---

## Human approval checkpoint

Not an agent - a conditional node between correlation and summarization.

```python
def needs_approval(state):
    # "Require approval" in the UI sets human_in_the_loop for the run.
    options = state.get("options") or {}
    return "human_approval" if options.get("human_in_the_loop") else "summarization_agent"
```

When entered, the node emits `AWAITING_APPROVAL` on the SSE stream and blocks on
the run registry until `POST /api/ecr/{id}/approve` arrives (or the workflow
timeout elapses). A decision can also exclude specific tests, which rewrites the
selection before the report is generated.

---

## Contracts

| Step | Returns |
|---|---|
| `ecr_understanding` | `ECRUnderstanding` |
| `retrieval_planning` | `RetrievalPlan` (search terms, behaviours that could break, dependency request) |
| `requirements` | `RequirementAnalysis` (list of `RequirementMatch`) |
| `historical_defects` | `DefectAnalysis` (list of `DefectMatch`) |
| `code_impact` | `CodeImpactAnalysis` (list of `CodeSymbol`) |
| `dependencies` | `DependencyAnalysis` (nodes, edges, paths) |
| `impact_assessment` | `ImpactAssessment` (`ComponentImpact`, recommended actions) |
| `test_discovery` | `TestDiscovery` |
| `test_selection` | `TestSelection` (list of `SelectedTest` with `TestScoreBreakdown`) |
| `test_prioritization` | `TestPrioritization` |
| `correlation_review` | `CorrelationReview` (key links, conflicts, gaps) |
| `summarization` | `SummaryReply` (answer + defect summary) |
| `report` | `ECRIntelligenceReport` |

## Confidence

Each step returns its own confidence from the evidence it actually found (match
strength, breadth, whether traceability existed). The report averages them and
subtracts penalties: 0.08 per failed step, 0.05 when fewer than five steps
contributed. Bands: >=0.85 HIGH, >=0.65 MEDIUM, else LOW.

## Failure handling

`agent_step` wraps every step. On exception it records the error, emits a
`failed` event, persists a failed `AgentRun`, adds the step to `skipped_steps`
and returns an empty partial state. Downstream, `impact_assessment` sees the gap,
marks that factor as estimated and says so in the explanation. Only steps marked
`critical=True` re-raise.
