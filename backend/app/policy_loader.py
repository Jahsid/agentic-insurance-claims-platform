"""
Loads policy_terms.json from disk into a validated PolicyTerms model.

This is the ONLY place that reads the policy file. All other components
receive a PolicyTerms object — no component should hardcode any limit,
percentage, exclusion, or waiting period.
"""
from __future__ import annotations

import json
import functools
from pathlib import Path

from app.models.policy import PolicyTerms

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "data" / "policy_terms.json"


class PolicyLoadError(Exception):
    """Raised when the policy file cannot be read or fails validation."""


@functools.lru_cache(maxsize=8)
def load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> PolicyTerms:
    path = Path(path)
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError as e:
        raise PolicyLoadError(f"Policy file not found at {path}") from e
    except json.JSONDecodeError as e:
        raise PolicyLoadError(f"Policy file at {path} is not valid JSON: {e}") from e

    try:
        return PolicyTerms.model_validate(raw)
    except Exception as e:
        raise PolicyLoadError(f"Policy file at {path} failed schema validation: {e}") from e