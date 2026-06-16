from __future__ import annotations

from app.agents.base import BaseAgent, AgentError
from app.models.claim import ClaimContext
from app.models.documents import DocumentType
from app.models.decision import TraceEntry, TraceStatus


class DocumentClassificationError(AgentError):
    pass


class DocumentClassifierAgent(BaseAgent):
    """
    Stage 1:
        Document Classification

    Responsibilities:
    - Detect document type
    - Populate ctx.classified_documents
    - Support evaluation mode
    - Support future Gemini Vision classification
    """

    name = "DocumentClassifierAgent"
    stage = "document_classification"

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def run(self, ctx: ClaimContext) -> ClaimContext:

        classified = []
        unknown = []

        classification_results = {}

        for doc in ctx.submission.documents:

            # --------------------------------------------------
            # Evaluation mode:
            # actual_type already supplied
            # --------------------------------------------------

            if doc.actual_type:

                classification_results[doc.file_id] = {
                    "predicted_type": doc.actual_type.value,
                    "confidence": 1.0,
                    "source": "provided",
                }

                classified.append(
                    {
                        "file_id": doc.file_id,
                        "type": doc.actual_type.value,
                        "source": "provided",
                    }
                )

                continue

            try:

                predicted_type = self._classify_document(doc)

                doc.actual_type = predicted_type

                classification_results[doc.file_id] = {
                    "predicted_type": predicted_type.value,
                    "confidence": 0.90,
                    "source": "classifier",
                }

                classified.append(
                    {
                        "file_id": doc.file_id,
                        "type": predicted_type.value,
                        "source": "classifier",
                    }
                )

            except Exception as exc:

                doc.actual_type = DocumentType.UNKNOWN

                classification_results[doc.file_id] = {
                    "predicted_type": DocumentType.UNKNOWN.value,
                    "confidence": 0.0,
                    "source": "fallback",
                    "error": str(exc),
                }

                unknown.append(doc.file_id)

                ctx.add_trace(
                    TraceEntry(
                        stage=self.stage,
                        component=self.name,
                        status=TraceStatus.WARNING,
                        message=(
                            f"Failed to classify document "
                            f"{doc.file_id}: {str(exc)}"
                        ),
                        details={
                            "file_id": doc.file_id,
                            "error": str(exc),
                        },
                        confidence_impact=-0.05,
                    )
                )

        # --------------------------------------------------
        # Save results for API response
        # --------------------------------------------------

        ctx.classified_documents = classification_results

        # --------------------------------------------------
        # Metadata
        # --------------------------------------------------

        ctx.processing_metadata.update(
            {
                "documents_received": len(
                    ctx.submission.documents
                ),
                "documents_classified": len(
                    classified
                ),
                "documents_unknown": len(
                    unknown
                ),
                "classification_engine": (
                    "gemini"
                    if self.llm_client
                    else "rule_based"
                ),
            }
        )

        # --------------------------------------------------
        # Trace
        # --------------------------------------------------

        if unknown:

            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.WARNING,
                    message=(
                        f"{len(unknown)} document(s) "
                        f"could not be classified."
                    ),
                    details={
                        "unknown_documents": unknown,
                        "classified_documents": classified,
                    },
                    confidence_impact=-0.05 * len(unknown),
                )
            )

        else:

            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.PASS,
                    message=(
                        f"Successfully classified "
                        f"{len(classified)} document(s)."
                    ),
                    details={
                        "classified_documents": classified,
                    },
                    confidence_impact=0.0,
                )
            )

        return ctx

    def _classify_document(
        self,
        doc,
    ) -> DocumentType:
        """
        Classification priority:

        1. Filename heuristics
        2. Content heuristics
        3. Gemini Vision
        4. UNKNOWN
        """

        file_name = (
            doc.file_name or ""
        ).lower()

        # ------------------------------------------
        # Filename heuristics
        # ------------------------------------------

        if "bill" in file_name:
            return DocumentType.HOSPITAL_BILL

        if "invoice" in file_name:
            return DocumentType.HOSPITAL_BILL

        if "prescription" in file_name:
            return DocumentType.PRESCRIPTION

        if "lab" in file_name:
            return DocumentType.LAB_REPORT

        if "report" in file_name:
            return DocumentType.LAB_REPORT

        if "discharge" in file_name:
            return DocumentType.DISCHARGE_SUMMARY

        # ------------------------------------------
        # Content heuristics
        # ------------------------------------------

        if getattr(doc, "content", None):

            text_blob = str(
                doc.content
            ).lower()

            if "diagnosis" in text_blob:
                return DocumentType.PRESCRIPTION

            if "doctor" in text_blob:
                return DocumentType.PRESCRIPTION

            if "test_result" in text_blob:
                return DocumentType.LAB_REPORT

            if "hospital_name" in text_blob:
                return DocumentType.HOSPITAL_BILL

            if "admission_date" in text_blob:
                return (
                    DocumentType.DISCHARGE_SUMMARY
                )

        # ------------------------------------------
        # Gemini Vision
        # ------------------------------------------

        if self.llm_client:

            try:

                prediction = (
                    self.llm_client
                    .classify_document(doc)
                )

                return DocumentType(
                    prediction
                )

            except Exception:
                pass

        return DocumentType.UNKNOWN
