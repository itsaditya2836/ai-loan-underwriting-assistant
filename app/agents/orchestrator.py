"""Orchestrator Agent module.

Coordinates the specialized multi-agent workflow, managing execution order,
data pipelines between agents, and state progression through the underwriting pipeline.
"""

from typing import TYPE_CHECKING, List, Optional

from app.schemas.applicant import Applicant, Document
from app.schemas.underwriting import UnderwritingAnalysisResult
from app.utils.helpers import get_logger

if TYPE_CHECKING:
    from app.orchestration.orchestrator import UnderwritingOrchestrator

logger = get_logger(__name__)


class OrchestratorAgent:
    """Master orchestrator agent coordinating specialized underwriting agents.

    Provides a clean agent facade wrapping the UnderwritingOrchestrator engine.
    """

    def __init__(
        self,
        orchestrator: Optional["UnderwritingOrchestrator"] = None,
    ) -> None:
        """Initialize the OrchestratorAgent."""
        if orchestrator is None:
            from app.orchestration.orchestrator import UnderwritingOrchestrator

            self.orchestrator = UnderwritingOrchestrator()
        else:
            self.orchestrator = orchestrator
        logger.info("OrchestratorAgent initialized.")

    def run_pipeline(
        self,
        applicant: Applicant,
        documents: Optional[List[Document]] = None,
        package_dir: Optional[str] = None,
    ) -> UnderwritingAnalysisResult:
        """Execute the end-to-end multi-agent underwriting workflow.

        Args:
            applicant: Pre-loaded Applicant profile model.
            documents: Optional list of Document objects.
            package_dir: Optional path to physical document directory.

        Returns:
            UnderwritingAnalysisResult containing all analytical agent findings.
        """
        return self.orchestrator.run_pipeline(
            applicant=applicant, documents=documents, package_dir=package_dir
        )

    def process(
        self,
        application_id: str,
        package_dir: Optional[str] = None,
    ) -> UnderwritingAnalysisResult:
        """Process an application by identifier.

        Args:
            application_id: Unique application identifier (e.g. 'APP0001').
            package_dir: Optional path to document directory.

        Returns:
            UnderwritingAnalysisResult.
        """
        return self.orchestrator.process(
            application_id=application_id, package_dir=package_dir
        )
