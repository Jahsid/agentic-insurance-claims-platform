# backend/app/agents/extractor.py
"""
ExtractionAgent

For each uploaded document, produces a DocumentExtractionResult with
structured fields, a confidence score, and quality flags.

Two extraction paths:
1. PASSTHROUGH (used by the eval harness / test_cases.json)
2. LLM EXTRACTION (real path with built-in 503 resilience backoff)
"""

from __future__ import annotations

import time
import logging

# 1. FIX: Restore missing base class dependency imports
from app.agents.base import BaseAgent, AgentError
from app.models.claim import ClaimContext
from app.models.documents import (
    DocumentExtractionResult,
    DocumentQuality,
    DocumentType,
)
from app.models.decision import TraceEntry, TraceStatus
from app.utils.confidence import (
    calculate_document_confidence,
)

logger = logging.getLogger(__name__)


class ExtractionAgentError(AgentError):
    pass


class ExtractionAgent(BaseAgent):
    name = "ExtractionAgent"
    stage = "extraction"

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def run(self, ctx: ClaimContext) -> ClaimContext:
        sub = ctx.submission

        if sub.simulate_component_failure:
            raise ExtractionAgentError(
                "Simulated extraction service failure "
                "(timeout connecting to vision LLM)."
            )

        results: list[DocumentExtractionResult] = []

        for doc in sub.documents:
            if doc.content is not None:
                results.append(
                    self._passthrough(doc)
                )
            else:
                results.append(
                    self._extract_with_llm(doc)
                )

        ctx.extractions = results

        n_failed = sum(
            1
            for r in results
            if r.extraction_status == "FAILED"
        )

        n_partial = sum(
            1
            for r in results
            if r.extraction_status == "PARTIAL"
        )

        document_summary = [
            {
                "file_id": r.file_id,
                "document_type": r.document_type.value,
                "confidence": r.confidence,
                "status": r.extraction_status,
                "error": r.error,
                "quality_flags": r.quality_flags,
            }
            for r in results
        ]

        if n_failed:
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.WARNING,
                    message=(
                        f"{n_failed} of {len(results)} "
                        f"document(s) failed extraction "
                        f"and were skipped. "
                        f"Decision will proceed with "
                        f"reduced confidence."
                    ),
                    details={
                        "documents": document_summary,
                        "failed_file_ids": [
                            r.file_id
                            for r in results
                            if r.extraction_status == "FAILED"
                        ],
                    },
                    confidence_impact=-0.15 * n_failed,
                )
            )

        elif n_partial:
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.WARNING,
                    message=(
                        f"{n_partial} of {len(results)} "
                        f"document(s) partially extracted "
                        f"(some fields unreadable)."
                    ),
                    details={
                        "documents": document_summary,
                        "partial_file_ids": [
                            r.file_id
                            for r in results
                            if r.extraction_status == "PARTIAL"
                        ],
                    },
                    confidence_impact=-0.05 * n_partial,
                )
            )

        else:
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.PASS,
                    message=(
                        f"All {len(results)} document(s) "
                        f"extracted successfully."
                    ),
                    details={
                        "documents": document_summary,
                    },
                )
            )

        return ctx

    def _passthrough(
        self,
        doc,
    ) -> DocumentExtractionResult:
        doc_type = (
            doc.actual_type
            or DocumentType.UNKNOWN
        )

        quality_flags = []
        status = "OK"

        if doc.quality == DocumentQuality.PARTIAL:
            quality_flags.append(
                "PARTIAL_QUALITY"
            )
            status = "PARTIAL"

        confidence = (
            calculate_document_confidence(
                extraction_confidence=0.95,
                quality_flags=quality_flags,
                extraction_status=status,
            )
        )

        return DocumentExtractionResult(
            file_id=doc.file_id,
            document_type=doc_type,
            extracted_fields=doc.content or {},
            confidence=confidence,
            quality_flags=quality_flags,
            extraction_status=status,
        )

    def _extract_with_llm(
        self,
        doc,
    ) -> DocumentExtractionResult:
        """
        Real extraction path with built-in exponential backoff.
        """
        doc_type = (
            doc.actual_type
            or DocumentType.UNKNOWN
        )

        # --------------------------------------------------
        # No LLM configured
        # --------------------------------------------------
        if self.llm_client is None:
            return DocumentExtractionResult(
                file_id=doc.file_id,
                document_type=doc_type,
                extracted_fields={},
                confidence=0.0,
                quality_flags=["NO_LLM_CLIENT_CONFIGURED"],
                extraction_status="FAILED",
                error="No LLM client configured for live extraction.",
            )

        # --------------------------------------------------
        # Missing uploaded file
        # --------------------------------------------------
        if not getattr(doc, "file_path", None):
            return DocumentExtractionResult(
                file_id=doc.file_id,
                document_type=doc_type,
                extracted_fields={},
                confidence=0.0,
                quality_flags=["FILE_PATH_MISSING"],
                extraction_status="FAILED",
                error="Document does not contain a valid file_path.",
            )

        # --------------------------------------------------
        # Extraction Execution Loop with Exponential Backoff
        # --------------------------------------------------
        max_retries = 3
        initial_delay = 2.0  # seconds
        delay = initial_delay
        extracted = {}

        for attempt in range(max_retries):
            try:
                extracted = self.llm_client.extract_document(doc)

                is_failed = extracted.get("status") == "FAILED"
                err_msg = str(extracted.get("error", ""))
                
                # Catch 503 errors to trigger a retry
                if is_failed and ("503" in err_msg or "UNAVAILABLE" in err_msg.upper()):
                    raise Exception(f"Gemini Server Unavailable: {err_msg}")

                break

            except Exception as exc:
                if attempt == max_retries - 1:
                    logger.error(f"Final extraction attempt failed for file {doc.file_id}: {exc}")
                    return DocumentExtractionResult(
                        file_id=doc.file_id,
                        document_type=doc_type,
                        extracted_fields={},
                        confidence=0.0,
                        quality_flags=["EXTRACTION_EXCEPTION"],
                        extraction_status="FAILED",
                        error=f"All retry attempts exhausted. {type(exc).__name__}: {str(exc)}",
                    )

                logger.warning(
                    f"ExtractionAgent hit a temporary API spike on file {doc.file_id} "
                    f"(Attempt {attempt + 1}/{max_retries}). Retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2

        # --------------------------------------------------
        # Final Payload Mapping & Response Creation
        # --------------------------------------------------
        if extracted.get("status") == "FAILED":
            return DocumentExtractionResult(
                file_id=doc.file_id,
                document_type=doc_type,
                extracted_fields={},
                confidence=0.0,
                quality_flags=extracted.get("quality_flags", ["EXTRACTION_FAILED"]),
                extraction_status="FAILED",
                error=extracted.get("error", "Unknown extraction error."),
            )

        confidence = float(extracted.get("confidence", 0.0))

        return DocumentExtractionResult(
            file_id=doc.file_id,
            document_type=doc_type,
            extracted_fields=extracted.get("fields", {}),
            confidence=confidence,
            quality_flags=extracted.get("quality_flags", []),
            extraction_status=extracted.get("status", "OK"),
            error=extracted.get("error"),
        )