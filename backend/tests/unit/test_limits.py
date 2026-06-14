import pytest
from app.policy_loader import load_policy
from app.rules_engine.limits import check_per_claim_limit, check_category_sub_limit, check_annual_opd_limit
from app.models.decision import TraceStatus


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def test_tc008_per_claim_limit_exceeded(policy):
    """₹7500 claimed > ₹5000 per-claim limit -> FAIL with both values stated."""
    entry = check_per_claim_limit(7500, policy)
    assert entry.status == TraceStatus.FAIL
    assert "5,000" in entry.message or "5000" in entry.message
    assert "7,500" in entry.message or "7500" in entry.message
    assert entry.details["per_claim_limit"] == 5000
    assert entry.details["claimed_amount"] == 7500


def test_within_per_claim_limit(policy):
    entry = check_per_claim_limit(1500, policy)
    assert entry.status == TraceStatus.PASS


def test_category_sub_limit_headroom(policy):
    # consultation sub_limit = 2000, ytd already 5000 (from TC004) -> exhausted
    entry = check_category_sub_limit(1500, ytd_category_amount=2000, category="CONSULTATION", policy=policy)
    assert entry.status == TraceStatus.FAIL
    assert entry.details["remaining_sub_limit_headroom"] == 0


def test_category_sub_limit_partial_headroom(policy):
    entry = check_category_sub_limit(1500, ytd_category_amount=1000, category="CONSULTATION", policy=policy)
    assert entry.status == TraceStatus.WARNING
    assert entry.details["remaining_sub_limit_headroom"] == 1000


def test_annual_opd_limit_sufficient(policy):
    entry = check_annual_opd_limit(1500, ytd_total_amount=5000, policy=policy)
    assert entry.status == TraceStatus.PASS
    assert entry.details["remaining_annual_headroom"] == 45000