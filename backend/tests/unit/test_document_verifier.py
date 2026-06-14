"""
DocumentVerifierAgent

Runs BEFORE any extraction or decisioning. Performs three checks, in order:

1. TYPE CHECK (TC001): are the required document types for this
   claim_category present among the uploaded documents? If a required
   type is missing, but the member uploaded something else instead
   (e.g. two prescriptions when a hospital bill was required), the
   message must name both what was uploaded and what is still needed.

2. READABILITY CHECK (TC002): if any document is flagged UNREADABLE,
   stop and ask the member to re-upload that *specific* document —
   do not reject the whole claim outright.

3. PATIENT IDENTITY CHECK (TC003): if multiple documents carry a
   `patient_name_on_doc` (or extracted patient_name) and they disagree,
   stop and surface the specific names found on each document.

Any failure here sets ctx.blocked = True, ctx.block_code, and
ctx.block_message, and the orchestrator must not proceed to extraction
or the rules engine.

Component contract
-------------------
Input:  ClaimContext.submission (claim_category, documents[])
        PolicyTerms.document_requirements[claim_category]
Output: ClaimContext with one of:
          - document_check_passed=True, blocked=False
          - blocked=True, block_code in {
                "MISSING_REQUIRED_DOCUMENT",
                "UNREADABLE_DOCUMENT",
                "PATIENT_MISMATCH",
            }, block_message=<specific actionable text>
Raises: DocumentVerificationError on malformed input (e.g. unknown
        claim_category not present in policy.document_requirements).
        This propagates up through BaseAgent.run_safe(), which converts
        it into a degraded trace entry rather than crashing.
"""
from __future__ import annotations

from app.agents.base import BaseAgent, AgentError
from app.models.claim import ClaimContext
from app.models.documents import DocumentQuality
from app.models.decision import TraceEntry, TraceStatus
from app.models.policy import PolicyTerms


class DocumentVerificationError(AgentError):
    pass


class DocumentVerifierAgent(BaseAgent):
    name = "DocumentVerifierAgent"
    stage = "document_verification"

    def __init__(self, policy: PolicyTerms):
        self.policy = policy

    def run(self, ctx: ClaimContext) -> ClaimContext:
        sub = ctx.submission
        category = sub.claim_category.upper()

        requirements = self.policy.get_document_requirements(category)
        if requirements is None:
            raise DocumentVerificationError(
                f"Unknown claim_category '{sub.claim_category}': no document "
                f"requirements configured in policy_terms.json"
            )

        uploaded_types = [
            d.actual_type.value if d.actual_type else "UNKNOWN"
            for d in sub.documents
        ]

        # --- 1. Readability check -------------------------------------
        unreadable = [d for d in sub.documents if d.quality == DocumentQuality.UNREADABLE]
        if unreadable:
            names = ", ".join(d.file_name or d.file_id for d in unreadable)
            types = ", ".join(
                (d.actual_type.value if d.actual_type else "document") for d in unreadable
            )
            message = (
                f"We couldn't read the following file(s): {names} "
                f"(expected: {types}). The image is too blurry or unclear to "
                f"process. Please re-upload a clearer photo or scan of this "
                f"document — the rest of your submission is fine."
            )
            ctx.blocked = True
            ctx.block_code = "UNREADABLE_DOCUMENT"
            ctx.block_message = message
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.BLOCKED,
                    message=message,
                    details={"unreadable_files": [d.file_id for d in unreadable]},
                )
            )
            return ctx

        # --- 2. Required document type check ---------------------------
        missing = [req for req in requirements.required if req not in uploaded_types]
        if missing:
            uploaded_desc = ", ".join(uploaded_types) if uploaded_types else "no documents"
            missing_desc = ", ".join(missing)
            message = (
                f"This {category} claim requires {', '.join(requirements.required)}. "
                f"You uploaded: {uploaded_desc}. "
                f"You are missing: {missing_desc}. "
                f"Please upload {missing_desc} to proceed with this claim."
            )
            ctx.blocked = True
            ctx.block_code = "MISSING_REQUIRED_DOCUMENT"
            ctx.block_message = message
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.BLOCKED,
                    message=message,
                    details={
                        "claim_category": category,
                        "required": requirements.required,
                        "uploaded_types": uploaded_types,
                        "missing": missing,
                    },
                )
            )
            return ctx

        # --- 3. Patient identity consistency check ----------------------
        named_docs = [
            (d.file_id, d.actual_type.value if d.actual_type else "document", d.patient_name_on_doc)
            for d in sub.documents
            if d.patient_name_on_doc
        ]
        distinct_names = {n for _, _, n in named_docs}
        if len(distinct_names) > 1:
            detail_str = "; ".join(
                f"{doc_type} ({file_id}) is for {name}" for file_id, doc_type, name in named_docs
            )
            message = (
                f"The documents you uploaded appear to belong to different people: "
                f"{detail_str}. Claims can only be processed if all documents are for "
                f"the same patient. Please check and re-upload matching documents, or "
                f"submit a separate claim for the other person."
            )
            ctx.blocked = True
            ctx.block_code = "PATIENT_MISMATCH"
            ctx.block_message = message
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.BLOCKED,
                    message=message,
                    details={"documents": named_docs},
                )
            )
            return ctx

        # --- All checks passed -------------------------------------------
        ctx.document_check_passed = True
        ctx.add_trace(
            TraceEntry(
                stage=self.stage,
                component=self.name,
                status=TraceStatus.PASS,
                message=(
                    f"All required documents present for {category} "
                    f"({', '.join(requirements.required)}), all readable, "
                    f"patient identity consistent."
                ),
                details={"required": requirements.required, "uploaded_types": uploaded_types},
            )
        )
        return ctx