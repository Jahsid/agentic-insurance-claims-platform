"""
ClaimSubmission: POST /claims input contract.

Supports:

1. Evaluation Mode
   - test_cases.json
   - structured content supplied directly

2. Production Mode
   - uploaded PDFs/images
   - Gemini Vision extraction
   - OCR processing
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.models.documents import (
    UploadedDocument,
    DocumentExtractionResult,
)
from app.models.decision import (
    ClaimDecision,
    TraceEntry,
)


# ============================================================================
# Claim History
# ============================================================================


class ClaimHistoryEntry(BaseModel):
    claim_id: str
    date: str
    amount: float
    provider: Optional[str] = None


# ============================================================================
# Claim Submission
# ============================================================================


class ClaimSubmission(BaseModel):
    """
    API input contract.

    POST /claims
    """

    member_id: str

    policy_id: str

    claim_category: str

    treatment_date: str

    claimed_amount: float

    hospital_name: Optional[str] = None

    diagnosis: Optional[str] = None

    treatment_description: Optional[str] = None

    pre_auth_reference: Optional[str] = None

    ytd_claims_amount: float = 0

    claims_history: list[
        ClaimHistoryEntry
    ] = Field(default_factory=list)

    documents: list[
        UploadedDocument
    ] = Field(default_factory=list)

    simulate_component_failure: bool = False


# ============================================================================
# Shared Pipeline Context
# ============================================================================


class ClaimContext(BaseModel):
    """
    Shared mutable pipeline state.
    """

    submission: ClaimSubmission

    # ------------------------------------------------------------------
    # Document Verification
    # ------------------------------------------------------------------

    document_check_passed: bool = False

    blocked: bool = False

    block_message: Optional[str] = None

    block_code: Optional[str] = None

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    classified_documents: dict = Field(
        default_factory=dict
    )

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    extractions: list[
        DocumentExtractionResult
    ] = Field(default_factory=list)

    extracted_patient_name: Optional[str] = None

    extracted_diagnosis: Optional[str] = None

    extracted_treatment: Optional[str] = None

    extracted_total_amount: Optional[float] = None

    # ------------------------------------------------------------------
    # Fraud
    # ------------------------------------------------------------------

    fraud_score: float = 0.0

    fraud_signals: list[str] = Field(
        default_factory=list
    )

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------

    decision: Optional[
        ClaimDecision
    ] = None

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    trace: list[
        TraceEntry
    ] = Field(default_factory=list)

    degraded: bool = False

    processing_metadata: dict = Field(
        default_factory=dict
    )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def add_trace(
        self,
        entry: TraceEntry,
    ) -> None:
        self.trace.append(entry)