# Demo guide

A 10-minute walkthrough that shows the assistant doing the work a person does by
hand today.

---

## 0. Start

```bash
docker compose up --build        # or: make backend / make frontend
```

* Dashboard: http://localhost:3000
* API: http://localhost:8000/docs

Check `GET /api/health` first. `demo_mode: true` means no LLM credentials were
found (or the endpoint is unreachable) - everything still works; only the prose
is rule-based instead of model-written.

---

## 1. The pitch (30s)

Open the **Dashboard**. Point at the catalogue line: 55 components, 72 dependency
edges, 251 test cases and 64 requirements across two product domains - a payments
platform and a rail (I-ETMS) onboard system. The same platform, the same schema,
two very different engineering worlds.

---

## 2. The core loop (3 min)

Go to **ECR Analysis**, type `ECR-2026-001`, press **Analyze**.

Narrate while the agents run:

1. **Retrieval Agent** - classifies the change, asks the LLM what to search for
   (synonyms and behaviours the ECR never names), plans the investigation, then
   pulls requirements, code impact, historical defects, dependency reach, review
   comments and evidence. Watch the steps tick over individually.
2. **Correlation Agent** - finds the impacted components, discovers candidate
   tests through three channels, selects and orders them, links every artefact to
   the ECR, then has the LLM read the whole bundle for contradictions and gaps.
3. **Summarization Agent** - writes the answer and the defect summary in one LLM
   reply, then assembles the report.

That is three LLM requests for the whole analysis, one per agent.

When it finishes, open **ECR Summary** and read the AI summary aloud. The
**Sources** line lists what it is based on - `REQ-1003`, `BUG-201`, `CMT-1001`, `TC-1020`. That is the difference
between a chatbot and an assistant: **the answer is citable.**

### Expected result for ECR-2026-001

| | |
|---|---|
| Directly impacted | Payment Validator, Currency Service, Payment Service |
| Indirectly impacted | Refund Service, Order Service, API Gateway, Invoice Service, Frontend Portal |
| Similar defects | BUG-101, BUG-332, BUG-201, BUG-118, BUG-281 |
| Regression | 67 of 170 payments tests, 61% reduction, 179 min instead of 424 |
| Wall clock | ~25 s, three LLM requests |

Exact numbers shift slightly with the LLM's search terms; the component sets
and the test relevance scores are stable.

---

## 3. Why it is not a chatbot (2 min)

Expand **Execution Trace**.

* One row per step: which agent ran it, its status and how long it took, then the
  total time. **Exactly three agents** - Retrieval, Correlation, Summarization.

Expand **Impacted Components**.

* The components changed directly, the ones reached through dependencies, each
  with its reason, and the recommended actions.

Expand **Review Comments and Evidence**: the payments architect warning that the
shared validator broke refunds before (BUG-332).

---

## 4. Test what matters (2 min)

Expand **Recommended Test Cases**.

* Payments suite 170, recommended 67, reduction 61%, runtime 179 min vs 424.
* Tests are listed in execution order with their priority and the reason
  each was chosen; **Show all** lists the rest.
* A typical P0 reason: *"Covers impacted requirement REQ-1004 (95% relevance);
  targets directly modified component CMP-005; historically fails in 31% of runs.
  Relevance 96%."*

---

## 5. It discriminates (2 min)

This is the strongest part of the demo. Run these and compare:

| ECR | Change | Recommended | Reduction | Baseline suite |
|---|---|---|---|---|
| `ECR-2026-002` | Profile page button text | 7 tests | 96% | payments, 170 |
| `ECR-2026-023` | EU VAT tax engine upgrade | 11 tests | 94% | payments, 170 |
| `ECR-2026-008` | Tax rounding in order totals | 31 tests | 82% | payments, 170 |
| `ECR-2026-001` | Multi-currency validation | 67 tests | 61% | payments, 170 |
| `ECR-2026-004` | Step-up authentication | 67 tests | 61% | payments, 170 |
| `ECR-2026-034` | Overspeed warning time (rail) | 3 tests | 96% | **rail, 68** |
| `ECR-2026-036` | Event recorder logging (rail) | 1 test | 99% | **rail, 68** |

A copy tweak gets 7 tests; a multi-currency validation change gets 67 across the
payment, refund and ledger paths. The two rail rows are measured against 68 rail
tests, never the 170 payments ones - the baseline is scoped to the ECR's own
product domain.

Figures above are from saved runs. Any ECR you analyse live prints its own, and
the deterministic scores are reproducible.

`ECR-2026-005` scoring HIGH is worth discussing rather than hiding: the
notification service has three critical consumers and a real production incident
(BUG-256, a template change that leaked raw placeholders to customers). The
engine is telling you something defensible, and the factor breakdown shows
exactly which part drove it.

---

## 6. Human in the loop (1 min)

Tick **Require approval** and re-run `ECR-2026-001`.

The workflow reaches the checkpoint, the stream emits `AWAITING_APPROVAL`, the page
shows *"High impact change detected"* and the workflow is genuinely blocked - not a
cosmetic modal. Approve, and the report is published; reject, and the
recommendation is withheld. You can also exclude specific tests, which rewrites
the selection before the report is generated.

---

## 7. Ask it things (1 min)

In the follow-up box:

* *"Why was TC-1020 selected?"* - answers from the score breakdown for that test.
* *"What did the team already decide?"* - answers from the comment thread.
* *"What evidence is missing?"* - answers from the evidence gap analysis.

Each question is one LLM request, on top of the three the analysis spent.

Or use the API directly:

```bash
curl -X POST localhost:8000/api/chat/query \
  -H 'content-type: application/json' \
  -d '{"query":"Analyze ECR-2026-001 and tell me which regression tests to run"}'
```

---

## 8. The report (30s)

Open **Report**: 16 sections including Correlation Findings, metrics, confidence with its penalties, and the
full agent trace. Export as HTML, Markdown or JSON, or print to PDF.

---

## Scripted version

```bash
python scripts/demo.py                     # all five scenarios, tabulated
python scripts/demo.py --ecr ECR-2026-001
```

## Talking points

* **Exactly three agents, five traced steps.** Every step is labelled with
  the agent that owns it.
* **Exactly three LLM requests, one per agent** - plan the search, review the
  correlated bundle, write the answer. A test fails if a change adds a fourth,
  and every prompt lives in one file, `app/prompts.py`.
* **The LLM never invents a number.** Deterministic engines compute; the model
  explains. That is why it still works with no API key at all.
* **Every recommendation is defensible.** Requirement matches, defect matches,
  impacted components and test selections all carry their reason.
* **It degrades honestly.** Pull the network and the analysis still completes -
  the health endpoint and the UI both say the reasoning layer is running locally.
