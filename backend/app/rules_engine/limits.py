"""
Limit checks: per-claim limit, category sub-limit, annual OPD limit.

Order of evaluation matters for messaging clarity:
1. Per-claim limit (policy.coverage.per_claim_limit) — hard cap on any
   single claim's *claimed* amount. TC008: claimed > per_claim_limit ->
   REJECTED, rejection_reasons=["PER_CLAIM_EXCEEDED"], message states
   both the limit and the claimed amount.
2. Category sub-limit (policy.opd_categories[category].sub_limit) —
   caps how much of the claimed amount can be approved against that
   category's annual sub-limit, considering ytd_claims_amount already
   used in that category.
3. Annual OPD limit (policy.coverage.annual_opd_limit) — overall annual
   cap across all OPD categories.

Sub-limit and annual-limit checks return the *remaining headroom*,
which the coverage calculator uses to cap the approved amount (this
can turn an APPROVED into a PARTIAL even when no exclusions apply).

Component contract
-------------------
check_per_claim_limit(claimed_amount, policy) -> TraceEntry
    FAIL -> rejection_reasons=["PER_CLAIM_EXCEEDED"]

check_category_sub_limit(claimed_amount, ytd_category_amount, category, policy) -> TraceEntry
    details.remaining_sub_limit_headroom used by coverage calculator.

check_annual_opd_limit(claimed_amount, ytd_total_amount, policy) -> TraceEntry
    details.remaining_annual_headroom used by coverage calculator.

Raises: nothing.
"""
from __future__ import annotations

from app.models.policy import PolicyTerms
from app.models.decision import TraceEntry, TraceStatus


def check_per_claim_limit(claimed_amount: float, policy: PolicyTerms) -> TraceEntry:
    limit = policy.coverage.per_claim_limit
    if claimed_amount > limit:
        return TraceEntry(
            stage="limit_check",
            component="RulesEngine.limits.per_claim",
            status=TraceStatus.FAIL,
            message=(
                f"The claimed amount of ₹{claimed_amount:,.0f} exceeds the "
                f"per-claim limit of ₹{limit:,.0f} for this policy. Claims "
                f"above this limit cannot be processed as a single claim."
            ),
            details={"claimed_amount": claimed_amount, "per_claim_limit": limit},
        )
    return TraceEntry(
        stage="limit_check",
        component="RulesEngine.limits.per_claim",
        status=TraceStatus.PASS,
        message=f"Claimed amount ₹{claimed_amount:,.0f} is within the per-claim limit of ₹{limit:,.0f}.",
        details={"claimed_amount": claimed_amount, "per_claim_limit": limit},
    )


def check_category_sub_limit(
    claimed_amount: float,
    ytd_category_amount: float,
    category: str,
    policy: PolicyTerms,
) -> TraceEntry:
    cat_config = policy.get_category(category)
    if not cat_config:
        return TraceEntry(
            stage="limit_check",
            component="RulesEngine.limits.sub_limit",
            status=TraceStatus.WARNING,
            message=f"No sub-limit configuration found for category '{category}'.",
        )

    sub_limit = cat_config.sub_limit
    remaining = max(0.0, sub_limit - ytd_category_amount)

    if remaining <= 0:
        return TraceEntry(
            stage="limit_check",
            component="RulesEngine.limits.sub_limit",
            status=TraceStatus.FAIL,
            message=(
                f"The annual sub-limit for {category} (₹{sub_limit:,.0f}) has "
                f"already been used (YTD ₹{ytd_category_amount:,.0f}). No "
                f"further claims in this category can be approved this policy year."
            ),
            details={"sub_limit": sub_limit, "ytd_category_amount": ytd_category_amount, "remaining_sub_limit_headroom": 0},
        )

    if remaining < claimed_amount:
        return TraceEntry(
            stage="limit_check",
            component="RulesEngine.limits.sub_limit",
            status=TraceStatus.WARNING,
            message=(
                f"Only ₹{remaining:,.0f} of the ₹{sub_limit:,.0f} annual "
                f"{category} sub-limit remains (YTD used: "
                f"₹{ytd_category_amount:,.0f}). The approved amount will be "
                f"capped at this remaining headroom."
            ),
            details={"sub_limit": sub_limit, "ytd_category_amount": ytd_category_amount, "remaining_sub_limit_headroom": remaining},
        )

    return TraceEntry(
        stage="limit_check",
        component="RulesEngine.limits.sub_limit",
        status=TraceStatus.PASS,
        message=(
            f"Category {category} sub-limit ₹{sub_limit:,.0f}; YTD used "
            f"₹{ytd_category_amount:,.0f}; ₹{remaining:,.0f} remaining — "
            f"sufficient headroom for this claim."
        ),
        details={"sub_limit": sub_limit, "ytd_category_amount": ytd_category_amount, "remaining_sub_limit_headroom": remaining},
    )


def check_annual_opd_limit(
    claimed_amount: float,
    ytd_total_amount: float,
    policy: PolicyTerms,
) -> TraceEntry:
    annual_limit = policy.coverage.annual_opd_limit
    remaining = max(0.0, annual_limit - ytd_total_amount)

    if remaining <= 0:
        return TraceEntry(
            stage="limit_check",
            component="RulesEngine.limits.annual_opd",
            status=TraceStatus.FAIL,
            message=(
                f"The annual OPD limit of ₹{annual_limit:,.0f} has already "
                f"been used (YTD ₹{ytd_total_amount:,.0f}). No further OPD "
                f"claims can be approved this policy year."
            ),
            details={"annual_opd_limit": annual_limit, "ytd_total_amount": ytd_total_amount, "remaining_annual_headroom": 0},
        )

    if remaining < claimed_amount:
        return TraceEntry(
            stage="limit_check",
            component="RulesEngine.limits.annual_opd",
            status=TraceStatus.WARNING,
            message=(
                f"Only ₹{remaining:,.0f} of the ₹{annual_limit:,.0f} annual "
                f"OPD limit remains (YTD used: ₹{ytd_total_amount:,.0f}). "
                f"The approved amount may be capped at this remaining headroom."
            ),
            details={"annual_opd_limit": annual_limit, "ytd_total_amount": ytd_total_amount, "remaining_annual_headroom": remaining},
        )

    return TraceEntry(
        stage="limit_check",
        component="RulesEngine.limits.annual_opd",
        status=TraceStatus.PASS,
        message=(
            f"Annual OPD limit ₹{annual_limit:,.0f}; YTD used "
            f"₹{ytd_total_amount:,.0f}; ₹{remaining:,.0f} remaining — "
            f"sufficient headroom for this claim."
        ),
        details={"annual_opd_limit": annual_limit, "ytd_total_amount": ytd_total_amount, "remaining_annual_headroom": remaining},
    )