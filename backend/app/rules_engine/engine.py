"""
RulesEngine.evaluate()

Runs all deterministic policy checks in a fixed order and returns a
RulesEvaluationResult bundling every TraceEntry plus intermediate
values the DecisionSynthesizerAgent needs (line item decisions,
coverage breakdown, etc.).

Order of checks (each appends a TraceEntry regardless of pass/fail;
the synthesizer decides what early-exits into REJECTED):

1. Member lookup (MEMBER_NOT_FOUND if missing)
2. Waiting period check
3. Condition-level exclusion check
4. Pre-authorization check
5. Per-claim limit check
6. Category sub-limit check
7. Annual OPD limit check
8. Line-item exclusion check (for itemized bills)
9. Coverage calculation (discount -> copay -> cap)

Component contract
-------------------
evaluate(ctx: ClaimContext, policy: PolicyTerms) -> RulesEvaluationResult
    .traces: list[TraceEntry]              -- all checks, in order
    .hard_rejections: list[tuple[str, TraceEntry]]  -- (code, entry) for
        checks that must REJECT the whole claim if failed:
        MEMBER_NOT_FOUND, WAITING_PERIOD, EXCLUDED_CONDITION,
        PRE_AUTH_MISSING, PER_CLAIM_EXCEEDED
    .line_item_decisions: list[LineItemDecision]
    .approved_amount: float
    .coverage_breakdown: dict
    .is_network_hospital: bool

Raises: nothing. Genuinely unexpected errors (bad data shapes) bubble
up to BaseAgent.run_safe at the agent boundary, which degrades gracefully.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.claim import ClaimContext
from app.models.documents import LineItem
from app.models.decision import TraceEntry, TraceStatus, LineItemDecision
from app.models.policy import PolicyTerms

from app.rules_engine.waiting_periods import check_waiting_period
from app.rules_engine.exclusions import check_condition_exclusion, check_line_item_exclusions
from app.rules_engine.preauth import check_pre_authorization
from app.rules_engine.limits import (
    check_per_claim_limit,
    check_category_sub_limit,
    check_annual_opd_limit,
)
from app.rules_engine.coverage_calculator import calculate_coverage


@dataclass
class RulesEvaluationResult:
    traces: list[TraceEntry] = field(default_factory=list)
    hard_rejections: list[tuple[str, TraceEntry]] = field(default_factory=list)
    line_item_decisions: list[LineItemDecision] = field(default_factory=list)
    approved_amount: float = 0.0
    coverage_breakdown: dict = field(default_factory=dict)
    is_network_hospital: bool = False
    diagnosis_text: str | None = None
    treatment_text: str | None = None


def _gather_text_fields(ctx: ClaimContext) -> tuple[str | None, str | None, list[str], list[LineItem], float]:
    """
    Pulls diagnosis/treatment text, tests ordered, line items, and total
    bill amount out of ctx.extractions (or, if extraction was skipped
    due to a component failure, directly from ctx.submission.documents
    -- this is the fallback path for TC011).
    """
    diagnosis_parts = []
    treatment_parts = []
    tests_ordered: list[str] = []
    line_items: list[LineItem] = []
    bill_total = 0.0

    sources = ctx.extractions if ctx.extractions else None
    if sources:
        for ex in sources:
            f = ex.extracted_fields or {}
            if f.get("diagnosis"):
                diagnosis_parts.append(str(f["diagnosis"]))
            if f.get("treatment"):
                treatment_parts.append(str(f["treatment"]))
            tests_ordered += [str(t) for t in f.get("tests_ordered", []) or []]
            for li in f.get("line_items", []) or []:
                try:
                    line_items.append(LineItem(description=li["description"], amount=li["amount"]))
                except (KeyError, TypeError):
                    continue
            if f.get("total"):
                bill_total = max(bill_total, float(f["total"]))
    else:
        # Fallback: extraction was skipped (degraded pipeline). Read
        # raw `content` directly off the submission documents.
        for doc in ctx.submission.documents:
            f = doc.content or {}
            if f.get("diagnosis"):
                diagnosis_parts.append(str(f["diagnosis"]))
            if f.get("treatment"):
                treatment_parts.append(str(f["treatment"]))
            tests_ordered += [str(t) for t in f.get("tests_ordered", []) or []]
            for li in f.get("line_items", []) or []:
                try:
                    line_items.append(LineItem(description=li["description"], amount=li["amount"]))
                except (KeyError, TypeError):
                    continue
            if f.get("total"):
                bill_total = max(bill_total, float(f["total"]))

    diagnosis_text = "; ".join(diagnosis_parts) if diagnosis_parts else None
    treatment_text = "; ".join(treatment_parts) if treatment_parts else None
    return diagnosis_text, treatment_text, tests_ordered, line_items, bill_total


def evaluate(ctx: ClaimContext, policy: PolicyTerms) -> RulesEvaluationResult:
    sub = ctx.submission
    result = RulesEvaluationResult()
    category = sub.claim_category.upper()

    # --- Member lookup ---------------------------------------------------
    member = policy.get_member(sub.member_id)
    if member is None:
        entry = TraceEntry(
            stage="member_lookup",
            component="RulesEngine.member_lookup",
            status=TraceStatus.FAIL,
            message=(
                f"Member ID '{sub.member_id}' was not found in the policy "
                f"member roster. This claim cannot be processed."
            ),
            details={"member_id": sub.member_id},
        )
        result.traces.append(entry)
        result.hard_rejections.append(("MEMBER_NOT_FOUND", entry))
        return result

    diagnosis_text, treatment_text, tests_ordered, line_items, bill_total = _gather_text_fields(ctx)
    result.diagnosis_text = diagnosis_text
    result.treatment_text = treatment_text

    # --- Waiting period -----------------------------------------------------
    wp_entry = check_waiting_period(member, policy, sub.treatment_date, diagnosis_text)
    result.traces.append(wp_entry)
    if wp_entry.status == TraceStatus.FAIL:
        result.hard_rejections.append(("WAITING_PERIOD", wp_entry))

    # --- Condition-level exclusion -----------------------------------------
    excl_entry = check_condition_exclusion(diagnosis_text, treatment_text, policy)
    result.traces.append(excl_entry)
    if excl_entry.status == TraceStatus.FAIL:
        result.hard_rejections.append(("EXCLUDED_CONDITION", excl_entry))

    # --- Pre-authorization ----------------------------------------------------
    line_item_descs = [li.description for li in line_items]
    preauth_entry = check_pre_authorization(
        category=category,
        claimed_amount=sub.claimed_amount,
        tests_ordered=tests_ordered,
        line_item_descriptions=line_item_descs,
        policy=policy,
    )
    result.traces.append(preauth_entry)
    if preauth_entry.status == TraceStatus.FAIL:
        result.hard_rejections.append(("PRE_AUTH_MISSING", preauth_entry))

    # --- Per-claim limit -------------------------------------------------------
    per_claim_entry = check_per_claim_limit(sub.claimed_amount, policy)
    result.traces.append(per_claim_entry)
    if per_claim_entry.status == TraceStatus.FAIL:
        result.hard_rejections.append(("PER_CLAIM_EXCEEDED", per_claim_entry))

    # If any hard rejection so far, skip remaining computation (no point
    # computing coverage for a claim that will be rejected), but we still
    # return all traces collected so far for the explainability record.
    if result.hard_rejections:
        return result

    # --- Sub-limit & annual limit (compute headroom cap) ------------------------
    sub_limit_entry = check_category_sub_limit(sub.claimed_amount, sub.ytd_claims_amount, category, policy)
    result.traces.append(sub_limit_entry)
    annual_entry = check_annual_opd_limit(sub.claimed_amount, sub.ytd_claims_amount, policy)
    result.traces.append(annual_entry)

    if sub_limit_entry.status == TraceStatus.FAIL:
        result.hard_rejections.append(("CATEGORY_SUB_LIMIT_EXHAUSTED", sub_limit_entry))
        return result
    if annual_entry.status == TraceStatus.FAIL:
        result.hard_rejections.append(("ANNUAL_OPD_LIMIT_EXHAUSTED", annual_entry))
        return result

    headrooms = []
    if "remaining_sub_limit_headroom" in sub_limit_entry.details:
        headrooms.append(sub_limit_entry.details["remaining_sub_limit_headroom"])
    if "remaining_annual_headroom" in annual_entry.details:
        headrooms.append(annual_entry.details["remaining_annual_headroom"])
    cap = min(headrooms) if headrooms else None

    # --- Line-item exclusions (for itemized claims) --------------------------------
    if line_items:
        decisions, line_excl_entry = check_line_item_exclusions(line_items, category, policy)
        result.line_item_decisions = decisions
        result.traces.append(line_excl_entry)
        base_amount = sum(d.approved_amount for d in decisions)
    else:
        base_amount = bill_total if bill_total else sub.claimed_amount

    # --- Network hospital check -----------------------------------------------------
    is_network = bool(sub.hospital_name and sub.hospital_name in policy.network_hospitals)
    result.is_network_hospital = is_network
    result.traces.append(
        TraceEntry(
            stage="network_check",
            component="RulesEngine.network_check",
            status=TraceStatus.PASS,
            message=(
                f"Hospital '{sub.hospital_name}' is {'a network' if is_network else 'not a network'} "
                f"hospital."
            ) if sub.hospital_name else "No hospital name provided; treated as non-network.",
            details={"hospital_name": sub.hospital_name, "is_network_hospital": is_network},
        )
    )

    # --- Coverage calculation -----------------------------------------------------------
    approved_amount, breakdown, coverage_entry = calculate_coverage(
        base_amount=base_amount,
        category=category,
        is_network_hospital=is_network,
        policy=policy,
        cap=cap,
    )
    result.approved_amount = approved_amount
    result.coverage_breakdown = breakdown
    result.traces.append(coverage_entry)

    return result