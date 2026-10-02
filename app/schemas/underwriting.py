"""Pydantic schemas for multi-agent underwriting orchestration.

Defines structured data contracts for:
- AgentStatus: Lifecycle state of individual specialized agents.
- OrchestrationStatus: Overall completion state of the underwriting pipeline.
- AgentExecutionStatus: Execution telemetry and audit tracking per agent.
- UnderwritingAnalysisResult: Unified analytical synthesis of all agent findings
  prior to Stage 8 decisioning.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.anomaly import AnomalyResult
from app.schemas.applicant import (
    DocumentPackageResult,
    EligibilityResult,
    RiskResult,
)


class AgentStatus(str, Enum):
    """Execution state of an individual agent in the underwriting pipeline."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class OrchestrationStatus(str, Enum):
    """Aggregate lifecycle status of the underwriting pipeline."""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class AgentExecutionStatus(BaseModel):
    """Audit and telemetry record for an individual agent execution."""

    agent_name: str = Field(..., description="Identifier of the executing agent")
    status: AgentStatus = Field(
        default=AgentStatus.PENDING, description="Execution status"
    )
    started_at: Optional[datetime] = Field(
        default=None, description="Timestamp when agent execution started"
    )
    completed_at: Optional[datetime] = Field(
        default=None, description="Timestamp when agent execution completed"
    )
    duration_ms: Optional[float] = Field(
        default=None, ge=0.0, description="Execution wall-clock time in milliseconds"
    )
    error: Optional[str] = Field(
        default=None, description="Error message or exception details if failed"
    )


class UnderwritingAnalysisResult(BaseModel):
    """Unified analytical output from the Stage 7 Multi-Agent Orchestrator.

    Aggregates analytical findings from Document Intelligence, Underwriting
    Eligibility, Risk Assessment, and Fraud & Anomaly Detection agents.
    Strictly separates analysis from final loan decisioning (reserved for Stage 8).
    """

    application_id: str = Field(
        ..., description="Unique application or applicant identifier"
    )
    applicant_id: str = Field(..., description="Identifier of the loan applicant")
    orchestration_status: OrchestrationStatus = Field(
        ..., description="Overall pipeline status: SUCCESS, PARTIAL_SUCCESS, or FAILED"
    )
    document_result: Optional[DocumentPackageResult] = Field(
        default=None, description="Stage 3 Document Intelligence intake findings"
    )
    eligibility_result: Optional[EligibilityResult] = Field(
        default=None, description="Stage 4 Underwriting Eligibility policy outcomes"
    )
    risk_result: Optional[RiskResult] = Field(
        default=None, description="Stage 5 Financial and credit risk assessment"
    )
    anomaly_result: Optional[AnomalyResult] = Field(
        default=None,
        description="Stage 6 Cross-document anomaly and discrepancy findings",
    )
    agent_statuses: Dict[str, AgentExecutionStatus] = Field(
        default_factory=dict,
        description="Telemetry and execution status mapping for each agent",
    )
    pipeline_started_at: Optional[datetime] = Field(
        default=None, description="Timestamp when pipeline orchestration commenced"
    )
    pipeline_completed_at: Optional[datetime] = Field(
        default=None, description="Timestamp when pipeline orchestration finished"
    )
    total_duration_ms: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total pipeline execution duration in milliseconds",
    )
    pipeline_version: str = Field(
        default="pipeline_v1",
        description="Version identifier of the orchestrator pipeline specification",
    )
    error_message: Optional[str] = Field(
        default=None, description="High-level error explanation if pipeline failed"
    )
    summary: Optional[str] = Field(
        default=None,
        description="Executive analytical summary of findings across all executed agents",
    )

    @model_validator(mode="before")
    @classmethod
    def sync_ids(cls, data: Any) -> Any:
        """Ensure applicant_id and application_id remain synchronized."""
        if isinstance(data, dict):
            if "application_id" in data and "applicant_id" not in data:
                data["applicant_id"] = data["application_id"]
            elif "applicant_id" in data and "application_id" not in data:
                data["application_id"] = data["applicant_id"]
        return data


__all__ = [
    "AgentStatus",
    "OrchestrationStatus",
    "AgentExecutionStatus",
    "UnderwritingAnalysisResult",
]
