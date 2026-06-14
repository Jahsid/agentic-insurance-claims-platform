"""
FraudDetectorAgent

Deterministic anomaly checks (no LLM) against policy.fraud_thresholds:
  - same_day_claims_limit: how many claims (incl. this one) the member
    has submitted on the treatment_date.
  - monthly_claims_limit: how many claims in the same month.
  - high_value_claim_threshold / auto_manual_review_above: claimed_amount
    above this triggers a flag and routes to MANUAL_REVIEW regardless of
    other checks.

Each triggered signal is appended to ctx.fraud_signals (human-readable)
and ctx.fraud_score is incremented. If fraud_score crosses
fraud_score_manual_review_threshold, or auto_manual_review_above is
exceeded, the Decision Synthesizer must route to MANUAL_REVIEW rather
than auto-rejecting (TC009).

Component contract
-------------------
Input:  ClaimContext.submission (claims_history, treatment_date, claimed_amount)
        PolicyTerms.fraud_thresholds
Output: ClaimContext.fraud_score: float (0.0-1.0+)
        ClaimContext.fraud_signals: list[str] (specific signal descriptions)
        TraceEntry appended describing all signals checked.
Raises: nothing (BaseAgent.run_safe wraps any unexpected error).
"""
from __future__ import annotations

from datetime import datetime

from app.agents.base import BaseAgent
from app.models.claim import ClaimContext
from app.models.decision import TraceEntry, TraceStatus
from app.models.policy import PolicyTerms


class FraudDetectorAgent(BaseAgent):
    name = "FraudDetectorAgent"
    stage = "fraud_check"

    SIGNAL_WEIGHT = 0.4  # each triggered signal adds this much to fraud_score

    def __init__(self, policy: PolicyTerms):
        self.policy = policy

    def run(self, ctx: ClaimContext) -> ClaimContext:
        sub = ctx.submission
        thresholds = self.policy.fraud_thresholds
        signals: list[str] = []

        treatment_date = sub.treatment_date
        try:
            treatment_month = datetime.strptime(treatment_date, "%Y-%m-%d").strftime("%Y-%m")
        except ValueError:
            treatment_month = None

        same_day_count = 1 + sum(1 for h in sub.claims_history if h.date == treatment_date)
        if same_day_count > thresholds.same_day_claims_limit:
            signals.append(
                f"Member has submitted {same_day_count} claims on {treatment_date} "
                f"(limit: {thresholds.same_day_claims_limit}). Claim IDs: "
                + ", ".join(h.claim_id for h in sub.claims_history if h.date == treatment_date)
            )

        if treatment_month:
            monthly_count = 1 + sum(
                1 for h in sub.claims_history
                if h.date.startswith(treatment_month)
            )
            if monthly_count > thresholds.monthly_claims_limit:
                signals.append(
                    f"Member has submitted {monthly_count} claims in {treatment_month} "
                    f"(limit: {thresholds.monthly_claims_limit})."
                )

        if sub.claimed_amount > thresholds.high_value_claim_threshold:
            signals.append(
                f"Claimed amount ₹{sub.claimed_amount:,.0f} exceeds the high-value "
                f"claim threshold of ₹{thresholds.high_value_claim_threshold:,.0f}."
            )

        ctx.fraud_signals = signals
        ctx.fraud_score = round(min(1.0, len(signals) * self.SIGNAL_WEIGHT), 2)

        if signals:
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.WARNING,
                    message=(
                        f"{len(signals)} fraud signal(s) detected (fraud_score="
                        f"{ctx.fraud_score}): " + " | ".join(signals)
                    ),
                    details={"signals": signals, "fraud_score": ctx.fraud_score},
                )
            )
        else:
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.PASS,
                    message="No fraud signals detected.",
                    details={"fraud_score": ctx.fraud_score},
                )
            )

        return ctx