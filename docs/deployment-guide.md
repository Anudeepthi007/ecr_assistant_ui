# Deployment guide

## 1. Local development (no infrastructure)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt   # POSIX: .venv/bin/python

cd backend
../.venv/Scripts/python -m app.seed --index      # check the CSV data + build embeddings
../.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
yarn install
yarn start          # http://localhost:3000
```

Defaults: data from the CSV files in `backend/data`, in-memory vector store, and
the mock LLM unless a key is configured. The backend loads the CSVs on startup,
then builds the embedding index in a background thread, so the API answers
immediately. It makes no LLM call at startup - that would spend a gateway
request on every boot. The first start after the data changes embeds the new
rows; later starts reuse `backend/.cache/embeddings.json`.

## 2. Docker compose

```bash
cp .env.example .env     # optional
docker compose up --build
```

| Service | Port | Notes |
|---|---|---|
| `frontend` | 3000 | CRA build served by nginx with SPA routing |
| `backend` | 8000 | uvicorn, non-root user, health-checked; `backend/data` mounted at `/data` |
| `redis` | 6379 | optional: `docker compose --profile cache up` |

The frontend URL is a **build argument** (`REACT_APP_BACKEND_URL`) because CRA
inlines env vars at build time - changing it needs a rebuild, not a restart.
The container writes changes back to the mounted CSV files, so the mounted folder
must be writable by the container user (uid 10001).

```bash
docker compose up --build -d
docker compose logs -f backend
docker compose down
```

## 3. Environment reference

See `.env.example`. The variables that actually change behaviour:

| Variable | Default | Effect |
|---|---|---|
| `DATA_DIR` | `backend/data` | Folder with the CSV data files |
| `DATABASE_URL` | temp SQLite file | Working copy the CSVs are loaded into; rarely needed |
| `LLM_PROVIDER` | `auto` | `auto` resolves by key presence; `mock` forces offline |
| `LLM_NARRATION` | `false` | `true` makes the LLM reword every step (about 7 extra calls per analysis) |
| `OPENAI_BASE_URL` | OpenAI | Point at any OpenAI-compatible gateway |
| `OPENAI_MODEL` / `OPENAI_FAST_MODEL` | `gpt-4o` / unset | Main model and the cheap model for the defect summary |
| `OPENAI_EMBEDDING_MODEL` / `EMBEDDING_DIM` | `text-embedding-3-small` / 1024 | **Must agree**; a change re-embeds every row |
| `LLM_MAX_RETRIES` / `LLM_RATE_LIMIT_MAX_WAIT_SECONDS` | 2 / 4 | How long a throttled call may wait before using the plain-text fallback. Only a 429 or a failed connection is retried - a timeout is not, because the gateway may already have billed it |
| `REMOTE_EMBEDDINGS` | `false` | `true` sends every search query to the embedding endpoint (one request each) instead of hashing vectors locally |
| `VECTOR_STORE` | `memory` | `chroma`, or `pgvector` with a PostgreSQL `DATABASE_URL` |
| `AGENT_STEP_DELAY_MS` | 0 | Artificial pause per step for demos |
| `TEST_WEIGHT_*` | 0.30/0.25/0.15/0.15/0.15 | Selection weights (should sum to 1.0) |
| `TEST_SELECTION_THRESHOLD` | 60 | Relevance cut-off; the real knob for suite size |
| `MAX_SELECTED_TESTS` | 120 | Safety valve, not the decider |
| `HUMAN_IN_THE_LOOP` | `false` | Default approval policy; the UI's "Require approval" box sets it per run |
| `API_KEY` | unset | When set, `X-API-Key` is required on every `/api` call |
| `CORS_ORIGINS` | `*` | Comma-separated list |
| `RATE_LIMIT_PER_MINUTE` | 0 (off) | Per-client-IP fixed window |

## 4. Data files

All data lives in `backend/data/`, one CSV per table (see *Storage: CSV files* in
`architecture.md` for the format).

* **Backups** are file copies of `backend/data/`.
* **Editing** by hand: stop the backend (or restart it afterwards), edit, then run
  `python -m app.seed` to check the files load. A bad value is reported as
  `defects.csv line 12, column 'detected_at': ...`.
* **Adding a column** means adding the field to the model in `app/models/`; the CSV
  header must use the same name. Rows without the new column take the default.
* **Write-back** happens shortly after each committed change and on shutdown. A
  file held open with a lock (e.g. Excel on Windows) is retried, then logged as
  `csv.write_failed` and written again on the next change.

## 5. Scaling notes

| Concern | Current | Production step |
|---|---|---|
| Data | CSV files, one process | Move to a database server; the repositories already speak SQLAlchemy |
| Workflow runs | In-process registry, capped at 100 runs, lost on restart | Move to Redis; the registry interface is small |
| SSE | Served from the same process that runs the workflow | Sticky sessions, or publish events to Redis pub/sub |
| Vector search | In-memory numpy | `VECTOR_STORE=chroma` or `pgvector` |
| Dependency graph | NetworkX, rebuilt per workflow (tens of nodes) | Neo4j behind `BaseDependencyGraph` for thousands |
| Rate limiting | In-process fixed window | API gateway or Redis token bucket |
| LLM latency | Three LLM requests per analysis, one per agent, in sequence | Cache answers per (ECR, data version) |

Run a single backend process against one data folder: the CSV writer is not
shared between processes.

## 6. Operations

* `GET /api/health` reports the data folder, LLM (including circuit-breaker
  state), vector store and code-analysis status. Use it as the readiness probe.
  `GET /api/health/data` returns the row counts.
* Logs are structured key/value lines. `WORKFLOW_ID` and `ECR_ID` appear on every
  agent event. API keys are never logged - `redact()` masks anything whose key
  looks like a secret.
* Every step appends a row to `agent_runs.csv` (status, reasoning, confidence,
  duration), and every completed workflow appends to `impact_reports.csv`. That is
  the audit trail.

## 7. Security checklist before exposing it

1. Set `API_KEY` and put the service behind your gateway.
2. Set `CORS_ORIGINS` to the real frontend origin - not `*`.
3. Enable `RATE_LIMIT_PER_MINUTE`, or rate-limit at the gateway.
4. Supply LLM keys through the secret store, never in the image.
5. Restrict who can read and write `backend/data/` - it is the whole data set.
6. Terminate TLS at the ingress; the container speaks plain HTTP by design.
7. Review what leaves the building: with a remote LLM, ECR text, requirements and
   comments are sent to that provider. `LLM_PROVIDER=mock` keeps everything local.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Backend will not start, `CSV data error` | A malformed value in a CSV | The message names the file, line and column; fix it and run `python -m app.seed` |
| Analysis is slow | Gateway throttling (429) or `LLM_NARRATION=true` | Check the log for `429`; keep narration off |
| `demo_mode: true` unexpectedly | No key configured, or the circuit opened after repeated failures | Check `llm.circuit_open` and `llm.consecutive_failures` in `/api/health` |
| Answer text is generic | Circuit breaker open after repeated failures | It half-opens after the cooldown; check `llm.circuit_open` |
| Retrieval returns nothing sensible | Embedding cache built by a different embedder | Delete `backend/.cache/embeddings.json` and restart |
| Changes missing from the CSVs | A file was locked while the app wrote it | Close the file in Excel; the next change rewrites it |
| Frontend shows "cannot reach backend" | `REACT_APP_BACKEND_URL` wrong, or CORS | Rebuild the frontend with the right URL |
| SSE never completes | Proxy buffering | The stream sends `ping` every 10s and sets `X-Accel-Buffering: no`; disable proxy buffering |
