"""
Gemini Vision Client

Supports:
- PDF upload
- PNG/JPG upload
- Handwritten prescriptions
- Multi-page hospital bills
- Structured JSON extraction
"""

from __future__ import annotations

import json
import os
import time
from dotenv import load_dotenv

from app.llm.prompts.extraction_prompts import get_extraction_prompt
from app.models.extraction_schema import ExtractionResponse

load_dotenv()


class LLMClient:

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        # Correct import for the modern Google GenAI SDK
        from google import genai

        self.api_key = api_key or os.getenv("GEMINI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY missing. "
                "Set it via the GEMINI_API_KEY environment variable "
                "or pass api_key= to LLMClient()."
            )

        # 1. FIX: Initialize the Client object instead of using genai.configure()
        self.client = genai.Client(api_key=self.api_key)

        self.model_name = (
            model
            or os.getenv(
                "MODEL_NAME",
                "gemini-2.5-flash",
            )
        )

    # =====================================================
    # Extraction
    # =====================================================

    def extract_document(
        self,
        doc,
    ) -> dict:
        """
        Real Gemini Vision extraction.
        """
        if not doc.file_path:
            return {
                "fields": {},
                "confidence": 0.0,
                "quality_flags": ["MISSING_FILE"],
                "status": "FAILED",
            }

        try:
            # 2. FIX: Use self.client.files.upload() instead of genai.upload_file()
            file_ref = self.client.files.upload(file=doc.file_path)

            # 3. FIX: Check file_ref.state instead of file_ref.state.name
            while file_ref.state.name == "PROCESSING":
                time.sleep(1)
                # Use self.client.files.get()
                file_ref = self.client.files.get(name=file_ref.name)

            doc_type = (
                doc.actual_type.value
                if doc.actual_type
                else "UNKNOWN"
            )

            extraction_prompt = get_extraction_prompt(doc_type)

            prompt = f"""
You are a health-insurance document extraction engine.

Document Type:
{doc_type}

Instructions:
{extraction_prompt}

IMPORTANT:
Return ONLY valid JSON conforming exactly to the structured schema requested.
"""

            # 4. FIX: Use self.client.models.generate_content() and add structural constraint if desired
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[file_ref, prompt]
            )

            text = response.text.strip()

            # Clean markdown code blocks if the model wrapped its response
            if text.startswith("```json"):
                text = text.replace("```json", "", 1).replace("```", "", 1).strip()
            elif text.startswith("```"):
                text = text.replace("```", "", 2).strip()

            parsed = json.loads(text)
            validated = ExtractionResponse(**parsed)

            return validated.model_dump()

        except Exception as exc:
            return {
                "fields": {},
                "confidence": 0.0,
                "quality_flags": ["EXTRACTION_FAILED"],
                "status": "FAILED",
                "error": str(exc),
            }

    # =====================================================
    # Classification
    # =====================================================

    def classify_document(
        self,
        doc,
    ) -> str:
        """
        Gemini document classification.
        """
        if not doc.file_path:
            return "UNKNOWN"

        try:
            # 5. FIX: Use self.client.files.upload()
            file_ref = self.client.files.upload(file=doc.file_path)

            prompt = """
Classify this document.

Return ONLY one value:
PRESCRIPTION
HOSPITAL_BILL
PHARMACY_BILL
LAB_REPORT
DIAGNOSTIC_REPORT
DISCHARGE_SUMMARY
DENTAL_REPORT
UNKNOWN
"""

            # 6. FIX: Use self.client.models.generate_content()
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[file_ref, prompt]
            )

            result = response.text.strip().upper()

            allowed = {
                "PRESCRIPTION",
                "HOSPITAL_BILL",
                "PHARMACY_BILL",
                "LAB_REPORT",
                "DIAGNOSTIC_REPORT",
                "DISCHARGE_SUMMARY",
                "DENTAL_REPORT",
                "UNKNOWN",
            }

            if result not in allowed:
                return "UNKNOWN"

            return result

        except Exception:
            return "UNKNOWN"