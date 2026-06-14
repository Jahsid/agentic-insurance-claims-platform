"""
Thin wrapper around Gemini for document extraction.

Used only for live document processing.
The evaluation harness bypasses this layer.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from app.llm.prompts.extraction_prompts import get_extraction_prompt

load_dotenv()


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ):
        import google.generativeai as genai

        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model or os.getenv(
            "MODEL_NAME",
            "gemini-2.5-flash",
        )

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY not found in environment."
            )

        genai.configure(api_key=self.api_key)

        self.model = genai.GenerativeModel(
            self.model_name
        )

        self.timeout = timeout

    def extract_document(self, doc) -> dict:
        """
        Extract structured fields from a document.

        Returns:
        {
            "fields": {},
            "confidence": float,
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

        response = self.model.generate_content(
            prompt
        )

        text = response.text.strip()

        if text.startswith("```json"):
            text = text.replace(
                "```json",
                ""
            ).replace(
                "```",
                ""
            ).strip()

        elif text.startswith("```"):
            text = text.replace(
                "```",
                ""
            ).strip()

        parsed = json.loads(text)

        return {
            "fields": parsed.get(
                "fields",
                {},
            ),
            "confidence": float(
                parsed.get(
                    "confidence",
                    0.7,
                )
            ),
            "quality_flags": parsed.get(
                "quality_flags",
                [],
            ),
            "status": parsed.get(
                "status",
                "OK",
            ),
        }