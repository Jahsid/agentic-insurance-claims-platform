"""
Document models: what comes in (the raw upload) and what comes out
of the Extraction Agent (structured, validated fields per doc type).

DocumentQuality / extraction confidence flow into the overall
decision confidence score (see decision.py).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    PHARMACY_BILL = "PHARMACY_BILL"
    LAB_REPORT = "LAB_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DENTAL_REPORT = "DENTAL_REPORT"
    UNKNOWN = "UNKNOWN"


class DocumentQuality(str, Enum):
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"          # some fields unreadable
    UNREADABLE = "UNREADABLE"    # whole document unusable


class UploadedDocument(BaseModel):
    """What the client sends us for one uploaded file."""
    file_id: str
    file_name: Optional[str] = None
    # In production this would be a storage URI / base64 image.
    # For the eval harness we also accept a pre-supplied `actual_type`
    # and `content` (ground truth) to simulate extraction deterministically
    # or to bypass the vision LLM during testing.
    actual_type: Optional[DocumentType] = None
    quality: Optional[DocumentQuality] = None
    patient_name_on_doc: Optional[str] = None
    content: Optional[dict] = None


class LineItem(BaseModel):
    description: str
    amount: float


class ExtractedPrescription(BaseModel):
    doctor_name: Optional[str] = None
    doctor_registration: Optional[str] = None
    patient_name: Optional[str] = None
    date: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment: Optional[str] = None
    medicines: list[str] = []
    tests_ordered: list[str] = []


class ExtractedBill(BaseModel):
    hospital_name: Optional[str] = None
    patient_name: Optional[str] = None
    date: Optional[str] = None
    line_items: list[LineItem] = []
    total: Optional[float] = None


class ExtractedLabReport(BaseModel):
    lab_name: Optional[str] = None
    patient_name: Optional[str] = None
    sample_date: Optional[str] = None
    report_date: Optional[str] = None
    tests: list[dict] = []
    remarks: Optional[str] = None


class DocumentExtractionResult(BaseModel):
    """Output of the Extraction Agent for a single document."""
    file_id: str
    document_type: DocumentType
    extracted_fields: dict = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    quality_flags: list[str] = Field(default_factory=list)
    extraction_status: str = "OK"  # OK | PARTIAL | FAILED
    error: Optional[str] = None