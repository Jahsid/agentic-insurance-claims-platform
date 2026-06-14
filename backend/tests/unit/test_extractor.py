import pytest
from app.agents.extractor import ExtractionAgent
from app.models.claim import ClaimContext, ClaimSubmission
from app.models.documents import UploadedDocument, DocumentType, DocumentQuality


@pytest.fixture
def agent():
    return ExtractionAgent()


def test_passthrough_extraction_with_content(agent):
    sub = ClaimSubmission(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=[
            UploadedDocument(
                file_id="F007",
                actual_type=DocumentType.PRESCRIPTION,
                content={"doctor_name": "Dr. Arun Sharma", "diagnosis": "Viral Fever"},
            )
        ],
    )
    ctx = agent.run_safe(ClaimContext(submission=sub))

    assert len(ctx.extractions) == 1
    result = ctx.extractions[0]
    assert result.extraction_status == "OK"
    assert result.confidence >= 0.9
    assert result.extracted_fields["diagnosis"] == "Viral Fever"
    assert ctx.degraded is False


def test_tc011_simulated_component_failure(agent):
    """simulate_component_failure=True must not crash the pipeline;
    ctx.degraded must be set and confidence reduced via trace."""
    sub = ClaimSubmission(
        member_id="EMP006",
        policy_id="PLUM_GHI_2024",
        claim_category="ALTERNATIVE_MEDICINE",
        treatment_date="2024-10-28",
        claimed_amount=4000,
        simulate_component_failure=True,
        documents=[
            UploadedDocument(file_id="F021", actual_type=DocumentType.PRESCRIPTION, content={"diagnosis": "Chronic Joint Pain"}),
            UploadedDocument(file_id="F022", actual_type=DocumentType.HOSPITAL_BILL, content={"total": 4000}),
        ],
    )
    ctx = agent.run_safe(ClaimContext(submission=sub))

    assert ctx.degraded is True
    assert ctx.extractions == []  # extraction did not complete
    assert any(t.status.value == "FAIL" for t in ctx.trace)
    assert any(t.confidence_impact < 0 for t in ctx.trace)


def test_partial_quality_document_lowers_confidence(agent):
    sub = ClaimSubmission(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=[
            UploadedDocument(
                file_id="F099",
                actual_type=DocumentType.PRESCRIPTION,
                quality=DocumentQuality.PARTIAL,
                content={"doctor_name": None, "diagnosis": "Viral Fever"},
            )
        ],
    )
    ctx = agent.run_safe(ClaimContext(submission=sub))
    result = ctx.extractions[0]
    assert result.extraction_status == "PARTIAL"
    assert result.confidence < 0.9
    assert "PARTIAL_QUALITY" in result.quality_flags