"""Credit Bureau integration interface and sandbox adapter."""

from __future__ import annotations

from abc import abstractmethod

from app.integrations.base import (
    ExternalServiceAdapter,
    IntegrationHealth,
    IntegrationResult,
    IntegrationStatus,
)


class CreditBureauProvider(ExternalServiceAdapter):
    """Interface for retrieving external credit bureau reports."""

    service_name = "credit_bureau"
    category = "credit_reporting"

    @abstractmethod
    def fetch_credit_report(self, applicant_id: str) -> IntegrationResult:
        """Fetch external credit report summary for an applicant."""


class LocalSyntheticCreditBureauAdapter(CreditBureauProvider):
    """Local sandbox adapter (no external network calls in prototype mode)."""

    def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(
            service_name=self.service_name,
            category=self.category,
            status=IntegrationStatus.SANDBOX,
            mode="local_sandbox",
            credentials_configured=False,
            details="Local synthetic credit bureau stub; no outbound API calls configured.",
        )

    def fetch_credit_report(self, applicant_id: str) -> IntegrationResult:
        return IntegrationResult(
            service_name=self.service_name,
            status=IntegrationStatus.SANDBOX,
            success=False,
            sandboxed=True,
            timed_out=False,
            payload={"applicant_id": applicant_id, "synthetic_sandbox": True},
            error="External credit bureau integration is in local sandbox mode.",
        )
