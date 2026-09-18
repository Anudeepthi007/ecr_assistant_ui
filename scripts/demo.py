#!/usr/bin/env python
"""Demo driver: analyse the five demo ECRs against a running backend.

    python scripts/demo.py [--base http://localhost:8000] [--ecr ECR-2026-001]

Prints the headline result of each scenario so the platform can be validated
without opening the UI.
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    import httpx
except ImportError:  # pragma: no cover
    print("httpx is required: pip install httpx")
    raise SystemExit(1)

SCENARIOS = [
    ("ECR-2026-001", "Multi-currency payment validation", "high impact, payments blast radius"),
    ("ECR-2026-002", "Profile page button text", "low impact, UI tests only"),
    ("ECR-2026-003", "Transaction schema change", "critical dependency analysis"),
    ("ECR-2026-004", "Step-up authentication", "high security risk"),
    ("ECR-2026-005", "Notification email template", "low impact"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--ecr", action="append", help="Analyse only these ECR ids")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    client = httpx.Client(base_url=f"{args.base.rstrip('/')}/api", timeout=args.timeout)
    try:
        health = client.get("/health").json()
    except Exception as exc:
        print(f"Cannot reach the backend at {args.base}: {exc}")
        return 1

    mode = "DEMO (rule-based)" if health.get("demo_mode") else health["llm"]["effective_provider"]
    print(f"Backend {health['status']} - reasoning: {mode}\n")

    wanted = {value.upper() for value in (args.ecr or [])}
    scenarios = [row for row in SCENARIOS if not wanted or row[0] in wanted]

    header = f"{'ECR':<14} {'RISK':<14} {'TESTS':<12} {'CUT':<8} {'P0/P1/P2/P3':<14} {'TIME':<7}"
    print(header)
    print("-" * len(header))

    failures = 0
    for ecr_id, title, expectation in scenarios:
        started = time.perf_counter()
        try:
            client.post(f"/ecr/{ecr_id}/analyze?wait=true", json={})
            analysis = client.get(f"/ecr/{ecr_id}/analysis").json()
        except Exception as exc:
            print(f"{ecr_id:<14} FAILED: {exc}")
            failures += 1
            continue
        impact = analysis["impact_analysis"]
        selection = analysis["test_selection"]
        distribution = selection["priority_distribution"]
        elapsed = time.perf_counter() - started
        print(
            f"{ecr_id:<14} "
            f"{str(impact['risk_score']) + ' ' + impact['risk_level']:<14} "
            f"{str(len(selection['selected_tests'])) + '/' + str(selection['total_available']):<12} "
            f"{str(round(selection['reduction_percentage'], 1)) + '%':<8} "
            f"{'/'.join(str(distribution.get(p, 0)) for p in ('P0', 'P1', 'P2', 'P3')):<14} "
            f"{elapsed:>5.1f}s"
        )
        print(f"{'':<14} {title} - expected: {expectation}")
        print(f"{'':<14} {analysis['answer'][:160]}...\n")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
