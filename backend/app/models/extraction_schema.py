"""
Validation schema for LLM extraction responses.

Purpose
-------
Validate Gemini output before it enters the claim-processing workflow.

This prevents malformed JSON or unexpected structures from reaching:
    - Rules Engine
    - Fraud Detection
    - Decision Synthesis

Expected Gemini response:

{
    "fields": {...},
    "confidence": 0.95,
    "quality_flags": [],
    "status": "OK"
}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExtractionResponse(BaseModel):
    """
    Standardized output expected from any extraction model
    (Gemini, Claude, GPT, OCR pipeline, etc.).
    """

    fields: dict[str, Any] = Field(
        default_factory=dict
    )

    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
    )

    quality_flags: list[str] = Field(
        default_factory=list
    )

    status: str = Field(
        default="OK"
    )

    @field_validator("status")
    @classmethod
    def validate_status(
        cls,
        value: str,
    ) -> str:

        allowed = {
            "OK",
            "PARTIAL",
            "FAILED",
        }

        if value not in allowed:
            raise ValueError(
                f"status must be one of {allowed}"
            )

        return value