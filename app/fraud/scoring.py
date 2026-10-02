"""Anomaly Scoring and Severity Aggregation Engine.

Calculates composite anomaly scores (0-100) based on detected flags and rule
weights, assigns aggregate severity levels, and synthesizes human-readable summaries.
"""

from typing import List, Tuple

from app.fraud.rules import AnomalyRulesConfig
from app.schemas.anomaly import AnomalyFlag, AnomalySeverity


class AnomalyScorer:
    """Calculates normalized anomaly scores and assigns composite severity tiers."""

    def __init__(self, config: AnomalyRulesConfig = None) -> None:
        """Initialize the scorer with rule configuration."""
        self.config = config or AnomalyRulesConfig.default_config()

    def calculate_score(
        self, flags: List[AnomalyFlag]
    ) -> Tuple[float, AnomalySeverity]:
        """Compute composite anomaly score and determine overall severity.

        Args:
            flags: List of detected AnomalyFlags.

        Returns:
            Tuple of (anomaly_score, AnomalySeverity).
        """
        if not flags:
            return 0.0, AnomalySeverity.NONE

        total_weight = 0.0
        for flag in flags:
            w = self.config.rule_weights.get(flag.rule_id, 20.0)
            # Escalate weight if individual flag severity is HIGH
            if flag.severity == AnomalySeverity.HIGH:
                w = max(w, 35.0)
            total_weight += w

        anomaly_score = round(min(max(total_weight, 0.0), 100.0), 2)

        # Categorize into overall severity
        if anomaly_score == 0.0:
            severity = AnomalySeverity.NONE
        elif anomaly_score <= 25.0:
            severity = AnomalySeverity.LOW
        elif anomaly_score < 60.0:
            severity = AnomalySeverity.MEDIUM
        else:
            severity = AnomalySeverity.HIGH

        return anomaly_score, severity

    def synthesize_summary(
        self,
        flags: List[AnomalyFlag],
        missing_evidence: List[str],
        severity: AnomalySeverity,
        score: float,
    ) -> str:
        """Generate a transparent explanatory summary of anomaly findings.

        Args:
            flags: Detected anomaly flags.
            missing_evidence: List of missing document types.
            severity: Aggregate severity level.
            score: Composite anomaly score.

        Returns:
            Human-readable summary string.
        """
        lines: List[str] = []

        if not flags and not missing_evidence:
            return "Cross-document verification complete: All submitted documents and declared attributes are consistent with no detected discrepancies."

        if flags:
            lines.append(
                f"Cross-document consistency check identified {len(flags)} material discrepancy(ies) (Composite Anomaly Score: {score:.1f}/100, Severity: {severity.value})."
            )
            for i, f in enumerate(flags, 1):
                lines.append(f"[{f.rule_id}] {f.description}")
        else:
            lines.append(
                "All submitted documents exhibit consistent financial and identity attributes."
            )

        if missing_evidence:
            lines.append(
                f"Notice: Missing document evidence ({', '.join(missing_evidence)}). Incomplete documentation requires verification follow-up but does not constitute an anomaly flag."
            )

        return " ".join(lines)
