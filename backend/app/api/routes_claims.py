"""
Claims API (Fully Updated for Multi-part Form Data and Real Document Uploads).

Responsibilities:
- Ingest real multipart/form-data file submissions.
- Map binary inputs into the strict UploadedDocument model definition.
- Support production live-extraction pipelines.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, HTTPException, status, File, Form, UploadFile

# FIX: Import the exact class definition your schema file implements
from app.models.claim import ClaimSubmission
from app.models.documents import UploadedDocument 
from app.orchestrator.pipeline import run_claim_pipeline
from app.policy_loader import load_policy
from app.utils.confidence import calculate_pipeline_confidence

logger = logging.getLogger(__name__)

router = APIRouter()

# Temporary in-memory local data storage
CLAIMS_DB: Dict[str, dict] = {}

# Instantiate system rules configurations
policy = load_policy()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def submit_claim(
    # Ingest baseline claim form data parameters
    member_id: str = Form(...),
    policy_id: str = Form(...),
    claim_category: str = Form(...),
    treatment_date: str = Form(...),
    claimed_amount: float = Form(...),
    hospital_name: str = Form(""),
    
    # Ingest real file streams array
    files: List[UploadFile] = File(...),
) -> dict:
    """
    Submit a claim for processing using real multi-part document data.
    """
    claim_id = str(uuid.uuid4())
    logger.info("Processing multipart file claim payload %s", claim_id)

    try:
        processed_documents: List[UploadedDocument] = []
        
        for file in files:
            # Generate clean, unique local system filename path targets
            unique_filename = f"{uuid.uuid4()}_{file.filename}"
            local_storage_path = f"storage/uploads/{unique_filename}"
            
            # Stream payload blocks directly onto the host file environment
            contents = await file.read()
            with open(local_storage_path, "wb") as f:
                f.write(contents)
                
            # Intelligently infer layout categories from standard filename signatures
            inferred_type = "UNKNOWN"
            filename_upper = (file.filename or "").upper()
            if "PRESCRIPTION" in filename_upper:
                inferred_type = "PRESCRIPTION"
            elif "BILL" in filename_upper or "HOSPITAL" in filename_upper:
                inferred_type = "HOSPITAL_BILL"
            
            # Instantiate the exact UploadedDocument Pydantic model contract
            doc_instance = UploadedDocument(
                file_id=str(uuid.uuid4()),
                file_name=file.filename or "uploaded_document.pdf",
                mime_type=file.content_type or "application/pdf",
                file_path=local_storage_path,
                actual_type=inferred_type
            )
            processed_documents.append(doc_instance)

        # Re-pack components directly inside the internal validation body blueprint
        reconstructed_submission = ClaimSubmission(
            member_id=member_id,
            policy_id=policy_id,
            claim_category=claim_category,
            treatment_date=treatment_date,
            claimed_amount=claimed_amount,
            hospital_name=hospital_name,
            documents=processed_documents,
            simulate_component_failure=False # Default standard run profile execution
        )

        # Trigger execution down the backend agent system orchestration pipeline
        ctx = run_claim_pipeline(
            submission=reconstructed_submission,
            policy=policy,
        )

        result = {
            "claim_id": claim_id,
            "submitted_at": datetime.utcnow().isoformat(),
            "decision": ctx.decision.model_dump() if ctx.decision else None,
            "confidence_score": round(calculate_pipeline_confidence(ctx), 2),
            "documents": [doc.model_dump() for doc in reconstructed_submission.documents],
            "classified_documents": ctx.classified_documents,
            "extractions": [ext.model_dump() for ext in ctx.extractions],
            "trace": [trace.model_dump() for trace in ctx.trace],
            "fraud_score": ctx.fraud_score,
            "fraud_signals": ctx.fraud_signals,
            "blocked": ctx.blocked,
            "block_code": ctx.block_code,
            "block_message": ctx.block_message,
            "degraded": ctx.degraded,
            "processing_metadata": ctx.processing_metadata,
        }

        CLAIMS_DB[claim_id] = result
        return result

    except Exception as exc:
        logger.exception("Claim runtime processing failed for target token %s", claim_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline processing execution crash: {str(exc)}",
        ) from exc


# --- Keep standard GET methods active below unchanged ---

@router.get("/{claim_id}")
async def get_claim(claim_id: str) -> dict:
    claim = CLAIMS_DB.get(claim_id)
    if claim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim '{claim_id}' not found",
        )
    return claim


@router.get("")
async def list_claims() -> dict:
    return {
        "count": len(CLAIMS_DB),
        "claims": list(CLAIMS_DB.keys()),
    }