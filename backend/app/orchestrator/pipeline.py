"""
Pipeline orchestrator.

Supports:

1. Evaluation Mode
   - test_cases.json
   - actual_type/content supplied directly

2. Production Mode
   - PDF/JPG/PNG upload
   - Gemini Vision extraction
   - OCR
"""

from __future__ import annotations

from app.models.claim import (
    ClaimContext,
    ClaimSubmission,
)
from app.models.decision import (
    ClaimDecision,
    DecisionStatus,
    TraceEntry,
    TraceStatus,
)
from app.models.policy import PolicyTerms

from app.agents.document_classifier import (
    DocumentClassifierAgent,
)
from app.agents.document_verifier import (
    DocumentVerifierAgent,
)
from app.agents.extractor import (
    ExtractionAgent,
)
from app.agents.fraud_detector import (
    FraudDetectorAgent,
)
from app.agents.decision_synthesizer import (
    DecisionSynthesizerAgent,
)

from app.rules_engine.engine import (
    evaluate as evaluate_rules,
    RulesEvaluationResult,
)

from app.llm.client import LLMClient


def run_claim_pipeline(
    submission: ClaimSubmission,
    policy: PolicyTerms,
    llm_client=None,
) -> ClaimContext:
    """
    Main orchestration pipeline.
    """

    # ------------------------------------------------------------------
    # Create shared context
    # ------------------------------------------------------------------

    ctx = ClaimContext(
        submission=submission
    )

    # ------------------------------------------------------------------
    # Production mode:
    # initialize Gemini automatically
    # ------------------------------------------------------------------

    if llm_client is None:
        try:
            llm_client = LLMClient()

            print("✅ Gemini initialized successfully")

            ctx.processing_metadata[
                "llm_enabled"
            ] = True

            ctx.processing_metadata[
                "llm_model"
            ] = getattr(
                llm_client,
                "model_name",
                "unknown",
            )

        except Exception as exc:

            print(
                f"❌ LLM INIT FAILED: {exc}"
            )

            llm_client = None

            ctx.processing_metadata[
                "llm_enabled"
            ] = False

            ctx.processing_metadata[
                "llm_error"
            ] = str(exc)
    # ------------------------------------------------------------------
    # Stage 0
    # Document Classification
    # ------------------------------------------------------------------

    classifier = DocumentClassifierAgent(
        llm_client=llm_client
    )

    ctx = classifier.run_safe(ctx)

    # ------------------------------------------------------------------
    # Stage 1
    # Document Verification
    # ------------------------------------------------------------------

    verifier = DocumentVerifierAgent(
        policy
    )

    ctx = verifier.run_safe(ctx)

    if ctx.blocked:
        return ctx

    if (
        not ctx.document_check_passed
        and ctx.degraded
    ):
        ctx.add_trace(
            TraceEntry(
                stage="document_verification",
                component="Orchestrator",
                status=TraceStatus.WARNING,
                message=(
                    "Document verification could "
                    "not complete normally. "
                    "Proceeding with reduced "
                    "confidence."
                ),
            )
        )

    # ------------------------------------------------------------------
    # Stage 2
    # Extraction (Gemini Vision)
    # ------------------------------------------------------------------

    print(
        "LLM CLIENT:",
        type(llm_client).__name__
        if llm_client
        else None
    )

    extractor = ExtractionAgent(
        llm_client=llm_client
    )

    ctx = extractor.run_safe(ctx)

    # ------------------------------------------------------------------
    # Populate extracted summary fields
    # ------------------------------------------------------------------

    for extraction in ctx.extractions:

        fields = (
            extraction.extracted_fields
            or {}
        )

        if (
            not ctx.extracted_patient_name
            and fields.get("patient_name")
        ):
            ctx.extracted_patient_name = (
                fields.get("patient_name")
            )

        if (
            not ctx.extracted_diagnosis
            and fields.get("diagnosis")
        ):
            ctx.extracted_diagnosis = (
                fields.get("diagnosis")
            )

        if (
            not ctx.extracted_treatment
            and fields.get("treatment")
        ):
            ctx.extracted_treatment = (
                fields.get("treatment")
            )

        if (
            ctx.extracted_total_amount
            is None
            and fields.get("total")
        ):
            try:
                ctx.extracted_total_amount = float(
                    fields.get("total")
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Rules Engine
    # ------------------------------------------------------------------

    try:

        rules_result = evaluate_rules(
            ctx,
            policy,
        )

    except Exception as exc:

        ctx.degraded = True

        ctx.add_trace(
            TraceEntry(
                stage="rules_evaluation",
                component="RulesEngine",
                status=TraceStatus.FAIL,
                message=(
                    "Rules engine failed "
                    f"unexpectedly: {exc}"
                ),
                details={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                confidence_impact=-0.3,
            )
        )

        rules_result = (
            RulesEvaluationResult()
        )

    else:

        ctx.trace.extend(
            rules_result.traces
        )

    # ------------------------------------------------------------------
    # Fraud Detection
    # ------------------------------------------------------------------

    fraud_detector = FraudDetectorAgent(
        policy
    )

    ctx = fraud_detector.run_safe(ctx)

    # ------------------------------------------------------------------
    # Decision Synthesis
    # ------------------------------------------------------------------

    synthesizer = (
        DecisionSynthesizerAgent(
            policy,
            rules_result,
        )
    )

    ctx = synthesizer.run_safe(ctx)

    # ------------------------------------------------------------------
    # Final safety net
    # ------------------------------------------------------------------

    if ctx.decision is None:

        ctx.decision = ClaimDecision(
            decision=DecisionStatus.MANUAL_REVIEW,
            claimed_amount=(
                submission.claimed_amount
            ),
            approved_amount=0,
            reasons=[
                (
                    "Automated decision "
                    "synthesis failed."
                )
            ],
            confidence_score=0.1,
            manual_review_recommended=True,
            notes=(
                "Fallback decision "
                "generated by orchestrator."
            ),
        )

        ctx.add_trace(
            TraceEntry(
                stage="decision_synthesis",
                component="Orchestrator",
                status=TraceStatus.FAIL,
                message=(
                    "Decision synthesis failed; "
                    "returned MANUAL_REVIEW."
                ),
            )
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    ctx.processing_metadata.update(
        {
            "documents_received": len(
                submission.documents
            ),
            "documents_extracted": len(
                ctx.extractions
            ),
            "fraud_score": ctx.fraud_score,
            "pipeline_version": "2.0",
            "llm_enabled": (
                llm_client is not None
            ),
        }
    )

    return ctx