"""
Pipeline orchestrator.

run_claim_pipeline(submission: ClaimSubmission, policy: PolicyTerms) -> ClaimContext

Stages, in order:
  0. DocumentClassifierAgent -> infers doc.actual_type for any uploaded
                                document that doesn't already have one
                                (live uploads). Never overwrites a
                                pre-supplied actual_type (eval harness).
  1. DocumentVerifierAgent  -> may set ctx.blocked=True and short-circuit
  2. ExtractionAgent        -> ctx.extractions (may raise -> degraded)
  3. RulesEngine.evaluate() -> RulesEvaluationResult (pure function, not
                                an agent; wrapped in try/except here so a
                                bug in rules logic degrades rather than 500s)
  4. FraudDetectorAgent     -> ctx.fraud_score, ctx.fraud_signals
  5. DecisionSynthesizerAgent -> ctx.decision

If ctx.blocked is set by stage 1, stages 2-5 are skipped entirely and
the orchestrator returns immediately -- per requirement #2 ("the system
must stop immediately").

If any later stage raises unexpectedly (caught by run_safe or the
try/except around RulesEngine.evaluate), the orchestrator still reaches
stage 5, which is responsible for producing a sensible decision (or a
MANUAL_REVIEW fallback if even synthesis fails).
"""
from __future__ import annotations

from app.models.claim import ClaimContext, ClaimSubmission
from app.models.decision import ClaimDecision, DecisionStatus, TraceEntry, TraceStatus
from app.models.policy import PolicyTerms

from app.agents.document_classifier import DocumentClassifierAgent
from app.agents.document_verifier import DocumentVerifierAgent
from app.agents.extractor import ExtractionAgent
from app.agents.fraud_detector import FraudDetectorAgent
from app.agents.decision_synthesizer import DecisionSynthesizerAgent
from app.rules_engine.engine import evaluate as evaluate_rules, RulesEvaluationResult


def run_claim_pipeline(submission: ClaimSubmission, policy: PolicyTerms, llm_client=None) -> ClaimContext:
    ctx = ClaimContext(submission=submission)

    # --- Stage 0: Document classification (infer actual_type for live uploads) ---
    classifier = DocumentClassifierAgent(llm_client=llm_client)
    ctx = classifier.run_safe(ctx)

    # --- Stage 1: Document verification (can short-circuit) -----------------
    doc_verifier = DocumentVerifierAgent(policy)
    ctx = doc_verifier.run_safe(ctx)

    if ctx.blocked:
        return ctx

    if not ctx.document_check_passed and ctx.degraded:
        # DocumentVerifierAgent itself failed unexpectedly (e.g. unknown
        # category). Continue cautiously rather than block the member,
        # but flag heavily for manual review later.
        ctx.add_trace(
            TraceEntry(
                stage="document_verification",
                component="Orchestrator",
                status=TraceStatus.WARNING,
                message=(
                    "Document verification could not complete normally; "
                    "proceeding with reduced confidence and flagging for "
                    "manual review."
                ),
            )
        )

    # --- Stage 2: Extraction --------------------------------------------------
    extractor = ExtractionAgent(llm_client=llm_client)
    ctx = extractor.run_safe(ctx)

    # --- Stage 3: Rules engine (deterministic, pure function) ------------------
    try:
        rules_result = evaluate_rules(ctx, policy)
    except Exception as exc:  # noqa: BLE001
        ctx.degraded = True
        ctx.add_trace(
            TraceEntry(
                stage="rules_evaluation",
                component="RulesEngine",
                status=TraceStatus.FAIL,
                message=(
                    f"Rules engine failed unexpectedly and was skipped: {exc}. "
                    f"Pipeline continued without a coverage calculation."
                ),
                details={"error": str(exc), "error_type": type(exc).__name__},
                confidence_impact=-0.3,
            )
        )
        rules_result = RulesEvaluationResult()
    else:
        ctx.trace.extend(rules_result.traces)

    # --- Stage 4: Fraud detection ----------------------------------------------
    fraud_detector = FraudDetectorAgent(policy)
    ctx = fraud_detector.run_safe(ctx)

    # --- Stage 5: Decision synthesis --------------------------------------------
    synthesizer = DecisionSynthesizerAgent(policy, rules_result)
    ctx = synthesizer.run_safe(ctx)

    if ctx.decision is None:
        # Synthesizer itself failed -- final safety net.
        ctx.decision = ClaimDecision(
            decision=DecisionStatus.MANUAL_REVIEW,
            claimed_amount=submission.claimed_amount,
            approved_amount=0,
            reasons=["Automated decision synthesis failed; routed to manual review."],
            confidence_score=0.1,
            manual_review_recommended=True,
            notes="DecisionSynthesizerAgent failed; see trace for details.",
        )
        ctx.add_trace(
            TraceEntry(
                stage="decision_synthesis",
                component="Orchestrator",
                status=TraceStatus.FAIL,
                message="Decision synthesis failed; returned MANUAL_REVIEW fallback.",
            )
        )

    return ctx