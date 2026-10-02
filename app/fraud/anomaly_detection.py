"""Anomaly and consistency detection engine module.

Exposes AnomalyDetector wrapping CrossDocumentAnomalyDetector for backward
compatibility with Stage 1 abstractions and tests.
"""

from typing import Any, Dict, List, Optional, Union

from app.fraud.detectors import CrossDocumentAnomalyDetector
from app.fraud.rules import AnomalyRulesConfig
from app.schemas.anomaly import AnomalyResult
from app.schemas.applicant import Applicant, Document, DocumentPackageResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class AnomalyDetector:
    """Detects discrepancies and suspicious inconsistencies across applicant documents."""

    def __init__(self, config: Optional[AnomalyRulesConfig] = None) -> None:
        """Initialize the anomaly detector."""
        self.detector = CrossDocumentAnomalyDetector(config=config)
        logger.info("AnomalyDetector initialized.")

    def detect_inconsistencies(
        self,
        applicant: Applicant,
        documents: Optional[List[Document]] = None,
        package_result: Optional[DocumentPackageResult] = None,
    ) -> List[Dict[str, Any]]:
        """Cross-check applicant profile declarations against document findings.

        Args:
            applicant: Target Applicant profile.
            documents: Optional list of Document models.
            package_result: Optional Stage 3 DocumentPackageResult.

        Returns:
            List of dictionary records detailing detected inconsistencies.
        """
        target = package_result if package_result is not None else applicant
        res = self.detector.detect_anomalies(target=target, applicant_profile=applicant)
        return [f.model_dump() for f in res.flags]

    def evaluate(
        self,
        target: Union[DocumentPackageResult, Applicant, Dict[str, Any]],
        applicant_profile: Optional[Applicant] = None,
    ) -> AnomalyResult:
        """Run complete anomaly assessment and return structured AnomalyResult.

        Args:
            target: Stage 3 DocumentPackageResult, Applicant model, or raw data dict.
            applicant_profile: Optional reference Applicant model.

        Returns:
            Structured AnomalyResult detailing score, severity, flags, and missing evidence.
        """
        return self.detector.detect_anomalies(
            target=target, applicant_profile=applicant_profile
        )
