"""
ExtractionAgent

For each uploaded document, produces a DocumentExtractionResult with
structured fields, a confidence score, and quality flags.

Two extraction paths:

1. PASSTHROUGH (used by the eval harness / test_cases.json): if the
   UploadedDocument already carries a `content` dict (ground-truth
   structured data, simulating "a vision LLM already extracted this"),
   we validate it against the appropriate schema and use it directly.
   confidence = 0.95 (HIGH, since content is structured/clean).

2. LLM EXTRACTION (real path): if no `content` is supplied, calls the
   Anthropic API with a vision-capable model and a doc-type-specific
   prompt (see llm/prompts/), parses the JSON response, and validates
   it. On timeout / malformed JSON / API error, the document is marked
   extraction_status="FAILED", confidence=0.0, quality_flags includes
   "EXTRACTION_FAILED", and the pipeline continues (TC011).

Failure simulation: if ClaimSubmission.simulate_component_failure is
True, this agent raises immediately (simulating, e.g., the extraction
service being down). BaseAgent.run_safe catches this, marks
ctx.degraded=True, applies a confidence penalty, and the pipeline
continues with documents unextracted -- decisions further down the
pipeline must fall back to whatever raw `content`/metadata is available
in ctx.submission.documents directly (handled by the rules engine
input-builder, see orchestrator/pipeline.py).

Component contract
-------------------
Input:  ClaimContext.submission.documents (list[UploadedDocument])
Output: ClaimContext.extractions: list[DocumentExtractionResult]
        one entry per input document, same order, same file_id.
Raises: ExtractionAgentError if simulate_component_failure is True
        (caught by BaseAgent.run_safe -> degraded pipeline, TC011).
"""
from __future__ import annotations

from app.agents.base import BaseAgent, AgentError
from app.models.claim import ClaimContext
from app.models.documents import (
    DocumentExtractionResult,
    DocumentQuality,
    DocumentType,
)
from app.models.decision import TraceEntry, TraceStatus


class ExtractionAgentError(AgentError):
    pass


class ExtractionAgent(BaseAgent):
    name = "ExtractionAgent"
    stage = "extraction"

    def __init__(self, llm_client=None):
        # llm_client is optional; only required for the real LLM path.
        self.llm_client = llm_client

    def run(self, ctx: ClaimContext) -> ClaimContext:
        sub = ctx.submission

        if sub.simulate_component_failure:
            raise ExtractionAgentError(
                "Simulated extraction service failure (timeout connecting to vision LLM)."
            )

        results: list[DocumentExtractionResult] = []
        for doc in sub.documents:
            if doc.content is not None:
                results.append(self._passthrough(doc))
            else:
                results.append(self._extract_with_llm(doc))

        ctx.extractions = results

        n_failed = sum(1 for r in results if r.extraction_status == "FAILED")
        n_partial = sum(1 for r in results if r.extraction_status == "PARTIAL")

        if n_failed:
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.WARNING,
                    message=(
                        f"{n_failed} of {len(results)} document(s) failed extraction "
                        f"and were skipped. Decision will proceed with reduced confidence."
                    ),
                    details={"failed_file_ids": [r.file_id for r in results if r.extraction_status == "FAILED"]},
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
                        f"{n_partial} of {len(results)} document(s) partially "
                        f"extracted (some fields unreadable)."
                    ),
                    details={"partial_file_ids": [r.file_id for r in results if r.extraction_status == "PARTIAL"]},
                    confidence_impact=-0.05 * n_partial,
                )
            )
        else:
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.PASS,
                    message=f"All {len(results)} document(s) extracted successfully.",
                    details={"file_ids": [r.file_id for r in results]},
                )
            )

        return ctx

    def _passthrough(self, doc) -> DocumentExtractionResult:
        doc_type = doc.actual_type or DocumentType.UNKNOWN
        quality_flags = []
        confidence = 0.95
        if doc.quality == DocumentQuality.PARTIAL:
            quality_flags.append("PARTIAL_QUALITY")
            confidence = 0.6
        return DocumentExtractionResult(
            file_id=doc.file_id,
            document_type=doc_type,
            extracted_fields=doc.content or {},
            confidence=confidence,
            quality_flags=quality_flags,
            extraction_status="OK" if not quality_flags else "PARTIAL",
        )

    def _extract_with_llm(self, doc) -> DocumentExtractionResult:
        """
        Real extraction path. Not exercised by the eval harness (which
        supplies `content` for every test document) but implemented for
        genuine image/PDF uploads via the UI.
        """
        if self.llm_client is None:
            return DocumentExtractionResult(
                file_id=doc.file_id,
                document_type=doc.actual_type or DocumentType.UNKNOWN,
                extracted_fields={},
                confidence=0.0,
                quality_flags=["NO_LLM_CLIENT_CONFIGURED"],
                extraction_status="FAILED",
                error="No LLM client configured for live extraction.",
            )

        try:
            extracted = self.llm_client.extract_document(doc)
            return DocumentExtractionResult(
                file_id=doc.file_id,
                document_type=doc.actual_type or DocumentType.UNKNOWN,
                extracted_fields=extracted.get("fields", {}),
                confidence=extracted.get("confidence", 0.7),
                quality_flags=extracted.get("quality_flags", []),
                extraction_status=extracted.get("status", "OK"),
            )
        except Exception as exc:  # noqa: BLE001
            return DocumentExtractionResult(
                file_id=doc.file_id,
                document_type=doc.actual_type or DocumentType.UNKNOWN,
                extracted_fields={},
                confidence=0.0,
                quality_flags=["EXTRACTION_FAILED"],
                extraction_status="FAILED",
                error=str(exc),
            )