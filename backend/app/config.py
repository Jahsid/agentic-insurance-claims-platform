"""
Centralized application configuration.

All environment-driven settings are read here, once, via a cached
Settings object. No other module should call os.getenv() directly --
this keeps configuration auditable and makes it trivial to override
settings in tests (see get_settings.cache_clear()).

Settings are loaded from a .env file (via python-dotenv) if present,
falling back to process environment variables, falling back to the
defaults below.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the backend/ directory (where this app package lives)
# without overriding variables already set in the real environment.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env", override=False)


class Settings:
    """
    Immutable snapshot of configuration, read once at startup.

    Attributes
    ----------
    environment : str
        "development" | "staging" | "production". Controls things like
        reload behaviour and verbosity of error responses.
    log_level : str
        Standard logging level name, e.g. "INFO", "DEBUG".
    host / port : str / int
        Bind address for uvicorn when running `python -m app.main`.
    cors_allowed_origins : list[str]
        Frontend origins allowed to call the API.
    gemini_api_key : str | None
        API key for the live document-extraction LLM path
        (app.llm.client.LLMClient). May be None in the eval/test
        environment, where test_cases.json supplies `content` directly
        and the LLM path is never invoked.
    model_name : str
        Gemini model name used for document extraction.
    policy_data_path : Path
        Path to policy_terms.json. Defaults to <repo_root>/data/policy_terms.json,
        matching app.policy_loader.DEFAULT_POLICY_PATH.
    """

    def __init__(self) -> None:
        self.environment: str = os.getenv("ENVIRONMENT", "development")
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

        self.host: str = os.getenv("HOST", "0.0.0.0")
        self.port: int = int(os.getenv("PORT", "8000"))

        origins = os.getenv("CORS_ALLOWED_ORIGINS")
        if origins:
            self.cors_allowed_origins: list[str] = [o.strip() for o in origins.split(",") if o.strip()]
        else:
            self.cors_allowed_origins = [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]

        self.gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
        self.model_name: str = os.getenv("MODEL_NAME", "gemini-2.5-flash")

        default_policy_path = _BACKEND_DIR.parent / "data" / "policy_terms.json"
        self.policy_data_path: Path = Path(os.getenv("POLICY_DATA_PATH", str(default_policy_path)))

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def llm_configured(self) -> bool:
        """Whether the live (Gemini) extraction path can be used."""
        return bool(self.gemini_api_key)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Settings(environment={self.environment!r}, log_level={self.log_level!r}, "
            f"host={self.host!r}, port={self.port}, "
            f"cors_allowed_origins={self.cors_allowed_origins!r}, "
            f"model_name={self.model_name!r}, llm_configured={self.llm_configured}, "
            f"policy_data_path={self.policy_data_path!r})"
        )


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached)."""
    return Settings()