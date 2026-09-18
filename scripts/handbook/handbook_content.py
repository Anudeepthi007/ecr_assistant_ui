"""Text of the ECR Assistant project handbook (no secrets - key values are never included)."""
from datetime import date

TITLE = "ECR Assistant"
SUBTITLE = "AI-powered Engineering Change Request analysis - complete project handbook"
COVER_LINES = [
    "Three agents: Retrieval, Correlation, Summarization",
    "Deterministic scoring engines with an LLM for plain-language answers",
    "All data in CSV files - 45 ECRs, 64 requirements, 251 test cases, 68 defects",
    "",
    f"Version of {date.today():%d %B %Y}",
    "Prepared as a single reference document for questions about this project.",
]

CONTENT = r"""
#1 1. About this document

This handbook describes the ECR Assistant exactly as the code stands today. It is written so
that a reader who has never seen the repository - or an assistant answering questions about it -
can explain what the system does, how it works, what the numbers mean and how to run it.

Everything here is drawn from the working code: the agent definitions, the scoring engines, the
data files and the test suite. Where a number appears (a test count, a duration)
it was produced by running the system, not estimated.

#2 What this document does not contain

- No credentials. The LLM API key lives only in backend/.env, which is excluded from version
  control. The key value is not reproduced anywhere in this document.
- No customer data. All sample data in the project is synthetic, written for this project.
- No internal Capgemini or client information beyond the name of the LLM gateway that the
  backend is configured to call.

#1 2. Executive summary

The ECR Assistant answers one question: "An Engineering Change Request has landed - what does it
touch, which regression tests should we run, and has anything like it broken
before?"

Today an engineer answers that by hand, reading five systems: the change record, the requirements
tool, the test management tool, the defect tracker, and the review threads. The assistant does
that retrieval, joins the pieces together and writes the answer in plain language.

#2 What it produces for one ECR number

- A plain-language answer with the identifiers it relied on.
- The components the change touches directly and the ones it reaches indirectly, each with its
  reason, plus recommended actions.
- A recommended regression suite: which tests, in which order, why each was chosen, and how much
  execution time that saves against the full suite.
- A defect analysis: which past defects could come back, why, what to check, which defects are
  open right now in the affected area, and the defect history of the affected components.
- Review comments, evidence artefacts and any missing evidence.

#2 Headline numbers

#W 0.42 0.58
|Measure|Value|
|Agents|3 (Retrieval, Correlation, Summarization)|
|Traced steps per analysis|5|
|Time for one analysis|Usually 10 to 30 seconds with the live LLM (three requests); under 1 second offline|
|Time before the performance work|About 230 seconds|
|Regression reduction (example ECR-2026-001)|67 of 170 tests, 60.6% fewer, 179 min instead of 424 min|
|Sample data|45 ECRs, 64 requirements, 251 tests, 2,510 test runs, 68 defects, 55 components|
|Automated tests|111, all passing|
|Backend size|127 Python files, about 12,700 lines|
|Frontend size|54 React files|

#1 3. The problem and the outcome

#2 Before

For each change request an engineer opens the change record, searches the requirements tool for
anything related, opens the test management tool and guesses which regression tests matter, checks
the defect tracker for similar past failures, and reads the review thread. The work is slow, it is
repeated for every change, and the result depends on who did it and how much time they had.

Two failure modes follow. Run everything, and the regression suite costs hours of machine and
people time for a one-line copy change. Run too little, and a change ships next to an old defect
nobody remembered.

#2 After

The user types an ECR number. Three agents gather the evidence, join it up and explain it. The
answer is on screen within seconds, with every claim traceable to an identifier, and the
recommended test suite is sized to the change rather than to habit.

#2 Where the value is

- Time saved per change: the manual gathering is the expensive part, not the judgement.
- Consistency: the same change always produces the same components and the same suite, because the
  numbers come from deterministic code, not from a model.
- Explainability: every requirement match, every selected test and every impacted component carries a
  written reason, so a reviewer can disagree with a specific line rather than with a black box.
- Institutional memory: the defect analysis surfaces failures that nobody on the current team
  would remember.

#1 4. How to run the system

#2 Requirements

- Python 3.12 or newer, with the virtual environment in .venv at the repository root.
- Node.js with yarn or npm for the React frontend.
- No database server, no Docker requirement, no network requirement: the system runs fully
  offline in demo mode when no LLM key is configured.

#2 From VS Code (the usual way here)

- Open the Run and Debug panel (Ctrl+Shift+D).
- Choose "Backend" and press the green play button; or choose "Full stack" to start the backend
  and frontend together.
- Wait for this line in the terminal, which confirms the CSV data loaded:
> startup.data_loaded ... ecrs=45 requirements=64 test_cases=251
- The frontend opens on http://localhost:3000 and calls the backend on http://localhost:8000.

#2 From a terminal

> cd backend
> ..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload
> cd frontend
> yarn start

#2 With Docker

> docker compose up --build

The compose file starts the backend and the frontend only; there is no database service, because
the data is the CSV folder, which is mounted into the backend container.

#2 First start after a data change

At startup the backend builds the search index in the background, so the API answers
immediately. By default the vectors are made locally, which takes a few seconds. With
REMOTE_EMBEDDINGS=true they come from the gateway instead: the first build after a data change is
slower, and the result is cached in backend/.cache/embeddings.json so later starts only embed rows
whose text changed.

#2 Checking the data without starting the backend

> cd backend
> ..\.venv\Scripts\python.exe -m app.seed

This loads every CSV file into a private in-memory copy and prints the row counts. If a value is
malformed it reports the file, line and column, for example:
> defects.csv line 12, column 'detected_at': Invalid isoformat string

#1 5. Code structure at a glance

The project has two halves: a Python backend that does the analysis and a React frontend that
shows it. All data sits in CSV files next to the backend.

#2 Top-level folders

#W 0.3 0.7
|Folder or file|What it holds|
|backend/|The FastAPI app, the three agents, the selection logic, the data and the tests|
|backend/data/|The CSV data files and the saved reports - the only data store|
|frontend/|The React app: Dashboard, ECR Analysis and Report pages|
|docs/|Architecture, agent design, API, deployment and demo guides, and this handbook|
|scripts/|Helper scripts, including the one that builds this PDF|
|.vscode/|Run configurations: Backend, Frontend, Full stack, Backend tests|
|docker-compose.yml|Runs the backend and frontend in containers|

#2 Inside backend/app (127 Python files, about 12,700 lines)

#W 0.34 0.66
|File or folder|What it does|
|main.py|Starts the app: loads the CSV data, builds the search index in the background, registers the API routes|
|config.py|Every setting (LLM, embeddings, test-selection weights), read from backend/.env|
|prompts.py|Every instruction sent to the LLM, one block per agent|
|database.py|Loads the CSV files into a working SQL copy at startup|
|data/csv_store.py|Reads, checks and writes back the CSV files|
|models/|One class per CSV table: ECR, Requirement, TestCase, Defect, Component and so on|
|schemas/|The shapes of the data passed between steps and returned by the API|
|repositories/|Reusable database queries|
|agents/state.py|The shared workflow state, the three agents and their steps|
|agents/orchestrator.py|The workflow graph: Retrieval, Correlation, optional human approval, Summarization|
|agents/runtime.py|Run registry, live progress events, step timing and the step log|
|agents/nodes/agents.py|The three agents|
|agents/nodes/steps.py|The five steps the agents run|
|agents/nodes/ (other files)|The parts inside the steps: understanding the ECR, planning the search, requirements, code impact, past defects, dependencies, comments, impacted components, tests, links, the correlation review, defect insights and the summary|
|agents/tools/|Small reusable functions the steps call: searches, graph walks, code parsing|
|services/|Bigger building blocks: test selection, search (RAG), code analysis, reports, chat, ECR handling, confidence|
|llm/|LLM connectors (OpenAI-compatible gateway, Anthropic, offline mock) and the retry and circuit-breaker wrapper|
|vectorstore/|Where search vectors are kept (in memory by default)|
|graph/|The component dependency graph (NetworkX)|
|integrations/|Source-system adapters: the local CSV data today, Azure DevOps and Jira as stubs|
|api/routes/|The REST endpoints|
|seed/|python -m app.seed (checks the CSV files) and the small sample code repository the analyzer reads|
|tests/|111 automated tests|

#2 Inside frontend/src

#W 0.42 0.58
|File or folder|What it does|
|App.js|The page routes|
|pages/AnalyzePage.jsx|The ECR Analysis page - most of the UI|
|pages/DashboardPage.jsx, pages/ReportPage.jsx|The dashboard and the full report|
|components/agents/AgentPipeline.jsx|The live checklist and timer while the agents run|
|components/common/Sections.jsx|Collapsible sections and plain tables|
|context/AnalysisContext.jsx|Keeps the current ECR, the live events and the result|
|services/api.js|Every call to the backend|
|components/ui/|Generic UI building blocks (shadcn/ui)|

#2 How one analysis moves through the code

- The page calls POST /api/ecr/{id}/analyze (api/routes/analysis.py), and services/ecr_service.py
  starts a run.
- agents/orchestrator.py runs the graph on a background thread. The page follows the progress
  through GET /api/workflows/{id}/stream.
- The Retrieval Agent runs understand_ecr and gather_evidence: it classifies the change, LLM
  request 1 plans the search, then requirements, code impact, past defects, dependencies,
  comments and evidence are gathered.
- The Correlation Agent runs assess_impact and select_tests: the impacted components, the test
  selection and ordering (services/test_selection_service.py), the links between items, the
  defect insights, and LLM request 2, which reviews everything for conflicts and gaps.
- If "Require approval" was ticked, the approval gate waits for Approve or Reject.
- The Summarization Agent runs summarize: LLM request 3 writes the answer and the defect summary,
  and services/report_service.py builds the report.
- The report and the step log are written back to the CSV files (impact_reports.csv,
  agent_runs.csv and reports/). The page then loads the result from GET /api/ecr/{id}/analysis.

#2 Where to change common things

#W 0.42 0.58
|To change|Edit|
|The wording sent to the LLM|backend/app/prompts.py|
|The API key, models and timeouts|backend/.env and backend/app/config.py|
|The data|backend/data/*.csv|
|Test selection weights and threshold|backend/app/config.py (TEST_WEIGHT_*, TEST_SELECTION_THRESHOLD)|
|What the Analysis page shows|frontend/src/pages/AnalyzePage.jsx|

#1 6. Architecture overview

#2 Layers

#W 0.3 0.7
|Layer|Responsibility|
|React frontend|Three pages; live progress over Server-Sent Events; text and tables only|
|FastAPI layer|REST endpoints, validation, optional API key, rate limit placeholder|
|Service layer|ECR service, report service, test selection, RAG, code analysis, chat|
|Agent runtime|LangGraph state machine, run registry, event stream, step tracing|
|Repository layer|SQLAlchemy 2.0 queries over the working copy of the data|
|Data|CSV files in backend/data, loaded at startup, written back on every change|

#2 Request flow for one analysis

- The user enters an ECR number and presses Analyze.
- The API creates a workflow run, returns its id immediately and starts the agents on a worker
  thread, so the HTTP request never blocks.
- The browser opens an SSE stream for that workflow id and receives an event for every step start
  and finish, which is what fills the live checklist and the timer.
- The three agents run in order, each writing into one shared state object.
- If "Require approval" is ticked, the graph takes a conditional edge to a checkpoint and waits
  for a decision.
- The Summarization agent writes the answer and assembles the report; the report is persisted and
  the stream closes with a completion event carrying the duration.

#2 Why three agents and not ten

The first version had ten specialist agents. Three matches what a person actually does: find it,
join it up, explain it. Inside the three agents the fine-grained work still exists as steps and
parts, each traced and each able to fail without stopping the analysis, so the progress view stays
detailed without a sprawling graph. A guardrail test fails the build if a fourth agent appears.

#1 7. The three agents and five steps

#W 0.22 0.26 0.52
|Agent|Step|What it does|
|Retrieval|1. Understand the ECR|Classifies the change, extracts features and keywords, plans the investigation|
|Retrieval|2. Gather evidence|Requirements, code impact, related defects, dependencies, comments and evidence|
|Correlation|3. Assess impact|Directly and indirectly impacted components, recommended actions|
|Correlation|4. Select tests|Discovers, scores, selects and orders tests; links artefacts; analyses defects|
|Summarization|5. Summarize|Writes the grounded answer and the defect summary, assembles the report|

#2 Agent 1 - Retrieval

Purpose: given an ECR number, gather everything that exists about it.

- The LLM plans the search first (request 1): search words and things that could break, which
  widen the requirement and defect searches.
- Change classification is deterministic: each change type has a signal vocabulary, and the paths
  of the changed files add weight. If the top two types are within 0.08 of each other the result
  is a mixed change.
- Entity extraction pulls affected features, technical keywords, candidate components and risk
  indicators (for example financial transaction, schema migration, authentication change,
  shared library change, concurrency change).
- Requirement tracing combines three channels: explicit links on the ECR, semantic search and
  keyword search, merged and re-ranked, each with a written reason.
- Code impact parses the declared changed files with Python's ast module, walks the import graph
  and resolves which components the change reaches.
- Defect retrieval merges semantic similarity over incident write-ups with defects recorded
  against the impacted components.
- Collaboration retrieval pulls review comments and evidence, and extracts decisions, raised
  risks, scope statements and evidence gaps.

#2 Agent 2 - Correlation

Purpose: connect every artefact to the ECR, find the impacted components and decide which tests
matter.

- Impact assessment lists the components the change touches (section 9).
- Test discovery, scoring, selection and ordering produce the recommended suite (section 10).
- The correlation graph links requirements, tests, defects, components, comments and evidence to
  the ECR with typed, explained edges.
- Defect insight checks each related defect against this change (section 11).
- The LLM reviews the whole correlated bundle (request 2) for conflicts and gaps, which the page
  lists under Conflicts and Gaps.

#2 Agent 3 - Summarization

Purpose: answer the question from the correlated bundle, and publish the report.

- The answer is generated only from the correlated bundle, and it cites the identifiers it used.
  The model is instructed never to invent an identifier or a number.
- The defect summary explains the defect findings in three or four plain sentences.
- One LLM request (request 3) writes both the answer and the defect summary.
- The report assembles fifteen sections, the confidence score and the execution trace.

#2 Each ECR is analysed within its own scope

Every ECR names its own scope: its linked requirements and its affected test cases (ecrs.csv).
The analysis shows only data that belongs to it (backend/app/agents/nodes/scope.py):

- Requirements: only the linked ones (plus the requirement in an "L2R26:TC1" style test id).
- Tests: the listed affected test cases and the tests traced to those requirements. Similarity
  search still scores and orders them, but never adds a test.
- Past defects: only those raised against the linked requirements.
- Impacted components: the component of each linked requirement changes directly; the other
  components those requirements name are listed as reached.
- Comments and evidence: only those attached to the ECR itself. For ECR-1 and ECR-2 the export's
  attachments are their evidence.

For the sample ECRs, the affected test cases are the tests traced to their linked requirements.
An ECR created without any linked requirement or test falls back to the wider search.

#2 Steps and parts

Each step calls smaller parts. A part that fails is recorded, marks its evidence unavailable,
lowers confidence and lets the analysis finish. Only two steps are critical: understanding the
ECR and summarizing. Everything else degrades.

#1 8. Planning, routing and human approval

#2 The plan

After classification the planner decides what evidence is worth gathering for this specific
change, and writes a reason for every decision. Requirements, code impact, related defects and
review comments are always gathered. The dependency walk is skipped for a presentation-only change
with no risk indicators, because it cannot change the answer for such a change.

#2 Routing

The routing reason is recorded with each run (it is not shown on the page), for example: "UI change with 0 risk indicator(s)
detected. Not needed: component dependencies." Dependency-heavy change types are database, API,
backend, integration, security, infrastructure and mixed changes.

#2 Human in the loop

When "Require approval" is ticked for a run, the workflow stops at a checkpoint before the report
is published. The UI shows how many tests are recommended and offers Approve or Reject. The workflow blocks until the decision arrives, then continues or
withholds the recommendation. This is a real conditional edge in the graph, not a UI trick.

#1 9. Impacted components

The Correlation Agent lists which components a change touches. No score is computed - the output
is the list itself, with a reason on every entry.

- Changed directly: components resolved from the changed files by the code analyzer. When no file
  resolves, the components named in the ECR are used, then the components of its linked
  requirements.
- Reached through dependencies: components the dependency walk shows the change propagates to.
- Each component carries its reasons: changed directly, how many dependency hops away, whether it
  has related past defects, and its business criticality.
- Recommended actions come from the change's risk indicators (for example schema migration or
  shared library change) and from open review concerns.

#2 Two design rules worth knowing

- Direct impact rests on the strongest available evidence: components resolved from the actual
  changed files beat components guessed from keywords.
- Components below a propagation floor (0.25) are described as reachable, not impacted, and left
  out. Without that rule a one-line copy change pulled in services two hops away from it.

#2 Examples from the current data

#W 0.34 0.66
|ECR|Changed directly|
|ECR-2026-001 (multi-currency validation)|Payment Service, Payment Validator, Currency Service - and 13 more reached|
|ECR-2026-002 (profile page button label)|Frontend Portal only; the dependency walk is not needed|

#1 10. Regression test selection engine

#2 How a test is scored

Every candidate test is scored from 0 to 100 on five weighted factors.

#W 0.34 0.14 0.52
|Factor|Weight|What it measures|
|Requirement match|0.30|The test verifies a requirement the change affects|
|Component match|0.25|The test covers an impacted component|
|Dependency relevance|0.15|The test covers something downstream of the change|
|Historical failure|0.15|This test has caught real failures before|
|Semantic similarity|0.15|The test text resembles the change description|

#2 Selection and ordering

- Tests scoring below the relevance threshold (60) are dropped. The threshold, not the cap, is
  what decides suite size; the cap of 120 tests is a safety valve.
- Selected tests are banded into P0 to P3 and ordered by band, then component criticality, then
  relevance, then shortest runtime - so the fastest failure signal inside a band comes first.
- The baseline is scoped to the ECR's own product domain, so a payments change is measured
  against the payments suite and never against the rail suite.
- Every selected test carries a written reason, and the excluded ones are counted.

#2 Worked examples from the current data

#W 0.26 0.2 0.54
|ECR|Selected|Effect|
|ECR-2026-001|67 of 170|60.6% fewer tests, 179 min instead of 424 min, 9 P0 and 23 P1|
|ECR-2026-020|39 of 170|77.1% fewer tests, 101 min instead of 424 min|
|ECR-2026-002|7 of 170|95.9% fewer tests, 11 min instead of 424 min, all P1|

! The reduction figure answers the question a test manager asks first: what do we not have to run?

#1 11. Defect analysis

Defect analysis runs inside the same three agents - the Retrieval agent finds the defects, the
Correlation agent checks them against the change, and the Summarization agent explains them.

#2 What it answers for each related defect

- What went wrong, and the root cause.
- Why it matters for this change: the change touches the component where it happened, or it broke
  a requirement this ECR also affects, or it reached production last time.
- Can it happen again: High, Medium or Low.
- What to check: the recommended tests that cover it, or a manual check when no test covers it.

#2 How the recurrence rating is decided

A weighted score combines severity, similarity, whether this change touches the defect's component
(directly or indirectly), whether the defect broke a shared requirement, whether it escaped to
production, and how often it was reopened. One rule overrides the score: a defect can only be
rated Medium or High if this change actually touches its code. Without that rule almost every
defect in the sample rated High, because most of them are severe and reached production.

#2 What the section shows

- A plain-language summary of three or four sentences.
- Related past defects, with the four answers above.
- Defects that are open right now on the affected components, with how long they have been open.
- The defect history of each affected component: how many past defects, how many were high or
  critical, how many are still open, how many reached production, when the last one happened and
  the usual cause.

Because the last two parts come from component history rather than from text similarity, the
section is never empty: even a change with no similar past defect shows how defect-prone the area
is. Every sample ECR produces a populated section.

#2 Example

For ECR-2026-014 (reserve stock at add-to-cart) the summary reads: 10 past defects are related;
BUG-401 (stock oversold during a flash sale) and BUG-421 (checkout failed when the inventory
service timed out) could happen again; the recommended tests cover every defect that could come
back; BUG-421 is still open in the affected area. The history table shows the Order Service with
4 past defects, 1 still open, the most recent 25 days ago, usually caused by a resilience gap.

#1 12. Retrieval (RAG) and embeddings

#2 Hybrid retrieval

Requirements, defects, test cases and ECR descriptions are indexed. A query is answered by
blending two signals: dense vector similarity (weight 0.65) and lexical keyword overlap (weight
0.35). Enterprise artefacts are short and full of identifiers, so pure vector search is brittle on
them; the lexical half keeps identifier matches strong.

#2 Embeddings

- By default the vectors are made locally (hashed, 1024 dimensions), so searching costs no
  gateway requests at all.
- Set REMOTE_EMBEDDINGS=true to use the gateway's embedding model (amazon.titan-embed-text-v2:0)
  instead. Vectors from two different embedders are not comparable, so the index records which
  embedder built it and rebuilds when that changes.
- Remote vectors are cached in backend/.cache/embeddings.json, keyed by a hash of each row's text,
  so only rows whose text changed are embedded again.

#1 13. Dependency graph and code analysis

#2 Component graph

The components and their dependencies are loaded into a NetworkX graph: 55 nodes and 72 edges in
the current data. Each edge carries a type (synchronous API, library, database access,
asynchronous event) and a criticality, and the propagation weight is the type weight multiplied by
a criticality factor. Walking downstream from the changed components produces the blast radius,
decayed by distance, plus the critical paths through it.

#2 Code analysis

A real Python analyzer parses the sample repository (18 modules) with the ast module: functions,
classes, imports, call targets, route constants. From the declared changed files it resolves the
directly impacted modules, walks the import graph for dependents, and maps files to components.
Java and C# analyzers exist as stubs behind the same interface.

#1 14. LLM setup, resilience and cost control

#2 Provider

The backend talks to an OpenAI-compatible enterprise gateway (the Capgemini Generative Engine
Platform). Configuration lives in backend/.env, which is excluded from version control:
OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_FAST_MODEL and OPENAI_EMBEDDING_MODEL. The
key value is not part of this document.

#W 0.4 0.6
|Role|Model configured|
|The three agent requests (OPENAI_FAST_MODEL)|anthropic.claude-haiku-4-5|
|Ask a Question answers (OPENAI_MODEL)|openai.gpt-5-mini|
|Embeddings, only with REMOTE_EMBEDDINGS=true|amazon.titan-embed-text-v2:0 (1024 dimensions)|

#2 The rule that keeps it trustworthy

Deterministic engines compute every number; the LLM only writes prose about numbers it was given.
A model failure therefore cannot change the impacted components or a test list - it can only cost you the
nicer wording, because every call carries a deterministic fallback text.

#2 Resilience

- There is no LLM call at startup: every gateway request counts against the quota, and each agent
  falls back to its rules when the gateway is down.
- Only a rate limit (HTTP 429) or a failed connection is retried - twice, honouring the gateway's
  Retry-After and waiting at most 4 seconds. A timeout (60 seconds) is not retried, because the
  gateway may already have processed, and billed, that request.
- After three consecutive failures a circuit breaker opens and every later call is served locally;
  it half-opens after a 120 second cooldown and tries the real model again.
- A refused call returns the caller's grounded fallback text. This matters: an earlier version
  returned the offline provider's echo of the prompt, which briefly put raw prompt text on the
  page.

#2 Cost control

Three LLM requests are made per analysis, one per agent: plan the search, review the correlated
bundle, and write the answer with the defect summary. Step narration is off by default
(LLM_NARRATION=false). Turning it on adds about seven more calls per analysis and makes
runs several times slower, for wording only.

#2 Offline mode

With no key configured the system runs end to end on deterministic code and rule-based text. Demo
mode is a first-class path, not a stub: the same components, the same suites, the same sections.

#1 15. Performance

#W 0.45 0.25 0.3
|Situation|Time|Note|
|Live LLM, current code|Usually 10 to 30 s|Three short requests, one per agent|
|Offline (no LLM)|Under 1 s|All deterministic work|
|Live LLM, before the optimisation|About 230 s|Nine sequential calls on a throttled gateway|
|Search index at startup|A few seconds|Local vectors; the remote option is slower the first time, then cached|

#2 What made it slow, and what changed

- The old code made about nine LLM calls per analysis, one after another, seven of them only to
  reword text that already existed in a deterministic form. Those are off by default now.
- Each throttled call was waiting roughly 25 seconds through its retries. Retry waits are now
  capped, and a call that still fails uses its fallback text.
- What is left is three short requests, one per agent.
- A fixed 220 ms pause per step, added originally to make demos watchable, is now 0 by default.
- Search uses local vectors by default, so it needs no gateway requests at all.

#2 What the user sees

The page shows a live timer while the agents run, each step's duration in the checklist, and the
total time in the execution trace once the run completes.

#1 16. Data storage: CSV files

All data lives in CSV files under backend/data. There is no database server and no .db file in
the project.

#W 0.34 0.16 0.5
|File|Rows|Contents|
|ecrs.csv|45|Change requests, including the columns of the change-tracking export (see below)|
|requirements.csv|64|Requirements traced to components and features|
|test_cases.csv|251|Test cases with folder, technique, polarity, automation status, failure rate|
|test_executions.csv|2,510|Ten past runs per test, consistent with its failure rate|
|defects.csv|68|Past and open defects with root cause, component and linked requirements|
|components.csv|55|Services, modules, databases and interfaces with business criticality|
|dependencies.csv|72|Which component depends on which, with type and criticality|
|comments.csv|55|Review comments on ECRs, with author, category and sentiment|
|evidence.csv|46|Test runs, reviews and documents attached to ECRs|
|impact_reports.csv|grows|One row per completed analysis|
|agent_runs.csv|grows|Step log: status, reasoning, confidence, duration|
|feedback.csv|grows|User feedback on recommendations|
|reports/ (folder)|grows|The full report of each analysis, one JSON file per run|

#2 ECRs from the change-tracking export

ECR-1 and ECR-2 were added in the column layout of the change-tracking tool export, and the app
returns those values unchanged: Type, Id, Summary, Status, Severity, Assigned Testers, Actual and
Planned Modified Software Objects, Build Resolved In, Test Estimate (Archived), Estimate, Test
Estimate, Creation Date, Modified Date, Software Integration Test Assigned Testers, Test Actual
Time, Description, Affected Test Cases, Steps to Reproduce, Observed Behavior, Expected Behavior
and Attachments. They are separate columns in ecrs.csv (lifecycle_status holds the export's
Status, so an analysis never overwrites it - the app's own NEW / ANALYSED state stays in status).

- The affected test cases (L2R26:TC1 ...) exist in test_cases.csv, and their requirements (L2R26,
  L2R35, L2R01, L2R05) in requirements.csv. The requirement and test wording was written from the
  ECR descriptions as sample text and should be replaced with the approved text.
- Every test the ECR lists is always recommended, marked P0 and run first, with the reason
  "Listed as an affected test case on the ECR".
- More export rows can be added the same way: one row per ECR in ecrs.csv, list columns as JSON
  text, for example ["Deepak Yadav"].

#2 Format conventions

- The header row is the column names, which match the model fields.
- Lists and objects are JSON text inside the cell; booleans are true or false; times are ISO-8601.
- An empty cell means "use the default".
- dependencies.csv refers to components by component_id, not by row number.
- A full report is too large for a cell, so impact_reports.csv stores a path and the JSON lives in
  data/reports/<workflow_id>.json.

#2 How the app uses them

At startup the files are loaded into a working SQL copy - a temporary SQLite file rebuilt on every
start - so the repositories, agents and routes keep using ordinary SQLAlchemy queries. Every
committed change is written back to the matching CSV file by a background writer that coalesces
changes, writes to a temporary file and swaps it in, so a crash cannot leave a half-written file.
Pending changes are also flushed on shutdown.

#2 Editing the data

Edit the files with the backend stopped, or restart it afterwards, then run python -m app.seed to
check they load. If a file is open in Excel when the app tries to write it, the write is retried
and logged; the next change rewrites it.

#1 17. Sample data: what it is and is not

All data in this project is synthetic. It was written for the project to exercise the engines; it
contains no customer data and no data exported from a real programme.

It models two domains that share one schema:

- Commerce and payments: portal, gateway, payment service and validator, currency, orders,
  refunds, ledger, invoicing, fraud screening, plus the newer inventory, shipping, catalog,
  promotions, loyalty, subscriptions, wallet, chargebacks, payouts, tax, KYC, consent, audit,
  search, mobile backend, event broker, support portal, warehouse, gift cards and returns.
- Rail (I-ETMS / PTC onboard segment): requirements written as "the on-board segment shall ..."
  statements with TBC parameters, and test cases exported in the enterprise format with Folder,
  Optimization Technique, Test Type (Positive or Negative), Test Technique, Retired and Scorable
  columns. This mirrors the artefact shapes used on rail signalling programmes.

The domain field is the only discriminator; both domains use the same tables, the same engines and
the same agents. That is the point: the platform is domain-agnostic, and only the content differs.

#1 18. API reference

All endpoints are under the /api prefix. Interactive documentation is served at /docs.

#W 0.46 0.54
|Endpoint|Purpose|
|GET /api/health|Status of data, LLM, vector store and code analysis|
|GET /api/health/data|Row counts of the loaded data|
|GET /api/ecr|List or search change requests|
|GET /api/ecr/{id}|One change request|
|POST /api/ecr/{id}/analyze|Start an analysis; returns a workflow id and stream URL|
|GET /api/ecr/{id}/analysis|Full analysis payload (live run, else the saved report)|
|GET /api/ecr/{id}/impact|Impact, dependency and defect view|
|GET /api/ecr/{id}/tests|Recommended tests, filterable by priority|
|GET /api/ecr/{id}/sources|The raw multi-source view behind the analysis|
|GET /api/ecr/{id}/history|Previous analyses of this ECR|
|GET /api/ecr/{id}/report|The full report|
|POST /api/ecr/{id}/approve|Approve or reject at the human checkpoint|
|POST /api/ecr/{id}/ask|Ask a follow-up question about this ECR|
|GET /api/workflows/{id}|Status of one workflow run|
|GET /api/workflows/{id}/stream|Server-Sent Events stream of agent progress|
|GET /api/agents|The agent catalogue|
|GET /api/agents/tools|Every registered tool|
|GET /api/agents/runs|Persisted step log|
|GET /api/reports|Saved reports|
|GET /api/dashboard/stats|Dashboard figures|
|GET /api/components|Components|
|GET /api/components/graph|Dependency graph as nodes and edges|
|POST /api/chat/query|Conversational query across ECRs|
|POST /api/feedback|Record feedback on a recommendation|

#1 19. User interface

React 19 with Tailwind and shadcn/ui. Three pages, deliberately plain: text and tables, no charts
and no graph visualisations.

#2 Dashboard

Every change request and the latest analysis of each, as plain tables.

#2 ECR Analysis

- An ECR lookup box with an approval switch and an Analyze button.
- While the agents run: a live checklist of the three agents and their steps, each with its own
  duration, and a running timer.
- Execution Trace: one row per step with the agent that ran it, its status and duration, and the
  total time.
- ECR Summary: the headline facts plus a Copy for Teams button that copies the summary as
  formatted text.
- ECR Details, Requirements, Recommended Test Cases, Impacted Components (with recommended
  actions), Defect Analysis, Conflicts and Gaps, Review Comments and Evidence.
- Ask a Question: follow-up questions answered from the same correlated bundle.

#2 Report

The full report section by section, including the confidence score and its penalties.

#1 20. Testing and quality

111 automated tests, all passing. They run in parallel across two workers, each with a private copy
of the data files, so a test that writes data cannot disturb the real CSVs.

#W 0.36 0.64
|Area|What the tests guard|
|Three-agent guardrail|Exactly three agents, five steps, no module posing as an agent|
|Workflow|Every stage produces output; the expected payment impact; defect analysis is explained|
|Impacted components|Direct and indirect components are found; no score is produced|
|Test selection|Suite is smaller than the baseline; every test has a reason; bands are counted|
|Retrieval and graph|Hybrid search finds the right artefacts; blast radius is correct|
|CSV store|Files load; changes are written back; a bad value names file, line and column|
|LLM resilience|429 is retried; a refused call returns the fallback, never the prompt|
|API|Endpoint contracts and row counts|

#1 21. Security and privacy

- The LLM API key lives in backend/.env, which is gitignored. It is not in the repository and not
  in this document.
- Logs redact anything that looks like a secret. Workflow and ECR identifiers appear on every
  agent event for traceability.
- An optional API key can be required on every /api call, with CORS origins and a per-IP rate
  limit available.
- What leaves the building: with a remote LLM configured, the ECR text, requirements, comments and
  the correlated bundle are sent to that gateway. Setting LLM_PROVIDER=mock keeps everything
  local, and the system still produces the full analysis.
- The data folder is the whole data set; restricting who can read and write it is the main
  data control.

#1 22. Limitations and roadmap

#2 Known limitations

- The sample data is synthetic. Connecting real sources is the next step, not a rewrite: the
  provider interfaces exist and the local providers implement them.
- Enterprise connectors (Azure DevOps, Jira, TestRail, GitHub) are defined as interfaces with
  adapters that fail loudly until configured.
- Workflow runs are held in memory and are lost on restart; the saved report survives.
- The CSV writer assumes a single backend process per data folder.
- Only Python code analysis is implemented; Java and C# analyzers are stubs.
- The gateway currently rate-limits this key, which is what makes the three LLM requests take seconds
  rather than under a second.

#2 Natural next steps

- Connect one real source system (requirements or defects) behind the existing interface.
- Move workflow runs and the event stream to Redis so several backend processes can serve them.
- Feed real execution results back in, so the historical-failure factor learns from actual runs.
- Add a per-team threshold configuration so different products can size suites differently.

#1 23. Repository map

#W 0.42 0.58
|Path|Contents|
|backend/app/main.py|FastAPI application, startup, warmup|
|backend/app/config.py|All settings and engine weights|
|backend/app/database.py|Working copy engine, session factory, CSV loading|
|backend/app/data/csv_store.py|CSV table specs, loading, validation, write-back|
|backend/app/agents/state.py|Agent catalogue, shared workflow state|
|backend/app/agents/orchestrator.py|LangGraph graph, approval edge, report persistence|
|backend/app/agents/runtime.py|Run registry, event stream, step tracing|
|backend/app/agents/nodes/|The five steps and their parts|
|backend/app/agents/tools/|Registered tools used by the steps|
|backend/app/services/|Test selection, RAG, code analysis, report, chat, confidence|
|backend/app/models/|SQLAlchemy models - one per CSV table|
|backend/app/api/routes/|REST endpoints|
|backend/app/seed/sample_repo/|The small Python repository the code analyzer parses|
|backend/data/|The CSV data files and the reports folder|
|backend/app/tests/|111 tests|
|frontend/src/pages/|Dashboard, ECR Analysis, Report|
|frontend/src/components/agents/|Live agent checklist|
|docs/|Architecture, agent design, API, deployment, demo guide|

#1 24. Glossary

#W 0.28 0.72
|Term|Meaning|
|ECR|Engineering Change Request: a proposed change to the product|
|Agent|One of the three autonomous workers in the graph|
|Step|A traced unit of work owned by one agent; there are five|
|Part|A smaller function inside a step; may fail without stopping the analysis|
|P0 to P3|Priority bands of the recommended regression suite|
|Reduction|How much smaller the recommended suite is than the full domain suite|
|RAG|Retrieval Augmented Generation: search that grounds the model's answer|
|Embedding|A numeric vector representing text, used for similarity search|
|Circuit breaker|Protection that stops calling a failing endpoint for a cooldown period|
|Demo mode|Running with no LLM key: the same analysis with rule-based text|
|Human in the loop|The approval checkpoint, used when "Require approval" is ticked|

#1 25. Questions a manager may ask

#2 Scope and value

Q: What does this actually do?
A: You give it a change request number. It finds the related requirements, code impact, past
defects, review comments and evidence, works out which components it affects, recommends which
regression tests to run, and explains all of it in plain language within seconds.

Q: What problem does it solve?
A: The manual gathering across five systems before every change. That work is slow, repetitive and
inconsistent between people.

Q: How much time does it save?
A: Two ways. The gathering itself, which took an engineer a significant part of an hour per change,
now takes seconds. And the test run: for a payments change the recommendation was 67 tests instead
of 170, which is 179 minutes instead of 424. For a copy change it was 7 tests, 11 minutes instead
of 424.

Q: Is it accurate?
A: Every number is computed by deterministic code with weights you can see and change, and every
recommendation carries a written reason, so it can be checked line by line. The model writes only
the prose.

Q: What if the AI is wrong?
A: The AI cannot change a score or a test list; it only writes the summary. If the gateway is down
the system falls back to rule-based text and the analysis is unchanged.

#2 Technology

Q: What is it built with?
A: Python with FastAPI on the backend, LangGraph for the agent workflow, SQLAlchemy over CSV data,
React with Tailwind on the frontend. The LLM is reached through an OpenAI-compatible enterprise
gateway.

Q: How is the code organised?
A: A Python FastAPI backend and a React frontend. In the backend, agents/ holds the workflow
(orchestrator.py), the three agents (nodes/agents.py) and their five steps (nodes/steps.py);
services/ holds test selection, search and reports; prompts.py holds every LLM instruction;
the data is the CSV files in backend/data. Section 5 has the full map.

Q: How many agents are there, and why three?
A: Three - Retrieval, Correlation, Summarization - running five traced steps. Three maps onto what
a person does: find it, join it up, explain it. A test fails the build if a fourth appears.

Q: Where is the data?
A: In CSV files under backend/data, one per table. No database server. They are loaded at startup
and every change is written back to them.

Q: Is any of this real production data?
A: No. All sample data is synthetic and written for this project. The rail artefacts follow the
shape of real programme exports, but the content is invented.

Q: Does it send our data to an AI provider?
A: With the gateway configured, the ECR text and the correlated bundle are sent there for the two
summary calls. Set the provider to mock and nothing leaves the machine; the analysis still runs.

Q: Where is the API key?
A: In backend/.env, which is excluded from version control. It is not in the repository, not in
this document, and not in any shared file.

#2 Operations

Q: How long does an analysis take?
A: Usually 10 to 30 seconds with the live model, under a second offline. It was around 230 seconds
before the performance work; the fix was to stop making LLM calls that only reworded existing text,
cap the retry waiting, and keep it to three short requests, one per agent.

Q: What happens when the gateway is rate-limited?
A: The call is retried briefly, then the deterministic text is used. After three consecutive
failures the circuit breaker opens for two minutes and everything is served locally. The analysis
still completes.

Q: How do we add our own data?
A: Edit the CSV files, or replace them with exports from the real systems in the same column
format, then restart. python -m app.seed validates them and names the file, line and column of any
bad value.

Q: How do we connect the real tools?
A: The provider interfaces are already there - requirements, defects, tests, repository - with
local implementations that work and enterprise adapters that fail loudly until configured. Wiring
one real source is an adapter, not a redesign.

Q: How do we know it works?
A: 111 automated tests cover the agents, both engines, retrieval, the data layer and the API. They
run in seconds.

Q: Can it run without internet?
A: Yes, completely. That is demo mode and it is a supported path, not a stub.

Q: What would you do next?
A: Connect one real source system, move workflow runs out of process memory so it can scale
horizontally, and feed real test results back in so the historical-failure factor learns.

#2 Review and control

Q: Can a person override it?
A: Yes. Tick "Require approval" and the analysis stops at a checkpoint before the report is
published, until someone approves or rejects it. Tests can also be excluded from the recommendation.

Q: How do we audit what happened?
A: Every step writes a row to agent_runs.csv with its status, reasoning, confidence and duration,
and every completed analysis writes to impact_reports.csv with the full report JSON beside it.

Q: What does the confidence score mean?
A: It blends the confidence of each step and applies penalties for failures and missing evidence,
so a run that lost a source is visibly less certain rather than silently wrong.

#1 26. Five-minute demo script

- Open the ECR Analysis page. Point out the line "Data source: CSV files - 45 ECRs available".
- Enter ECR-2026-001 and press Analyze. While it runs, point at the live checklist: three agents,
  five steps, each with its own timer.
- When it finishes (usually well under a minute) read the ECR Summary aloud: 3 components changed directly, 67 of 170
  tests recommended, 60.6% fewer, 179 minutes instead of 424.
- Open Impacted Components: what changes directly, what is reached through dependencies, and the
  recommended actions.
- Open Recommended Test Cases and show that every row has a reason.
- Open Defect Analysis: BUG-101 currency conversion, why it matters here, whether it can come back
  and which test covers it - plus what is open right now in that area.
- Open Execution Trace and show the five steps, the agent behind each and the total time.
- Now enter ECR-2026-002, the profile page button label, and run it: 7 tests, 11
  minutes, and only the Frontend Portal changed directly.
- Close with the contrast: same system, same engines, two very different recommendations, each
  explained.
"""
