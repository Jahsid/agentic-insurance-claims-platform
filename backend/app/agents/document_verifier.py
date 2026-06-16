"""
DocumentVerifierAgent

Runs BEFORE any execution or decisioning logic. Performs three checks, in order:

1. READABILITY CHECK (TC002): If any document is flagged UNREADABLE,
   stop and ask the member to re-upload that *specific* document —
   do not reject the whole claim outright.

2. TYPE CHECK (TC001): Are the required document types for this
   claim_category present among the uploaded documents? If a required
   type is missing, but the member uploaded something else instead
   (e.g. two prescriptions when a hospital bill was required), the
   message must name both what was uploaded and what is still needed.

3. PATIENT IDENTITY CHECK (TC003): If multiple documents carry a
   `patient_name_on_doc` (or raw extracted patient name fields) and they disagree,
   stop, block processing immediately, and surface the names found across documents.

Any failure here sets ctx.blocked = True, ctx.block_code, and
ctx.block_message, guaranteeing that downstream engine adjustments are skipped.
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

        # --- 1. Readability Check (TC002) -------------------------------------
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

        # --- 2. Required Document Type Check (TC001) ---------------------------
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

        # --- 3. Patient Identity Consistency Check (TC003) ----------------------
        named_docs = []
        
        # Pull names from the pre-declared model tracking records
        for d in sub.documents:
            name_on_doc = getattr(d, "patient_name_on_doc", None) or (d.get("patient_name_on_doc") if isinstance(d, dict) else None)
            if name_on_doc:
                named_docs.append((d.file_id, d.actual_type.value if d.actual_type else "document", name_on_doc))

        # Cross-reference with extractions list if it ran asynchronously or was pre-populated
        if getattr(ctx, "extractions", None):
            for ex in ctx.extractions:
                fields = ex.extracted_fields or {}
                extracted_name = fields.get("patient_name") or fields.get("patient_name_on_doc")
                if extracted_name:
                    # Avoid duplications for the same file ID
                    if not any(item[0] == ex.file_id for item in named_docs):
                        named_docs.append((ex.file_id, ex.document_type.value if ex.document_type else "document", extracted_name))

        # Normalize names (strip whitespace, lowercase) to prevent false mismatches
        distinct_names = {name.strip().lower() for _, _, name in named_docs}
        
        if len(distinct_names) > 1:
            detail_str = "; ".join(
                f"{doc_type} is for {name}" for _, doc_type, name in named_docs
            )
            message = (
                f"The documents you uploaded appear to belong to different people: {detail_str}. "
                f"Claims can only be processed if all documents are for the same patient. "
                f"Please check and re-upload matching documents, or submit a separate claim for the other person."
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

        # --- All Checks Passed Successfully -------------------------------------------
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