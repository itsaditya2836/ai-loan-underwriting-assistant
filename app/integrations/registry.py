"""Central Integration Registry exposing health/readiness across configured adapters."""

from __future__ import annotations

from typing import Any, Dict, List

from app.integrations.base import ExternalServiceAdapter, IntegrationHealth
from app.integrations.credit_bureau import LocalSyntheticCreditBureauAdapter
from app.integrations.kyc_provider import LocalSyntheticKYCAdapter
from app.integrations.llm_provider import DisabledLocalLLMProvider
from app.integrations.webhook import NoOpWebhookPublisher


class IntegrationRegistry:
    """Manages registered external integration adapters safely."""

    def __init__(self, adapters: List[ExternalServiceAdapter] | None = None) -> None:
        self._adapters: List[ExternalServiceAdapter] = adapters or [
            LocalSyntheticCreditBureauAdapter(),
            LocalSyntheticKYCAdapter(),
            DisabledLocalLLMProvider(),
            NoOpWebhookPublisher(),
        ]

    def check_all(self) -> List[IntegrationHealth]:
        """Run health_check() across all adapters without leaking credentials."""
        return [adapter.health_check() for adapter in self._adapters]


def get_integration_statuses() -> List[Dict[str, Any]]:
    """Return serializable integration health records for API status endpoints."""
    registry = IntegrationRegistry()
    return [item.model_dump(mode="json") for item in registry.check_all()]
