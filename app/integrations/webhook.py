"""Audit and workflow webhook notification interface and No-Op publisher."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict

from app.integrations.base import (
    ExternalServiceAdapter,
    IntegrationHealth,
    IntegrationResult,
    IntegrationStatus,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class AuditWebhookPublisher(ExternalServiceAdapter):
    """Interface for publishing underwriting & human review events externally."""

    service_name = "audit_webhook"
    category = "notifications"

    @abstractmethod
    def publish_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> IntegrationResult:
        """Emit an event notification to downstream systems."""


class NoOpWebhookPublisher(AuditWebhookPublisher):
    """Local safe publisher that logs event envelopes without network dispatch."""

    def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(
            service_name=self.service_name,
            category=self.category,
            status=IntegrationStatus.DISABLED,
            mode="local_noop",
            credentials_configured=False,
            details="No outbound webhook endpoint configured; audit events stay persisted locally.",
        )

    def publish_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> IntegrationResult:
        logger.debug("NoOpWebhookPublisher received event '%s'.", event_type)
        return IntegrationResult(
            service_name=self.service_name,
            success=True,
            sandboxed=True,
            payload={"event_type": event_type, "dispatched": False},
        )
