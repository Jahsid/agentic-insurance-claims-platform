"""
FastAPI application entrypoint.

Responsibilities:
- Create and configure the FastAPI application.
- Register API routers.
- Install global exception handlers.
- Configure CORS.
- Expose health/readiness endpoints.
- Register upload endpoints.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ------------------------------------------------------------------
# Routers
# ------------------------------------------------------------------

try:
    from app.api.routes_health import router as health_router
except ImportError:
    health_router = None

from app.api.routes_claims import router as claims_router
from app.api.routes_uploads import router as uploads_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """
    Application Factory
    """

    app = FastAPI(
        title="Plum Claims Processing System",
        description=(
            "Agentic insurance claims processing platform "
            "with document verification, extraction, "
            "rules evaluation, fraud detection, "
            "and explainable decision synthesis."
        ),
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            # Local Frontend
            "http://localhost:5173",
            "http://127.0.0.1:5173",

            # Vercel Production Frontend
            "https://agentic-insurance-claims-platform.vercel.app",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------

    if health_router:
        app.include_router(
            health_router,
            tags=["health"],
        )

    app.include_router(
        claims_router,
        prefix="/claims",
        tags=["claims"],
    )

    app.include_router(
        uploads_router,
        tags=["uploads"],
    )

    # ------------------------------------------------------------------
    # Global Exception Handler
    # ------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:

        logger.exception(
            "Unhandled exception during request %s %s",
            request.method,
            request.url.path,
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "message": (
                    "An unexpected error occurred while "
                    "processing the request."
                ),
            },
        )

    # ------------------------------------------------------------------
    # Root Endpoint
    # ------------------------------------------------------------------

    @app.get("/", tags=["system"])
    async def root() -> dict:
        return {
            "service": "plum-claims",
            "status": "running",
            "version": "2.0.0",
            "features": [
                "document_verification",
                "document_classification",
                "policy_rules_engine",
                "fraud_detection",
                "decision_synthesis",
                "real_file_uploads",
                "explainable_trace",
            ],
        }

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    @app.get("/health", tags=["system"])
    async def health() -> dict:
        return {
            "status": "healthy",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )