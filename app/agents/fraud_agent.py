"""Fraud and Anomaly Detection Agent module.

Cross-verifies applicant declarations against Stage 3 extracted document data,
detecting inconsistencies, identity discrepancies, and financial anomalies.
"""

from typing import Any, Dict, List, Optional, Union

from app.fraud.anomaly_detection import AnomalyDetector
from app.schemas.anomaly import AnomalyResult
from app.schemas.applicant import Applicant, Document, DocumentPackageResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class FraudAnomalyAgent:
    """Agent responsible for cross-document consistency checks and anomaly detection.

    Consumes Stage 3 document intelligence outputs (DocumentPackageResult) or structured
    Applicant domain models, evaluates deterministic cross-document consistency rules,
    and returns a structured AnomalyResult.
    Does NOT determine loan approvals, calculate credit risk, or make final decisions.
    """

    def __init__(self, detector: Optional[AnomalyDetector] = None) -> None:
        """Initialize the Fraud and Anomaly Detection Agent."""
        self.detector = detector or AnomalyDetector()
        logger.info("FraudAnomalyAgent initialized.")

    def detect(
        self,
        target: Union[DocumentPackageResult, Applicant, Dict[str, Any]],
        documents: Optional[List[Document]] = None,
        applicant_profile: Optional[Applicant] = None,
    ) -> AnomalyResult:
        """Analyze documents and applicant data for cross-document anomalies.

        Args:
            target: Stage 3 DocumentPackageResult, Applicant model, or raw data dict.
            documents: Optional list of Document records for backward compatibility.
            applicant_profile: Optional reference Applicant model.

        Returns:
            Structured AnomalyResult detailing score, severity, flags, and missing evidence.
        """
        logger.info(
            "FraudAnomalyAgent evaluating target type: %s", type(target).__name__
        )
        return self.detector.evaluate(
            target=target, applicant_profile=applicant_profile
        )
