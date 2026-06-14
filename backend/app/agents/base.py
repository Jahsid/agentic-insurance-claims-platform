"""
BaseAgent: common wrapper that every agent/component extends.

Provides a `run_safe()` method that catches exceptions, appends a
TraceEntry describing the failure, marks the ClaimContext as degraded,
and lets the pipeline continue with whatever partial output is available.

This is the mechanism behind requirement #6 (graceful degradation, TC011):
no component failure should crash the pipeline.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.models.claim import ClaimContext
from app.models.decision import TraceEntry, TraceStatus

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Base class for agent-raised errors. Subclass per agent for specificity."""


class BaseAgent(ABC):
    name: str = "BaseAgent"
    stage: str = "unspecified"

    @abstractmethod
    def run(self, ctx: ClaimContext) -> ClaimContext:
        """Perform the agent's work, mutating and returning ctx."""
        raise NotImplementedError

    def run_safe(self, ctx: ClaimContext) -> ClaimContext:
        try:
            return self.run(ctx)
        except Exception as exc:  # noqa: BLE001 - intentional broad catch at boundary
            logger.exception("Agent %s failed", self.name)
            ctx.degraded = True
            ctx.add_trace(
                TraceEntry(
                    stage=self.stage,
                    component=self.name,
                    status=TraceStatus.FAIL,
                    message=(
                        f"{self.name} failed with an unexpected error and was skipped. "
                        f"Pipeline continued with partial data."
                    ),
                    details={"error": str(exc), "error_type": type(exc).__name__},
                    confidence_impact=-0.25,
                )
            )
            return ctx