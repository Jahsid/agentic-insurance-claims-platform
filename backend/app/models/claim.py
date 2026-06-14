"""
ClaimSubmission: the input contract for POST /claims.
ClaimContext: the mutable working state passed between pipeline stages.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from app.models.documents import UploadedDocument, DocumentExtractionResult
from app.models.decision import TraceEntry, ClaimDecision


class ClaimHistoryEntry(BaseModel):
    claim_id: str
    date: str
    amount: float
    provider: Optional[str] = None


class ClaimSubmission(BaseModel):
    member_id: str
    policy_id: str
    claim_category: str  # CONSULTATION | DIAGNOSTIC | PHARMACY | DENTAL | VISION | ALTERNATIVE_MEDICINE
    treatment_date: str
    claimed_amount: float
    hospital_name: Optional[str] = None
    ytd_claims_amount: float = 0
    claims_history: list[ClaimHistoryEntry] = Field(default_factory=list)
    documents: list[UploadedDocument] = Field(default_factory=list)

    # Test/debug hook (from test_cases.json TC011): lets us simulate
    # a component failure without needing real infra failure injection.
    simulate_component_failure: bool = False


class ClaimContext(BaseModel):
    """
    Shared mutable state threaded through every pipeline stage.
    Each agent reads what it needs and writes its results back here,
    plus appends a TraceEntry describing what it did.
    """
    submission: ClaimSubmission

    # Populated by Document Verifier
    document_check_passed: bool = False
    blocked: bool = False
    block_message: Optional[str] = None
    block_code: Optional[str] = None

    # Populated by Extraction Agent
    extractions: list[DocumentExtractionResult] = Field(default_factory=list)

    # Populated by Fraud Detector
    fraud_score: float = 0.0
    fraud_signals: list[str] = Field(default_factory=list)

    # Populated by Decision Synthesizer
    decision: Optional[ClaimDecision] = None

    # Observability
    trace: list[TraceEntry] = Field(default_factory=list)
    degraded: bool = False  # set True if any component failed and was skipped

    def add_trace(self, entry: TraceEntry) -> None:
        self.trace.append(entry)