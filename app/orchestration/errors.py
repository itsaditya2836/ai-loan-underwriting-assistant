"""Exception hierarchy for multi-agent underwriting orchestration."""


class OrchestrationError(Exception):
    """Base exception for all orchestration failures."""


class ApplicantNotFoundError(OrchestrationError):
    """Raised when an applicant or application identifier cannot be located."""

    def __init__(self, application_id: str) -> None:
        super().__init__(
            f"Applicant profile not found for identifier: '{application_id}'."
        )
        self.application_id = application_id


class AgentExecutionError(OrchestrationError):
    """Raised when an individual specialized agent fails execution."""

    def __init__(self, agent_name: str, reason: str) -> None:
        super().__init__(f"Agent '{agent_name}' failed execution: {reason}")
        self.agent_name = agent_name
        self.reason = reason


class PipelineConfigurationError(OrchestrationError):
    """Raised when pipeline configuration or prerequisite dependencies are missing."""
