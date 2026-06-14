"""
Runs all 12 test cases from test_cases.json through the pipeline and
prints the decision + trace for each, alongside a pass/fail vs expected.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.policy_loader import load_policy
from app.orchestrator.pipeline import run_claim_pipeline
from app.models.claim import ClaimSubmission


def load_test_cases():
    path = Path(__file__).resolve().parent / "test_cases.json"
    return json.loads(path.read_text())["test_cases"]


def run_case(tc, policy):
    sub = ClaimSubmission.model_validate(tc["input"])
    ctx = run_claim_pipeline(sub, policy)
    return ctx


def summarize(ctx):
    if ctx.blocked:
        return {
            "blocked": True,
            "block_code": ctx.block_code,
            "block_message": ctx.block_message,
        }
    d = ctx.decision
    return {
        "blocked": False,
        "decision": d.decision.value,
        "approved_amount": d.approved_amount,
        "confidence_score": d.confidence_score,
        "rejection_reasons": d.rejection_reasons,
        "reasons": d.reasons,
        "notes": d.notes,
        "line_items": [li.model_dump() for li in d.line_items],
    }


def main():
    policy = load_policy()
    cases = load_test_cases()

    for tc in cases:
        ctx = run_case(tc, policy)
        summary = summarize(ctx)
        print("=" * 80)
        print(f"{tc['case_id']}: {tc['case_name']}")
        print("-" * 80)
        print("EXPECTED:", json.dumps(tc["expected"], indent=2))
        print("-" * 80)
        print("ACTUAL DECISION SUMMARY:", json.dumps(summary, indent=2, default=str))
        print("-" * 80)
        print("FULL TRACE:")
        for t in ctx.trace:
            print(f"  [{t.status.value:>8}] {t.stage:30s} | {t.component:35s} | {t.message}")
        print()


if __name__ == "__main__":
    main()