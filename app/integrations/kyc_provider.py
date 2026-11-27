"""KYC identity verification interface and sandbox adapter."""

from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from app.integrations.base import (
    ExternalServiceAdapter,
    IntegrationHealth,
    IntegrationResult,
    IntegrationStatus,
)


class KYCVerificationProvider(ExternalServiceAdapter):
    """Interface for external KYC/identity verification providers."""

    service_name = "kyc_provider"
    category = "identity_verification"

    @abstractmethod
    def verify_identity(
        self,
        applicant_id: str,
        full_name: str,
        id_ref: Optional[str] = None,
    ) -> IntegrationResult:
        """Verify applicant identity against an external KYC registry."""


class LocalSyntheticKYCAdapter(KYCVerificationProvider):
    """Local sandbox KYC adapter (never sends PII to external providers)."""

    def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(
            service_name=self.service_name,
            category=self.category,
            status=IntegrationStatus.SANDBOX,
            mode="local_sandbox",
            credentials_configured=False,
            details="Local sandbox KYC stub; document verification relies on Stage 3 OCR/rules.",
        )

    def verify_identity(
        self,
        applicant_id: str,
        full_name: str,
        id_ref: Optional[str] = None,
    ) -> IntegrationResult:
        return IntegrationResult(
            service_name=self.service_name,
            success=False,
            sandboxed=True,
            payload={"applicant_id": applicant_id, "id_ref_supplied": bool(id_ref)},
            error="External KYC verification provider is in local sandbox mode.",
        )
