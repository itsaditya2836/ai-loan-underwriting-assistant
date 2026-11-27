"""LLM narrative reasoning provider interface and disabled local adapter."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict

from app.integrations.base import (
    ExternalServiceAdapter,
    IntegrationHealth,
    IntegrationResult,
    IntegrationStatus,
)
from config.settings import get_settings


class LLMReasoningProvider(ExternalServiceAdapter):
    """Interface for optional external LLM explanation/summarization integrations."""

    service_name = "llm_reasoning"
    category = "generative_ai"

    @abstractmethod
    def summarize_case(self, case_context: Dict[str, Any]) -> IntegrationResult:
        """Produce a supplementary narrative summary without overriding policy decisions."""


class DisabledLocalLLMProvider(LLMReasoningProvider):
    """Safe local adapter respecting deterministic underwriting boundaries."""

    def health_check(self) -> IntegrationHealth:
        settings = get_settings()
        has_key = bool(settings.gemini_api_key and settings.gemini_api_key.strip())
        return IntegrationHealth(
            service_name=self.service_name,
            category=self.category,
            status=(
                IntegrationStatus.CONFIGURED if has_key else IntegrationStatus.DISABLED
            ),
            mode="deterministic_local",
            credentials_configured=has_key,
            details=(
                "GEMINI_API_KEY detected in environment (runtime calls kept disabled; underwriting uses deterministic agents)."
                if has_key
                else "No GEMINI_API_KEY configured; deterministic local reasoning active."
            ),
        )

    def summarize_case(self, case_context: Dict[str, Any]) -> IntegrationResult:
        return IntegrationResult(
            service_name=self.service_name,
            status=IntegrationStatus.DISABLED,
            success=False,
            sandboxed=True,
            timed_out=False,
            payload={"keys_present": sorted(case_context.keys())},
            error="External LLM calls are disabled; deterministic local summary applies.",
        )
