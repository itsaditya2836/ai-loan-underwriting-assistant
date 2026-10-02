"""Decision Reasoning and Explanation Synthesizer.

Translates structured decision reasons, positive factors, and negative factors
into clear, auditable human-readable narrative explanations.
"""

from typing import List

from app.schemas.decision import DecisionOutcome, DecisionReason


class DecisionReasoningSynthesizer:
    """Synthesizes human-readable executive reasoning summaries for underwriting decisions."""

    @staticmethod
    def synthesize_summary(
        application_id: str,
        recommendation: DecisionOutcome,
        confidence: float,
        reasons: List[DecisionReason],
        positive_factors: List[str],
        negative_factors: List[str],
        blocking_factors: List[str],
    ) -> str:
        """Construct an explainable executive reasoning narrative."""
        sentences: List[str] = []

        # 1. Headline Recommendation
        sentences.append(
            f"Underwriting Recommendation for {application_id}: {recommendation.value} "
            f"(Confidence: {confidence:.1f}%)."
        )

        # 2. Recommendation Rationale
        if recommendation == DecisionOutcome.APPROVE:
            sentences.append(
                "The application satisfies all mandatory underwriting eligibility criteria, "
                "demonstrates an acceptable credit risk profile, provides verified document evidence, "
                "and exhibits no high-severity cross-document anomalies."
            )
            if positive_factors:
                sentences.append(f"Key Strengths: {'; '.join(positive_factors[:3])}.")

        elif recommendation == DecisionOutcome.REJECT:
            blocking_reasons = [
                r.description for r in reasons if r.severity == "BLOCKING"
            ]
            if blocking_reasons:
                sentences.append(
                    f"Primary Ineligibility Factor(s): {'; '.join(blocking_reasons)}."
                )
            else:
                sentences.append(
                    "The application failed one or more mandatory underwriting policy criteria."
                )

        elif recommendation == DecisionOutcome.MANUAL_REVIEW:
            review_reasons = [r.description for r in reasons]
            if review_reasons:
                sentences.append(
                    f"Factors Requiring Review: {'; '.join(review_reasons)}."
                )
            else:
                sentences.append(
                    "Available evidence is incomplete, contradictory, or near boundary policy thresholds, "
                    "requiring human underwriter judgment."
                )
            if blocking_factors:
                sentences.append(
                    f"Outstanding Verification Items: {'; '.join(blocking_factors[:2])}."
                )

        # 3. Governance Notice
        sentences.append(
            "Governance Notice: This automated decision-support recommendation does not constitute "
            "a final credit commitment. Final lending authority rests with authorized human underwriters."
        )

        return " ".join(sentences)


__all__ = ["DecisionReasoningSynthesizer"]
