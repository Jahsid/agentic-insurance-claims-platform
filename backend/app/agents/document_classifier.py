from __future__ import annotations

from app.agents.base import BaseAgent, AgentError
from app.models.claim import ClaimContext
from app.models.documents import DocumentType
from app.models.decision import TraceEntry, TraceStatus


class DocumentClassificationError(AgentError):
    pass


class DocumentClassifierAgent(BaseAgent):
    """
    Classifies uploaded documents before verification.

    Purpose:
        - Determine actual document type if missing.
        - Support live uploads where users provide arbitrary PDFs/images.
        - Improve document verification quality.

    Safe behavior:
        - If actual_type already exists, do not overwrite it.
        - If classification fails, mark UNKNOWN and continue.

    Component contract
    -------------------
    Input:  ClaimContext.submission.documents (list[UploadedDocument])
    Output: mutates doc.actual_type in place for any document where it
            was previously None. Documents that already carry an
            actual_type (e.g. from the eval harness / test_cases.json,
            which supplies ground-truth types) are left untouched.
    Raises: nothing (BaseAgent.run_safe wraps unexpected errors; internal
            classification failures are caught per-document and mapped
            to DocumentType.UNKNOWN rather than raising).

    Pipeline placement: runs BEFORE DocumentVerifierAgent (stage 0), so
    that the verifier's required-document-type check has a populated
    actual_type to work with even for live uploads where the client did
    not supply one.
    """

    name = "DocumentClassifierAgent"
    stage = "document_classification"

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def run(self, ctx: ClaimContext) -> ClaimContext:

        classified = []
        unknown = []

        for doc in ctx.submission.documents:

            # -------------------------------------------------
            # Keep existing type from test cases / eval harness
            # -------------------------------------------------
            if doc.actual_type:
                classified.append(
                    {
                        "file_id": doc.file_id,
                        "type": doc.actual_type.value,
                        "source": "provided",
                    }
                )
                continue

            try:
                doc.actual_type = self._classify_document(doc)

                classified.append(
                    {
                        "file_id": doc.file_id,
                        "type": doc.actual_type.value,
                        "source": "classifier",
                    }
                )

            except Exception as exc:  # noqa: BLE001

                doc.actual_type = DocumentType.UNKNOWN

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

        # -------------------------------------------------
        # Trace summary
        # -------------------------------------------------

        if unknown:
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.WARNING,
                    message=(
                        f"{len(unknown)} document(s) could not "
                        f"be classified."
                    ),
                    details={
                        "unknown_documents": unknown,
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
                )
            )

        return ctx

    def _classify_document(self, doc) -> DocumentType:
        """
        Classification logic.

        Priority:
        1. Content hints
        2. Filename heuristics
        3. LLM (future)
        """

        file_name = (doc.file_name or "").lower()

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
        # Content hints
        # ------------------------------------------

        if getattr(doc, "content", None):

            text_blob = str(doc.content).lower()

            if "diagnosis" in text_blob:
                return DocumentType.PRESCRIPTION

            if "doctor" in text_blob:
                return DocumentType.PRESCRIPTION

            if "test_result" in text_blob:
                return DocumentType.LAB_REPORT

            if "hospital_name" in text_blob:
                return DocumentType.HOSPITAL_BILL

            if "admission_date" in text_blob:
                return DocumentType.DISCHARGE_SUMMARY

        # ------------------------------------------
        # Future Gemini classification
        # ------------------------------------------

        if self.llm_client:

            try:
                prediction = self.llm_client.classify_document(doc)

                return DocumentType(prediction)

            except Exception:
                pass

        return DocumentType.UNKNOWN