"""
Thin wrapper around Gemini for document extraction.

Used only for live document processing.
The evaluation harness bypasses this layer.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from app.llm.prompts.extraction_prompts import (
    get_extraction_prompt,
)
from app.models.extraction_schema import (
    ExtractionResponse,
)

load_dotenv()


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ):
        import google.generativeai as genai

        self.api_key = api_key or os.getenv(
            "GEMINI_API_KEY"
        )

        self.model_name = model or os.getenv(
            "MODEL_NAME",
            "gemini-2.5-flash",
        )

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY not found in environment."
            )

        genai.configure(
            api_key=self.api_key
        )

        self.model = genai.GenerativeModel(
            self.model_name
        )

        self.timeout = timeout

    def extract_document(self, doc) -> dict:
        """
        Extract structured fields from a document.

        Expected response:

        {
            "fields": {},
            "confidence": 0.95,
            "quality_flags": [],
            "status": "OK"
        }
        """

        doc_type = (
            doc.actual_type.value
            if doc.actual_type
            else "UNKNOWN"
        )

        extraction_prompt = get_extraction_prompt(
            doc_type
        )

        prompt = f"""
You are an insurance document extraction engine.

{extraction_prompt}

Return ONLY valid JSON.

Expected format:

{{
  "fields": {{}},
  "confidence": 0.95,
  "quality_flags": [],
  "status": "OK"
}}
"""

        try:

            response = self.model.generate_content(
                prompt
            )

            text = response.text.strip()

            # ----------------------------------------
            # Remove markdown code fences
            # ----------------------------------------

            if text.startswith("```json"):
                text = (
                    text.replace(
                        "```json",
                        "",
                    )
                    .replace(
                        "```",
                        "",
                    )
                    .strip()
                )

            elif text.startswith("```"):
                text = (
                    text.replace(
                        "```",
                        "",
                    )
                    .strip()
                )

            parsed = json.loads(text)

            # ----------------------------------------
            # Validate Gemini response
            # ----------------------------------------

            validated = ExtractionResponse(
                **parsed
            )

            return validated.model_dump()

        except Exception as exc:  # noqa: BLE001

            return {
                "fields": {},
                "confidence": 0.0,
                "quality_flags": [
                    "EXTRACTION_FAILED"
                ],
                "status": "FAILED",
                "error": str(exc),
            }

    def classify_document(
        self,
        doc,
    ) -> str:
        """
        Optional future hook used by
        DocumentClassifierAgent.

        Not currently required by the
        evaluation harness.

        Expected return values:

        PRESCRIPTION
        HOSPITAL_BILL
        PHARMACY_BILL
        LAB_REPORT
        DIAGNOSTIC_REPORT
        DISCHARGE_SUMMARY
        DENTAL_REPORT
        UNKNOWN
        """

        raise NotImplementedError(
            "Gemini document classification "
            "is not implemented yet."
        )