import pytest
from app.policy_loader import load_policy
from app.rules_engine.exclusions import check_condition_exclusion, check_line_item_exclusions
from app.models.documents import LineItem
from app.models.decision import TraceStatus


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def test_tc012_obesity_excluded(policy):
    """Morbid Obesity / Bariatric Consultation must match the 'Obesity and
    weight loss programs' / 'Bariatric surgery' exclusions."""
    entry = check_condition_exclusion(
        diagnosis_text="Morbid Obesity — BMI 37",
        treatment_text="Bariatric Consultation and Customised Diet Plan",
        policy=policy,
    )
    assert entry.status == TraceStatus.FAIL
    assert "matched_exclusion" in entry.details


def test_viral_fever_not_excluded(policy):
    entry = check_condition_exclusion("Viral Fever", None, policy)
    assert entry.status == TraceStatus.PASS


def test_tc006_dental_line_item_exclusion(policy):
    """Root Canal Treatment is covered, Teeth Whitening is excluded.
    Approved amount should reflect only the covered item."""
    line_items = [
        LineItem(description="Root Canal Treatment", amount=8000),
        LineItem(description="Teeth Whitening", amount=4000),
    ]
    decisions, trace = check_line_item_exclusions(line_items, "DENTAL", policy)

    approved = [d for d in decisions if d.status == "APPROVED"]
    rejected = [d for d in decisions if d.status == "REJECTED"]

    assert len(approved) == 1
    assert approved[0].description == "Root Canal Treatment"
    assert approved[0].approved_amount == 8000

    assert len(rejected) == 1
    assert rejected[0].description == "Teeth Whitening"
    assert rejected[0].approved_amount == 0
    assert rejected[0].reason is not None

    total_approved = sum(d.approved_amount for d in decisions)
    assert total_approved == 8000
    assert trace.status == TraceStatus.WARNING


def test_no_exclusions_for_consultation(policy):
    line_items = [LineItem(description="Consultation Fee", amount=1000)]
    decisions, trace = check_line_item_exclusions(line_items, "CONSULTATION", policy)
    assert all(d.status == "APPROVED" for d in decisions)
    assert trace.status == TraceStatus.PASS