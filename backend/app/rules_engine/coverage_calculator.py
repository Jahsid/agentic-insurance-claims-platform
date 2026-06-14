"""
Coverage calculator.

Computes the final approved amount given:
  - the claimed amount (or sum of approved line items after exclusions)
  - whether the treatment was at a network hospital
  - the category's network_discount_percent and copay_percent
  - any remaining sub-limit / annual-limit headroom (caps)

CRITICAL ORDERING (TC010): network discount is applied FIRST, then
co-pay is applied on the discounted amount. E.g. ₹4,500 claimed at a
network hospital with 20% discount -> ₹3,600; then 10% co-pay on
₹3,600 -> ₹360 deducted -> ₹3,240 approved.

Component contract
-------------------
calculate_coverage(
    base_amount: float,            # amount eligible after exclusions
    category: str,
    is_network_hospital: bool,
    policy: PolicyTerms,
    cap: float | None = None,      # min(sub_limit_headroom, annual_headroom)
) -> tuple[float, dict, TraceEntry]
    Returns (approved_amount, breakdown_dict, trace_entry).
    breakdown_dict contains: base_amount, network_discount_percent,
    amount_after_discount, copay_percent, copay_amount, amount_after_copay,
    cap_applied (bool), approved_amount.

Raises: nothing.
"""
from __future__ import annotations

from app.models.policy import PolicyTerms
from app.models.decision import TraceEntry, TraceStatus


def calculate_coverage(
    base_amount: float,
    category: str,
    is_network_hospital: bool,
    policy: PolicyTerms,
    cap: float | None = None,
) -> tuple[float, dict, TraceEntry]:
    cat_config = policy.get_category(category)
    discount_pct = (cat_config.network_discount_percent if cat_config and is_network_hospital else 0) or 0
    copay_pct = (cat_config.copay_percent if cat_config else 0) or 0

    # Step 1: network discount applied first
    discount_amount = base_amount * (discount_pct / 100.0)
    amount_after_discount = base_amount - discount_amount

    # Step 2: co-pay applied on the discounted amount
    copay_amount = amount_after_discount * (copay_pct / 100.0)
    amount_after_copay = amount_after_discount - copay_amount

    cap_applied = False
    approved_amount = amount_after_copay
    if cap is not None and approved_amount > cap:
        approved_amount = cap
        cap_applied = True

    breakdown = {
        "base_amount": round(base_amount, 2),
        "is_network_hospital": is_network_hospital,
        "network_discount_percent": discount_pct,
        "discount_amount": round(discount_amount, 2),
        "amount_after_discount": round(amount_after_discount, 2),
        "copay_percent": copay_pct,
        "copay_amount": round(copay_amount, 2),
        "amount_after_copay": round(amount_after_copay, 2),
        "cap_applied": cap_applied,
        "cap_value": cap,
        "approved_amount": round(approved_amount, 2),
    }

    parts = [f"Base amount ₹{base_amount:,.2f}."]
    if discount_pct:
        parts.append(
            f"Network discount ({discount_pct:.0f}%) applied first: "
            f"₹{base_amount:,.2f} -> ₹{amount_after_discount:,.2f}."
        )
    if copay_pct:
        parts.append(
            f"Co-pay ({copay_pct:.0f}%) applied on ₹{amount_after_discount:,.2f}: "
            f"₹{copay_amount:,.2f} deducted -> ₹{amount_after_copay:,.2f}."
        )
    if cap_applied:
        parts.append(f"Result capped at remaining policy headroom of ₹{cap:,.2f}.")
    parts.append(f"Final approved amount: ₹{approved_amount:,.2f}.")

    trace = TraceEntry(
        stage="coverage_calculation",
        component="RulesEngine.coverage_calculator",
        status=TraceStatus.PASS,
        message=" ".join(parts),
        details=breakdown,
    )

    return round(approved_amount, 2), breakdown, trace