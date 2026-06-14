import pytest
from app.policy_loader import load_policy
from app.rules_engine.coverage_calculator import calculate_coverage


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def test_tc004_consultation_copay_only(policy):
    """₹1500 consultation, no network discount (not a network hospital),
    10% co-pay -> ₹1350 approved."""
    approved, breakdown, trace = calculate_coverage(
        base_amount=1500,
        category="CONSULTATION",
        is_network_hospital=False,
        policy=policy,
    )
    assert approved == 1350
    assert breakdown["network_discount_percent"] == 0
    assert breakdown["copay_amount"] == 150


def test_tc010_network_discount_before_copay(policy):
    """₹4500 at Apollo (network), 20% discount then 10% copay -> ₹3240.
    Discount first: 4500 -> 3600. Copay 10% of 3600 = 360 -> 3240."""
    approved, breakdown, trace = calculate_coverage(
        base_amount=4500,
        category="CONSULTATION",
        is_network_hospital=True,
        policy=policy,
    )
    assert breakdown["amount_after_discount"] == 3600
    assert breakdown["copay_amount"] == 360
    assert approved == 3240


def test_cap_applied_when_headroom_low(policy):
    approved, breakdown, trace = calculate_coverage(
        base_amount=1500,
        category="CONSULTATION",
        is_network_hospital=False,
        policy=policy,
        cap=1000,
    )
    assert approved == 1000
    assert breakdown["cap_applied"] is True


def test_dental_no_discount_no_copay(policy):
    approved, breakdown, trace = calculate_coverage(
        base_amount=8000,
        category="DENTAL",
        is_network_hospital=False,
        policy=policy,
    )
    assert approved == 8000