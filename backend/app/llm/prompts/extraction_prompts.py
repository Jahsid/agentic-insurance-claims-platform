"""
Doc-type-specific extraction prompts. Each prompt instructs the model
to return ONLY a JSON object of this shape:

{
  "fields": { ... doc-type-specific fields ... },
  "confidence": 0.0-1.0,
  "quality_flags": ["LIST", "OF", "FLAGS"],
  "status": "OK" | "PARTIAL" | "FAILED"
}

quality_flags vocabulary (from sample_documents_guide.md):
  HANDWRITTEN, STAMP_OVER_TEXT, MULTILINGUAL, PARTIAL_DOCUMENT,
  DOCUMENT_ALTERATION, DUPLICATE_STAMP, LOW_RESOLUTION
"""
from __future__ import annotations

_COMMON_SUFFIX = """
Indian medical documents are often messy: handwritten, with rubber
stamps over text, regional-language fields mixed with English, phone
photos with shadows/skew, or multi-page.

If a field is illegible or missing, set it to null and add a relevant
quality_flag (e.g. "STAMP_OVER_TEXT", "HANDWRITTEN", "LOW_RESOLUTION",
"PARTIAL_DOCUMENT", "DOCUMENT_ALTERATION", "DUPLICATE_STAMP",
"MULTILINGUAL"). Lower the confidence score accordingly
(below 0.5 if multiple key fields are unreadable).

Respond with ONLY a JSON object of the form:
{
  "fields": { ... },
  "confidence": <float 0.0-1.0>,
  "quality_flags": [ ... ],
  "status": "OK" | "PARTIAL" | "FAILED"
}
No prose, no markdown fences.
"""

PRESCRIPTION_PROMPT = """
You are extracting structured data from a photo/scan of an Indian
medical prescription. Extract these fields into "fields":
- doctor_name
- doctor_registration (format like KA/45678/2015 or AYUR/KL/2345/2019)
- patient_name
- date (YYYY-MM-DD if possible)
- diagnosis
- treatment
- medicines (list of strings, with dosage if visible)
- tests_ordered (list of strings)
""" + _COMMON_SUFFIX

HOSPITAL_BILL_PROMPT = """
You are extracting structured data from a hospital/clinic bill or
pharmacy bill. Extract these fields into "fields":
- hospital_name
- patient_name
- date (YYYY-MM-DD if possible)
- line_items (list of {"description": str, "amount": float})
- total (float)
""" + _COMMON_SUFFIX

LAB_REPORT_PROMPT = """
You are extracting structured data from a diagnostic/lab report.
Extract these fields into "fields":
- lab_name
- patient_name
- sample_date (YYYY-MM-DD if possible)
- report_date (YYYY-MM-DD if possible)
- tests (list of {"name": str, "result": str, "unit": str, "normal_range": str})
- remarks
""" + _COMMON_SUFFIX

GENERIC_PROMPT = """
You are extracting structured data from a medical document of
unspecified type. Extract whatever fields are relevant (patient name,
dates, amounts, diagnosis, line items, etc.) into "fields".
""" + _COMMON_SUFFIX

_PROMPTS = {
    "PRESCRIPTION": PRESCRIPTION_PROMPT,
    "HOSPITAL_BILL": HOSPITAL_BILL_PROMPT,
    "PHARMACY_BILL": HOSPITAL_BILL_PROMPT,
    "LAB_REPORT": LAB_REPORT_PROMPT,
    "DIAGNOSTIC_REPORT": LAB_REPORT_PROMPT,
}


def get_extraction_prompt(document_type: str) -> str:
    return _PROMPTS.get(document_type.upper(), GENERIC_PROMPT)