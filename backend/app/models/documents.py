"""
Document models.

Defines:
- Uploaded document metadata
- Document classification types
- Extraction schemas
- Extraction results

Supports two modes:

1. Evaluation Mode
   - test_cases.json provides:
       actual_type
       content
   - bypasses Gemini extraction

2. Production Mode
   - real PDF/JPG/PNG uploads
   - file stored locally/cloud
   - Gemini Vision extracts structured data
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Document Types
# ============================================================================


class DocumentType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    PHARMACY_BILL = "PHARMACY_BILL"
    LAB_REPORT = "LAB_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DENTAL_REPORT = "DENTAL_REPORT"
    UNKNOWN = "UNKNOWN"


# ============================================================================
# Document Quality
# ============================================================================


class DocumentQuality(str, Enum):
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"
    UNREADABLE = "UNREADABLE"


# ============================================================================
# Uploaded Document
# ============================================================================


class UploadedDocument(BaseModel):
    """
    Input document supplied with a claim.

    Evaluation Mode:
        actual_type + content supplied by test cases.

    Production Mode:
        file uploaded by member and stored on disk/cloud.
    """

    file_id: str

    file_name: Optional[str] = None

    mime_type: Optional[str] = None
    # Example:
    # application/pdf
    # image/jpeg
    # image/png

    file_path: Optional[str] = None
    # Example:
    # storage/uploads/claim_123_bill.pdf

    actual_type: Optional[DocumentType] = None

    quality: Optional[DocumentQuality] = None

    patient_name_on_doc: Optional[str] = None

    content: Optional[dict] = None
    # Evaluation harness uses this directly
    # instead of calling Gemini.


# ============================================================================
# Shared Extraction Models
# ============================================================================


class LineItem(BaseModel):
    description: str
    amount: float


# ============================================================================
# Prescription Schema
# ============================================================================


class ExtractedPrescription(BaseModel):
    doctor_name: Optional[str] = None

    doctor_registration: Optional[str] = None

    patient_name: Optional[str] = None

    date: Optional[str] = None

    diagnosis: Optional[str] = None

    treatment: Optional[str] = None

    medicines: list[str] = Field(default_factory=list)

    tests_ordered: list[str] = Field(default_factory=list)


# ============================================================================
# Bill Schema
# ============================================================================


class ExtractedBill(BaseModel):
    hospital_name: Optional[str] = None

    patient_name: Optional[str] = None

    date: Optional[str] = None

    line_items: list[LineItem] = Field(default_factory=list)

    total: Optional[float] = None


# ============================================================================
# Lab Report Schema
# ============================================================================


class ExtractedLabReport(BaseModel):
    lab_name: Optional[str] = None

    patient_name: Optional[str] = None

    sample_date: Optional[str] = None

    report_date: Optional[str] = None

    tests: list[dict] = Field(default_factory=list)

    remarks: Optional[str] = None


# ============================================================================
# Extraction Result
# ============================================================================


class DocumentExtractionResult(BaseModel):
    """
    Output produced by ExtractionAgent.
    """

    file_id: str

    document_type: DocumentType

    extracted_fields: dict = Field(default_factory=dict)

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    quality_flags: list[str] = Field(
        default_factory=list
    )

    extraction_status: str = "OK"
    # OK
    # PARTIAL
    # FAILED

    error: Optional[str] = None