"""
FastAPI application entrypoint.

Responsibilities:
- Create and configure the FastAPI application.
- Register API routers.
- Install global exception handlers.
- Expose health/readiness endpoints through routers.
- Keep orchestration/business logic outside the web layer.

The claim-processing workflow itself lives in:
    app.orchestrator.pipeline

API routes should remain thin adapters that:
    Request -> Pydantic Model -> Pipeline -> Response
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Routers (implemented separately)
try:
    from app.api.routes_health import router as health_router
except ImportError:
    health_router = None

from app.api.routes_claims import router as claims_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """
    Application factory.

    Using a factory makes testing easier and allows future
    environment-specific configuration without side effects
    at import time.
    """
    app = FastAPI(
        title="Plum Claims Processing System",
        description=(
            "Multi-stage explainable insurance claims processing "
            "platform with document verification, extraction, "
            "rules evaluation, fraud detection, and decision synthesis."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    if health_router:
        app.include_router(
            health_router,
            tags=["health"],
        )

    if claims_router:
        app.include_router(
            claims_router,
            prefix="/claims",
            tags=["claims"],
        )

    # ------------------------------------------------------------------
    # Global exception handling
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
                    "An unexpected error occurred while processing "
                    "the request."
                ),
            },
        )

    # ------------------------------------------------------------------
    # Root endpoint
    # ------------------------------------------------------------------
    @app.get("/", tags=["system"])
    async def root() -> dict:
        return {
            "service": "plum-claims",
            "status": "running",
            "version": "1.0.0",
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