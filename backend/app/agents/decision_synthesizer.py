"""
DecisionSynthesizerAgent

Combines:
  - RulesEvaluationResult (hard rejections, line items, coverage breakdown)
  - ctx.fraud_score / ctx.fraud_signals
  - extraction confidence (ctx.extractions[*].confidence) and ctx.degraded

...into a final ClaimDecision: decision status, approved_amount, reasons,
rejection_reasons, line_items, confidence_score, notes.

Confidence formula (documented here as the single source of truth)
---------------------------------------------------------------------
base_confidence = 0.95

confidence = base_confidence
            + sum(t.confidence_impact for t in ctx.trace)   # agent-reported deltas
            * (1 - fraud_score * 0.3)                         # fraud dampening
clamped to [0.0, 1.0]

Decision logic
--------------
1. If RulesEvaluationResult.hard_rejections is non-empty -> REJECTED.
   rejection_reasons = [code for code, _ in hard_rejections]
   reasons = [entry.message for _, entry in hard_rejections]

2. Else if fraud_score >= policy.fraud_thresholds.fraud_score_manual_review_threshold
   OR claimed_amount > policy.fraud_thresholds.auto_manual_review_above
   -> MANUAL_REVIEW. reasons include the fraud signals.

3. Else if ctx.degraded (a component failed) -> decision proceeds as
   APPROVED/PARTIAL based on coverage math, but confidence is reduced
   and manual_review_recommended=True with a note explaining why
   (TC011).

4. Else if any line items were rejected due to exclusions, OR
   approved_amount < claimed_amount (due to cap/copay/discount) but
   > 0 -> PARTIAL.

5. Else if approved_amount == claimed_amount-equivalent (after
   copay/discount, which is "full" coverage for that category) and
   approved_amount > 0 -> APPROVED.

6. Else -> REJECTED (approved_amount == 0 with no hard rejection is
   treated as a sub-limit exhaustion edge case).

Component contract
-------------------
Input:  ClaimContext (with .extractions, .fraud_score, .fraud_signals,
        .degraded, .trace populated by prior agents) + RulesEvaluationResult
Output: ClaimContext.decision: ClaimDecision
Raises: nothing (BaseAgent.run_safe wraps unexpected errors; if this
        agent itself fails, ctx.decision remains None and the
        orchestrator returns a MANUAL_REVIEW fallback decision).
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.models.claim import ClaimContext
from app.models.decision import ClaimDecision, DecisionStatus, TraceEntry, TraceStatus
from app.models.policy import PolicyTerms
from app.rules_engine.engine import RulesEvaluationResult


class DecisionSynthesizerAgent(BaseAgent):
    name = "DecisionSynthesizerAgent"
    stage = "decision_synthesis"

    BASE_CONFIDENCE = 0.95
    FRAUD_DAMPENING_FACTOR = 0.3

    def __init__(self, policy: PolicyTerms, rules_result: RulesEvaluationResult):
        self.policy = policy
        self.rules_result = rules_result

    def run(self, ctx: ClaimContext) -> ClaimContext:
        sub = ctx.submission
        rr = self.rules_result
        thresholds = self.policy.fraud_thresholds

        confidence = self._compute_confidence(ctx)

        # 1. Hard rejections -------------------------------------------------
        if rr.hard_rejections:
            reasons = [entry.message for _, entry in rr.hard_rejections]
            codes = [code for code, _ in rr.hard_rejections]
            decision = ClaimDecision(
                decision=DecisionStatus.REJECTED,
                claimed_amount=sub.claimed_amount,
                approved_amount=0,
                reasons=reasons,
                rejection_reasons=codes,
                confidence_score=confidence,
                notes="Claim rejected at policy rule evaluation; see trace for details.",
            )
            ctx.decision = decision
            ctx.add_trace(self._summary_trace(decision))
            return ctx

        # 2. Fraud routing ------------------------------------------------------
        fraud_triggered = (
            ctx.fraud_score >= thresholds.fraud_score_manual_review_threshold
            or sub.claimed_amount > thresholds.auto_manual_review_above
        )
        if fraud_triggered:
            decision = ClaimDecision(
                decision=DecisionStatus.MANUAL_REVIEW,
                claimed_amount=sub.claimed_amount,
                approved_amount=rr.approved_amount,
                reasons=(
                    ["Claim flagged for manual review due to anomaly signals."]
                    + ctx.fraud_signals
                ),
                confidence_score=confidence,
                manual_review_recommended=True,
                line_items=rr.line_item_decisions,
                breakdown=rr.coverage_breakdown,
                notes=(
                    f"fraud_score={ctx.fraud_score} "
                    f"(threshold={thresholds.fraud_score_manual_review_threshold}); "
                    f"claimed_amount={sub.claimed_amount} "
                    f"(auto_manual_review_above={thresholds.auto_manual_review_above})"
                ),
            )
            ctx.decision = decision
            ctx.add_trace(self._summary_trace(decision))
            return ctx

        # 3. Degraded pipeline (component failure, TC011) ------------------------
        if ctx.degraded:
            approved = rr.approved_amount
            status = DecisionStatus.PARTIAL if 0 < approved < sub.claimed_amount else (
                DecisionStatus.APPROVED if approved > 0 else DecisionStatus.MANUAL_REVIEW
            )
            decision = ClaimDecision(
                decision=status,
                claimed_amount=sub.claimed_amount,
                approved_amount=approved,
                reasons=[
                    "One or more components failed during processing; this "
                    "decision is based on partial/incomplete data."
                ],
                line_items=rr.line_item_decisions,
                breakdown=rr.coverage_breakdown,
                confidence_score=confidence,
                manual_review_recommended=True,
                notes=(
                    "A pipeline component failed and was skipped (see trace). "
                    "Confidence has been reduced and manual review is "
                    "recommended to verify the extracted data before final payout."
                ),
            )
            ctx.decision = decision
            ctx.add_trace(self._summary_trace(decision))
            return ctx

        # 4/5/6. Normal coverage-based decision -----------------------------------
        approved = rr.approved_amount
        any_line_item_rejected = any(li.status == "REJECTED" for li in rr.line_item_decisions)

        if approved <= 0:
            decision = ClaimDecision(
                decision=DecisionStatus.REJECTED,
                claimed_amount=sub.claimed_amount,
                approved_amount=0,
                reasons=["No amount payable after applying policy limits and exclusions."],
                rejection_reasons=["NO_PAYABLE_AMOUNT"],
                line_items=rr.line_item_decisions,
                breakdown=rr.coverage_breakdown,
                confidence_score=confidence,
            )
        elif any_line_item_rejected or approved < sub.claimed_amount:
            decision = ClaimDecision(
                decision=DecisionStatus.PARTIAL,
                claimed_amount=sub.claimed_amount,
                approved_amount=approved,
                reasons=["Partial approval after policy exclusions, limits, discount and co-pay."],
                line_items=rr.line_item_decisions,
                breakdown=rr.coverage_breakdown,
                confidence_score=confidence,
                notes=self._build_notes(rr),
            )
        else:
            decision = ClaimDecision(
                decision=DecisionStatus.APPROVED,
                claimed_amount=sub.claimed_amount,
                approved_amount=approved,
                reasons=["Claim approved: within all limits, no exclusions, no waiting period restrictions."],
                line_items=rr.line_item_decisions,
                breakdown=rr.coverage_breakdown,
                confidence_score=confidence,
                notes=self._build_notes(rr),
            )

        ctx.decision = decision
        ctx.add_trace(self._summary_trace(decision))
        return ctx

    def _compute_confidence(self, ctx: ClaimContext) -> float:
        confidence = self.BASE_CONFIDENCE
        for t in ctx.trace:
            confidence += t.confidence_impact
        # extraction confidence: average across documents, if any
        if ctx.extractions:
            avg_extraction_conf = sum(e.confidence for e in ctx.extractions) / len(ctx.extractions)
            confidence = confidence * (0.5 + 0.5 * avg_extraction_conf)
        fraud_dampening = 1 - (ctx.fraud_score * self.FRAUD_DAMPENING_FACTOR)
        confidence *= fraud_dampening
        return round(max(0.0, min(1.0, confidence)), 2)

    def _build_notes(self, rr: RulesEvaluationResult) -> str:
        b = rr.coverage_breakdown
        if not b:
            return None
        parts = []
        if b.get("network_discount_percent"):
            parts.append(
                f"Network discount ({b['network_discount_percent']:.0f}%) applied first "
                f"on ₹{b['base_amount']:,.0f} = ₹{b['amount_after_discount']:,.0f}."
            )
        if b.get("copay_percent"):
            parts.append(
                f"Co-pay ({b['copay_percent']:.0f}%) applied on ₹{b['amount_after_discount']:,.0f} "
                f"= ₹{b['copay_amount']:,.0f} deducted."
            )
        parts.append(f"Final: ₹{b['approved_amount']:,.0f}.")
        return " ".join(parts)

    def _summary_trace(self, decision: ClaimDecision) -> TraceEntry:
        return TraceEntry(
            stage=self.stage,
            component=self.name,
            status=TraceStatus.PASS,
            message=(
                f"Final decision: {decision.decision.value}. "
                f"Approved amount: ₹{decision.approved_amount:,.2f} of "
                f"₹{decision.claimed_amount:,.2f} claimed. "
                f"Confidence: {decision.confidence_score}."
            ),
            details={
                "decision": decision.decision.value,
                "approved_amount": decision.approved_amount,
                "confidence_score": decision.confidence_score,
                "rejection_reasons": decision.rejection_reasons,
            },
        )