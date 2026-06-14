import pytest
from app.policy_loader import load_policy
from app.rules_engine.waiting_periods import check_waiting_period, match_specific_condition
from app.models.decision import TraceStatus


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def test_tc005_diabetes_within_waiting_period(policy):
    """EMP005 (Vikram Joshi) joined 2024-09-01, diabetes WP is 90 days.
    Treatment on 2024-10-15 is 44 days after joining -> within WP."""
    member = policy.get_member("EMP005")
    entry = check_waiting_period(member, policy, "2024-10-15", "Type 2 Diabetes Mellitus")

    assert entry.status == TraceStatus.FAIL
    assert entry.details["condition"] == "diabetes"
    assert entry.details["required_days"] == 90
    assert "eligible" in entry.message.lower()
    # must state the date from which member becomes eligible
    assert entry.details["eligible_from"] == "2024-11-30"


def test_match_specific_condition_keywords():
    assert match_specific_condition("Type 2 Diabetes Mellitus") == "diabetes"
    assert match_specific_condition("T2DM") == "diabetes"
    assert match_specific_condition("HTN") == "hypertension"
    assert match_specific_condition("Viral Fever") is None


def test_no_waiting_period_for_long_standing_member(policy):
    """EMP001 joined 2024-04-01, treatment 2024-11-01 -> well past general WP, no condition match."""
    member = policy.get_member("EMP001")
    entry = check_waiting_period(member, policy, "2024-11-01", "Viral Fever")
    assert entry.status == TraceStatus.PASS


def test_general_waiting_period_blocks_recent_joiner(policy):
    """A member who joined < 30 days before treatment is blocked by the general WP."""
    member = policy.get_member("EMP005")  # joined 2024-09-01
    entry = check_waiting_period(member, policy, "2024-09-15", "Viral Fever")  # 14 days
    assert entry.status == TraceStatus.FAIL
    assert entry.details["rule"] == "initial_waiting_period"
    assert entry.details["eligible_from"] == "2024-10-01"


def test_dependent_uses_primary_member_join_date(policy):
    """DEP002 (child of EMP001) has no own join_date; should use EMP001's."""
    member = policy.get_member("DEP002")
    entry = check_waiting_period(member, policy, "2024-11-01", "Viral Fever")
    assert entry.status == TraceStatus.PASS
    assert entry.details["join_date"] == "2024-04-01"