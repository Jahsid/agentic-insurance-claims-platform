"""
Confidence scoring utilities.

Purpose
-------
Generate explainable confidence scores for claim decisions.

Confidence is influenced by:
1. Document extraction quality
2. Failed extraction count
3. Pipeline degraded state
4. Fraud risk
5. Missing information

All scores are normalized to [0.0, 1.0].

This is intentionally deterministic and explainable: every deduction is a
fixed, named penalty applied to a clear starting point (1.0, or the
average per-document extraction confidence), rather than an accumulation
of ad-hoc deltas scattered across pipeline stages.

This module is the single source of truth for confidence scoring.
DecisionSynthesizerAgent calls calculate_pipeline_confidence() rather
than computing its own formula, and routes_claims.py calls it directly
for blocked claims (which never reach the synthesizer).
"""
from __future__ import annotations

from app.models.claim import ClaimContext


def clamp(value: float) -> float:
    """
    Keep score between 0 and 1.
    """
    return max(0.0, min(1.0, value))


def calculate_document_confidence(
    extraction_confidence: float,
    quality_flags: list[str] | None = None,
    extraction_status: str = "OK",
) -> float:
    """
    Confidence for a single document.

    Examples:
        Good extraction -> 0.95
        Partial extraction -> 0.70
        Failed extraction -> 0.0
    """
    if extraction_status == "FAILED":
        return 0.0

    score = extraction_confidence
    quality_flags = quality_flags or []

    if "PARTIAL_QUALITY" in quality_flags:
        score -= 0.20

    if "EXTRACTION_FAILED" in quality_flags:
        score -= 0.50

    return clamp(score)


def calculate_pipeline_confidence(
    ctx: ClaimContext,
) -> float:
    """
    Overall confidence for the claim.

    Factors:
        - Average extraction confidence
        - Pipeline degradation
        - Fraud risk
        - Blocked state

    Starting point:
        - 1.0 if at least one document was extracted (then replaced by
          the average extraction confidence across documents)
        - 1.0 - 0.30 = 0.70 if no documents were extracted at all
          (e.g. a blocked claim that never reached extraction)

    Penalties (applied in order, all additive deductions from the
    starting score above):
        - -0.10 per document with extraction_status == "FAILED"
        - -0.20 if the pipeline is in a degraded state (any component
          failed and was skipped)
        - -(fraud_score * 0.20) for fraud/anomaly risk
        - capped at 0.40 if the claim is blocked (document verification
          stopped the pipeline before a decision could be made)
    """
    score = 1.0

    # --------------------------------------------------
    # Extraction quality
    # --------------------------------------------------
    if ctx.extractions:
        avg_extraction_confidence = (
            sum(e.confidence for e in ctx.extractions)
            / len(ctx.extractions)
        )
        score = avg_extraction_confidence

        failed_docs = sum(
            1
            for e in ctx.extractions
            if e.extraction_status == "FAILED"
        )
        score -= failed_docs * 0.10
    else:
        score -= 0.30

    # --------------------------------------------------
    # Pipeline degraded
    # --------------------------------------------------
    if ctx.degraded:
        score -= 0.20

    # --------------------------------------------------
    # Fraud uncertainty
    # --------------------------------------------------
    if ctx.fraud_score is not None:
        # Higher fraud score -> lower confidence
        score -= ctx.fraud_score * 0.20

    # --------------------------------------------------
    # Blocked claims
    # --------------------------------------------------
    if ctx.blocked:
        score = min(score, 0.40)

    return clamp(score)