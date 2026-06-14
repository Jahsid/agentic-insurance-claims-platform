"""
Claims API.

Responsibilities:
- Accept claim submissions.
- Invoke orchestration pipeline.
- Return decision + trace.
- Provide claim retrieval endpoint.

Business logic MUST remain inside:
    app.orchestrator.pipeline
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status

from app.models.claim import ClaimSubmission
from app.orchestrator.pipeline import run_claim_pipeline
from app.policy_loader import load_policy

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------
# Temporary in-memory store
#
# Replace with Postgres/Redis repository later.
# ---------------------------------------------------------------------

CLAIMS_DB: Dict[str, dict] = {}

# ---------------------------------------------------------------------
# Load policy once at startup
# ---------------------------------------------------------------------

policy = load_policy()

# ---------------------------------------------------------------------
# POST /claims
# ---------------------------------------------------------------------


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def submit_claim(
    claim: ClaimSubmission,
) -> dict:
    """
    Submit a claim for processing.

    Flow:
        Request
          ↓
        Pipeline
          ↓
        Decision
          ↓
        Persist Result
          ↓
        Response
    """

    claim_id = str(uuid.uuid4())

    logger.info(
        "Received claim submission %s",
        claim_id,
    )

    try:
        ctx = run_claim_pipeline(
            submission=claim,
            policy=policy,
        )

        result = {
            "claim_id": claim_id,
            "submitted_at": datetime.utcnow().isoformat(),
            "decision": (
                ctx.decision.model_dump()
                if ctx.decision
                else None
            ),
            "trace": [
                trace.model_dump()
                for trace in ctx.trace
            ],
            "degraded": ctx.degraded,
            "fraud_score": ctx.fraud_score,
            "fraud_signals": ctx.fraud_signals,
        }

        CLAIMS_DB[claim_id] = result

        return result

    except Exception as exc:
        logger.exception(
            "Claim processing failed for %s",
            claim_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Claim processing failed: {str(exc)}",
        ) from exc


# ---------------------------------------------------------------------
# GET /claims/{claim_id}
# ---------------------------------------------------------------------


@router.get("/{claim_id}")
async def get_claim(
    claim_id: str,
) -> dict:
    """
    Retrieve previously processed claim.
    """

    claim = CLAIMS_DB.get(claim_id)

    if claim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim '{claim_id}' not found",
        )

    return claim


# ---------------------------------------------------------------------
# GET /claims
# ---------------------------------------------------------------------


@router.get("")
async def list_claims() -> dict:
    """
    List processed claims.

    Useful during evaluation/demo.
    """

    return {
        "count": len(CLAIMS_DB),
        "claims": list(CLAIMS_DB.keys()),
    }