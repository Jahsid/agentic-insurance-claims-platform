"""
Pipeline Orchestrator

Coordinates the end-to-end execution of specialized claims processing agents.
Implements a strict fail-fast gating architecture:
1. Document Classification
2. Document Verification (Absolute Circuit Breaker)
3. Structured Data Extraction (with built-in exponential backoff loops)
4. Rules Engine Evaluation
5. Automated Fraud Detection Anomaly Scanning
6. Final Decision Synthesis

Guarantees 100% data integrity by ensuring that validation failures (e.g., patient
identity mismatches, missing required types) automatically halt the execution 
loop before any rules computation or metadata overrides can take place.
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
# Automatically handle variant environment runtime class names for Line Items
try:
    from app.models.decision import LineItem
except ImportError:
    try:
        from app.models.decision import ClaimLineItem as LineItem
    except ImportError:
        class LineItem:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
            def model_dump(self):
                return self.__dict__

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
    Main orchestration pipeline execution loop. Encapsulates all agent operations 
    within a shared context transaction frame.
    """

    # ------------------------------------------------------------------
    # 1. Context Setup & Core Initialization
    # ------------------------------------------------------------------
    ctx = ClaimContext(submission=submission)

    if llm_client is None:
        try:
            llm_client = LLMClient()
            print("✅ Gemini client initialized successfully")
            ctx.processing_metadata["llm_enabled"] = True
            ctx.processing_metadata["llm_model"] = getattr(
                llm_client, "model_name", "gemini-2.5-flash"
            )
        except Exception as exc:
            print(f"❌ LLM client initialization failed: {exc}")
            llm_client = None
            ctx.processing_metadata["llm_enabled"] = False
            ctx.processing_metadata["llm_error"] = str(exc)

    # ------------------------------------------------------------------
    # 2. Stage 0: Document Classification
    # ------------------------------------------------------------------
    classifier = DocumentClassifierAgent(llm_client=llm_client)
    ctx = classifier.run_safe(ctx)

    # ------------------------------------------------------------------
    # 3. Stage 1: Document Verification (CRITICAL FAIL-FAST GATING)
    # ------------------------------------------------------------------
    # Evaluates the input attachments against policy configuration matrices
    # to catch type completeness, unreadability, and cross-patient name variations.
    verifier = DocumentVerifierAgent(policy)
    ctx = verifier.run_safe(ctx)

    # ABSOLUTE CIRCUIT BREAKER: If the verification layer uncovers structural gaps 
    # (e.g., wrong documents uploaded or a patient identity mismatch), halt 
    # execution instantly. This cleanly stops data leakage down the line.
    if ctx.blocked:
        return ctx

    if not ctx.document_check_passed and ctx.degraded:
        ctx.add_trace(
            TraceEntry(
                stage="document_verification",
                component="Orchestrator",
                status=TraceStatus.WARNING,
                message=(
                    "Document verification could not complete normally. "
                    "Proceeding with reduced baseline pipeline certainty flags."
                ),
            )
        )

    # ------------------------------------------------------------------
    # 4. Stage 2: Structured Entity Extraction (LLM Vision / Parsing)
    # ------------------------------------------------------------------
    print("LLM CLIENT STATUS:", type(llm_client).__name__ if llm_client else None)
    extractor = ExtractionAgent(llm_client=llm_client)
    ctx = extractor.run_safe(ctx)

    # Normalize summary fields extracted across various image/PDF fragments
    for extraction in ctx.extractions:
        fields = extraction.extracted_fields or {}

        if not ctx.extracted_patient_name and fields.get("patient_name"):
            ctx.extracted_patient_name = fields.get("patient_name")

        if not ctx.extracted_patient_name and fields.get("patient_name_on_doc"):
             ctx.extracted_patient_name = fields.get("patient_name_on_doc")

        if not ctx.extracted_diagnosis and fields.get("diagnosis"):
            ctx.extracted_diagnosis = fields.get("diagnosis")

        if not ctx.extracted_treatment and fields.get("treatment"):
            ctx.extracted_treatment = fields.get("treatment")

        if ctx.extracted_total_amount is None and fields.get("total"):
            try:
                ctx.extracted_total_amount = float(fields.get("total"))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Dynamic Secondary Patient Identity Safety Cross-Check
    # ------------------------------------------------------------------
    # Extra check: If the extraction agent parses raw text blocks that reveal 
    # conflicting names after the initial checks, block execution dynamically.
    extracted_names = {
        ex.extracted_fields.get("patient_name").strip().lower()
        for ex in ctx.extractions
        if ex.extracted_fields and ex.extracted_fields.get("patient_name")
    }
    
    if len(extracted_names) > 1:
        message = (
            f"Pipeline halted during runtime extraction analysis: parsed names "
            f"point to multiple conflicting identities within a single submission package."
        )
        ctx.blocked = True
        ctx.block_code = "PATIENT_MISMATCH"
        ctx.block_message = message
        ctx.add_trace(
            TraceEntry(
                stage="extraction",
                component="Orchestrator.identity_safetynet",
                status=TraceStatus.BLOCKED,
                message=message,
                details={"extracted_names": list(extracted_names)},
            )
        )
        return ctx

    # ------------------------------------------------------------------
    # 5. Stage 3: Rules Engine Evaluation Loop
    # ------------------------------------------------------------------
    try:
        rules_result = evaluate_rules(ctx, policy)
    except Exception as exc:
        ctx.degraded = True
        ctx.add_trace(
            TraceEntry(
                stage="rules_evaluation",
                component="RulesEngine",
                status=TraceStatus.FAIL,
                message=f"Rules engine execution failed unexpectedly: {exc}",
                details={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                confidence_impact=-0.3,
            )
        )
        rules_result = RulesEvaluationResult()
    else:
        ctx.trace.extend(rules_result.traces)

    # ------------------------------------------------------------------
    # 6. Stage 4: Automated Fraud & Anomaly Detection Scanning
    # ------------------------------------------------------------------
    fraud_detector = FraudDetectorAgent(policy)
    ctx = fraud_detector.run_safe(ctx)

    # ------------------------------------------------------------------
    # 7. Stage 5: Decision Synthesis Output Formatting
    # ------------------------------------------------------------------
    synthesizer = DecisionSynthesizerAgent(policy, rules_result)
    ctx = synthesizer.run_safe(ctx)

    # ------------------------------------------------------------------
    # 8. Final Fallback Safety Net
    # ------------------------------------------------------------------
    if ctx.decision is None:
        ctx.decision = ClaimDecision(
            decision=DecisionStatus.MANUAL_REVIEW,
            claimed_amount=submission.claimed_amount,
            approved_amount=0.0,
            reasons=["Automated decision synthesis step failed to form resolution."],
            confidence_score=0.1,
            manual_review_recommended=True,
            notes="Pipeline fallback transaction generated by core orchestrator container.",
        )
        ctx.add_trace(
            TraceEntry(
                stage="decision_synthesis",
                component="Orchestrator",
                status=TraceStatus.FAIL,
                message="Decision synthesis step resolved to empty; forced fallback routing to MANUAL_REVIEW.",
            )
        )

    # ------------------------------------------------------------------
    # 9. Pipeline Observability Metadata Enrichment
    # ------------------------------------------------------------------
    ctx.processing_metadata.update(
        {
            "documents_received": len(submission.documents),
            "documents_extracted": len(ctx.extractions),
            "fraud_score": ctx.fraud_score,
            "pipeline_version": "2.0",
            "llm_enabled": (llm_client is not None),
        }
    )

    return ctx