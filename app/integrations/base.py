"""Base abstractions for external service integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class IntegrationStatus(str, Enum):
    """Operational readiness state for an external adapter."""

    DISABLED = "DISABLED"
    SANDBOX = "SANDBOX"
    CONFIGURED = "CONFIGURED"
    UNAVAILABLE = "UNAVAILABLE"


class IntegrationHealth(BaseModel):
    """Safe integration status summary (never contains raw API keys/secrets)."""

    service_name: str
    category: str
    status: IntegrationStatus
    mode: str = "local_sandbox"
    credentials_configured: bool = False
    details: str = ""
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntegrationResult(BaseModel):
    """Standardized envelope returned by external integration adapters."""

    service_name: str
    status: IntegrationStatus = IntegrationStatus.SANDBOX
    success: bool
    sandboxed: bool = True
    timed_out: bool = False
    latency_ms: Optional[float] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExternalServiceAdapter(ABC):
    """Abstract base class for pluggable external integration providers."""

    service_name: str = "external_service"
    category: str = "general"

    @abstractmethod
    def health_check(self) -> IntegrationHealth:
        """Report current adapter configuration and readiness safely."""
