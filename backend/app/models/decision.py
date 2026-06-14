"""
Decision output and the trace entry that makes every decision explainable.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class DecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class TraceStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


class TraceEntry(BaseModel):
    """
    One row in the explainability trace. Every agent / rule check
    appends one (or more) of these. The full list of TraceEntry
    objects, in order, is what the ops team reviews to understand
    "what was checked, what passed, what failed, and why".
    """
    stage: str                       # e.g. "document_verification", "waiting_period_check"
    component: str                   # e.g. "DocumentVerifierAgent", "RulesEngine.waiting_periods"
    status: TraceStatus
    message: str                     # human-readable explanation
    details: dict[str, Any] = Field(default_factory=dict)
    confidence_impact: float = 0.0   # delta applied to overall confidence (can be negative)


class LineItemDecision(BaseModel):
    description: str
    claimed_amount: float
    approved_amount: float
    status: str             # APPROVED | REJECTED
    reason: Optional[str] = None


class ClaimDecision(BaseModel):
    decision: DecisionStatus
    claimed_amount: float
    approved_amount: float = 0
    currency: str = "INR"
    reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)  # machine-readable codes
    line_items: list[LineItemDecision] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.0)
    notes: Optional[str] = None
    manual_review_recommended: bool = False
    breakdown: dict[str, Any] = Field(default_factory=dict)  # discount/copay math etc.