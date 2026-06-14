"""
Pre-authorization checks.

For DIAGNOSTIC category, policy.opd_categories.diagnostic defines
`high_value_tests_requiring_pre_auth` (e.g. MRI, CT Scan, PET Scan) and
a `pre_auth_threshold` amount. If a high-value test is ordered/billed
AND the claimed amount exceeds the threshold, pre-authorization is
required. The claim submission does not carry a pre-auth reference
field in test_cases.json, so absence of any pre-auth info is treated
as "not obtained".

Component contract
-------------------
check_pre_authorization(category, claimed_amount, tests_ordered, line_item_descriptions, policy, pre_auth_ref=None) -> TraceEntry
    status PASS if pre-auth not required, or required and present.
    status FAIL if required and missing -> rejection_reasons=["PRE_AUTH_MISSING"].
    On FAIL, message explains the requirement and how to resubmit.

Raises: nothing.
"""
from __future__ import annotations

from app.models.policy import PolicyTerms
from app.models.decision import TraceEntry, TraceStatus


def _mentions_high_value_test(texts: list[str], high_value_tests: list[str]) -> str | None:
    combined = " ".join(t.lower() for t in texts if t)
    for test in high_value_tests:
        if test.lower() in combined:
            return test
    return None


def check_pre_authorization(
    category: str,
    claimed_amount: float,
    tests_ordered: list[str],
    line_item_descriptions: list[str],
    policy: PolicyTerms,
    pre_auth_ref: str | None = None,
) -> TraceEntry:
    cat_config = policy.get_category(category)

    if not cat_config or not cat_config.high_value_tests_requiring_pre_auth:
        return TraceEntry(
            stage="pre_authorization_check",
            component="RulesEngine.pre_authorization",
            status=TraceStatus.PASS,
            message=f"Category '{category}' has no pre-authorization requirements configured.",
        )

    matched_test = _mentions_high_value_test(
        tests_ordered + line_item_descriptions,
        cat_config.high_value_tests_requiring_pre_auth,
    )
    threshold = cat_config.pre_auth_threshold

    if not matched_test:
        return TraceEntry(
            stage="pre_authorization_check",
            component="RulesEngine.pre_authorization",
            status=TraceStatus.PASS,
            message="No high-value test (MRI/CT/PET) detected; pre-authorization not required.",
        )

    if threshold is not None and claimed_amount <= threshold:
        return TraceEntry(
            stage="pre_authorization_check",
            component="RulesEngine.pre_authorization",
            status=TraceStatus.PASS,
            message=(
                f"{matched_test} detected, but claimed amount ₹{claimed_amount:,.0f} "
                f"is at or below the pre-authorization threshold of "
                f"₹{threshold:,.0f}. Pre-authorization not required."
            ),
        )

    if pre_auth_ref:
        return TraceEntry(
            stage="pre_authorization_check",
            component="RulesEngine.pre_authorization",
            status=TraceStatus.PASS,
            message=f"{matched_test} required pre-authorization; reference {pre_auth_ref} found.",
            details={"matched_test": matched_test, "pre_auth_ref": pre_auth_ref},
        )

    return TraceEntry(
        stage="pre_authorization_check",
        component="RulesEngine.pre_authorization",
        status=TraceStatus.FAIL,
        message=(
            f"{matched_test} costing ₹{claimed_amount:,.0f} exceeds the "
            f"₹{threshold:,.0f} pre-authorization threshold for {category} "
            f"claims, and no pre-authorization reference was provided. "
            f"This claim cannot be approved without prior authorization. "
            f"To resubmit: obtain pre-authorization from the insurer before "
            f"the procedure (valid for {policy.pre_authorization.validity_days} days) "
            f"and include the pre-authorization reference number with your claim."
        ),
        details={
            "matched_test": matched_test,
            "claimed_amount": claimed_amount,
            "threshold": threshold,
        },
    )