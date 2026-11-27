"""Orchestration package for multi-agent loan underwriting workflow."""

from app.orchestration.consistency import (
    AUTHORITATIVE_SOURCES,
    check_cross_agent_consistency,
    validate_anomaly_output,
    validate_applicant_data,
    validate_document_output,
    validate_eligibility_output,
    validate_risk_output,
)
from app.orchestration.errors import (
    AgentExecutionError,
    ApplicantNotFoundError,
    OrchestrationError,
    PipelineConfigurationError,
)


def __getattr__(name: str):
    """Lazily expose orchestrator symbols to avoid circular imports with agents/decision."""
    if name in ("ORCHESTRATOR_VERSION", "UnderwritingOrchestrator"):
        from app.orchestration.orchestrator import (
            ORCHESTRATOR_VERSION,
            UnderwritingOrchestrator,
        )

        return {
            "ORCHESTRATOR_VERSION": ORCHESTRATOR_VERSION,
            "UnderwritingOrchestrator": UnderwritingOrchestrator,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AUTHORITATIVE_SOURCES",
    "AgentExecutionError",
    "ApplicantNotFoundError",
    "ORCHESTRATOR_VERSION",
    "OrchestrationError",
    "PipelineConfigurationError",
    "UnderwritingOrchestrator",
    "check_cross_agent_consistency",
    "validate_anomaly_output",
    "validate_applicant_data",
    "validate_document_output",
    "validate_eligibility_output",
    "validate_risk_output",
]
