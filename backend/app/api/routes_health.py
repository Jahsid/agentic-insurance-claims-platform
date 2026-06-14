"""
Health and readiness endpoints.

These routes are intentionally lightweight and should not
invoke the claims pipeline.

Used by:
- Docker health checks
- Kubernetes probes
- Load balancers
- Monitoring systems
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """
    Liveness probe.

    Indicates that the application process is running.
    """

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/health/ready")
async def readiness() -> dict:
    """
    Readiness probe.

    Future checks:
    - policy file loaded
    - database reachable
    - LLM provider reachable
    - cache available
    """

    return {
        "status": "ready",
        "checks": {
            "application": True,
        },
    }


@router.get("/health/info")
async def info() -> dict:
    """
    Service metadata.
    """

    return {
        "service": "plum-claims",
        "version": "1.0.0",
        "environment": "development",
        "api": "v1",
    }