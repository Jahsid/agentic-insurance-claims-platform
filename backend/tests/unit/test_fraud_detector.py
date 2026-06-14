import pytest
from app.policy_loader import load_policy
from app.agents.fraud_detector import FraudDetectorAgent
from app.models.claim import ClaimContext, ClaimSubmission, ClaimHistoryEntry
from app.models.documents import UploadedDocument, DocumentType


@pytest.fixture(scope="module")
def policy():
    return load_policy()


@pytest.fixture
def agent(policy):
    return FraudDetectorAgent(policy)


def test_tc009_same_day_claims_flagged(agent):
    """EMP008 already has 3 claims on 2024-10-30; this is the 4th.
    same_day_claims_limit is 2 -> 4 > 2 -> signal triggered."""
    sub = ClaimSubmission(
        member_id="EMP008",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-10-30",
        claimed_amount=4800,
        claims_history=[
            ClaimHistoryEntry(claim_id="CLM_0081", date="2024-10-30", amount=1200, provider="City Clinic A"),
            ClaimHistoryEntry(claim_id="CLM_0082", date="2024-10-30", amount=1800, provider="City Clinic B"),
            ClaimHistoryEntry(claim_id="CLM_0083", date="2024-10-30", amount=2100, provider="Wellness Center"),
        ],
        documents=[
            UploadedDocument(file_id="F017", actual_type=DocumentType.PRESCRIPTION),
            UploadedDocument(file_id="F018", actual_type=DocumentType.HOSPITAL_BILL),
        ],
    )
    ctx = agent.run_safe(ClaimContext(submission=sub))

    assert ctx.fraud_score > 0
    assert len(ctx.fraud_signals) >= 1
    assert any("4 claims" in s for s in ctx.fraud_signals)


def test_no_signals_for_normal_claim(agent):
    sub = ClaimSubmission(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=[],
    )
    ctx = agent.run_safe(ClaimContext(submission=sub))
    assert ctx.fraud_score == 0
    assert ctx.fraud_signals == []


def test_high_value_claim_flagged(agent):
    sub = ClaimSubmission(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="DIAGNOSTIC",
        treatment_date="2024-11-01",
        claimed_amount=30000,
        documents=[],
    )
    ctx = agent.run_safe(ClaimContext(submission=sub))
    assert ctx.fraud_score > 0
    assert any("high-value" in s.lower() or "exceeds" in s.lower() for s in ctx.fraud_signals)