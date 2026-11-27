"""External Integration Foundations Package.

Defines clean, mock-safe adapter interfaces and sandboxed local defaults for
credit bureau, KYC verification, LLM reasoning, and audit webhooks.
"""

from app.integrations.base import (
    ExternalServiceAdapter,
    IntegrationHealth,
    IntegrationResult,
    IntegrationStatus,
)
from app.integrations.credit_bureau import (
    CreditBureauProvider,
    LocalSyntheticCreditBureauAdapter,
)
from app.integrations.kyc_provider import (
    KYCVerificationProvider,
    LocalSyntheticKYCAdapter,
)
from app.integrations.llm_provider import (
    DisabledLocalLLMProvider,
    LLMReasoningProvider,
)
from app.integrations.registry import (
    IntegrationRegistry,
    get_integration_statuses,
)
from app.integrations.webhook import (
    AuditWebhookPublisher,
    NoOpWebhookPublisher,
)

__all__ = [
    "AuditWebhookPublisher",
    "CreditBureauProvider",
    "DisabledLocalLLMProvider",
    "ExternalServiceAdapter",
    "IntegrationHealth",
    "IntegrationRegistry",
    "IntegrationResult",
    "IntegrationStatus",
    "KYCVerificationProvider",
    "LLMReasoningProvider",
    "LocalSyntheticCreditBureauAdapter",
    "LocalSyntheticKYCAdapter",
    "NoOpWebhookPublisher",
    "get_integration_statuses",
]
