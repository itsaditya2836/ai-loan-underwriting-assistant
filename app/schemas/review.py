"""Pydantic Data Contracts for Stage 6 Human Underwriter Review & Audit.

Defines strict enums and schemas separating:
- AI Recommendations (immutable Stage 4/8 DecisionOutcome)
- Pipeline Execution Status (OrchestrationStatus)
- Human Review Lifecycle Status (ReviewStatus)
- Append-Only Human Review Events (HumanReviewEvent)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional, Set

from pydantic import BaseModel, Field


class ReviewStatus(str, Enum):
    """Explicit human underwriter case review lifecycle states."""

    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ADDITIONAL_INFO_REQUESTED = "ADDITIONAL_INFO_REQUESTED"
    INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"


class HumanReviewAction(str, Enum):
    """Permitted human underwriter actions recorded in the review audit ledger."""

    START_REVIEW = "START_REVIEW"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_ADDITIONAL_INFO = "REQUEST_ADDITIONAL_INFO"
    RETURN_FOR_INVESTIGATION = "RETURN_FOR_INVESTIGATION"
    RETURN_TO_PENDING = "RETURN_TO_PENDING"


ACTION_TO_TARGET_STATUS: Dict[HumanReviewAction, ReviewStatus] = {
    HumanReviewAction.START_REVIEW: ReviewStatus.IN_REVIEW,
    HumanReviewAction.APPROVE: ReviewStatus.APPROVED,
    HumanReviewAction.REJECT: ReviewStatus.REJECTED,
    HumanReviewAction.REQUEST_ADDITIONAL_INFO: ReviewStatus.ADDITIONAL_INFO_REQUESTED,
    HumanReviewAction.RETURN_FOR_INVESTIGATION: ReviewStatus.INVESTIGATION_REQUIRED,
    HumanReviewAction.RETURN_TO_PENDING: ReviewStatus.PENDING,
}

# Non-correction forward/workflow transitions allowed from each current state.
ALLOWED_REVIEW_TRANSITIONS: Dict[ReviewStatus, Set[ReviewStatus]] = {
    ReviewStatus.PENDING: {
        ReviewStatus.IN_REVIEW,
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.ADDITIONAL_INFO_REQUESTED,
        ReviewStatus.INVESTIGATION_REQUIRED,
    },
    ReviewStatus.IN_REVIEW: {
        ReviewStatus.PENDING,
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.ADDITIONAL_INFO_REQUESTED,
        ReviewStatus.INVESTIGATION_REQUIRED,
    },
    ReviewStatus.ADDITIONAL_INFO_REQUESTED: {
        ReviewStatus.PENDING,
        ReviewStatus.IN_REVIEW,
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.INVESTIGATION_REQUIRED,
    },
    ReviewStatus.INVESTIGATION_REQUIRED: {
        ReviewStatus.PENDING,
        ReviewStatus.IN_REVIEW,
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.ADDITIONAL_INFO_REQUESTED,
    },
    # Terminal decisions cannot mutate implicitly without an explicit linked correction.
    ReviewStatus.APPROVED: set(),
    ReviewStatus.REJECTED: set(),
}

# Explicit correction transitions permitted ONLY when is_correction=True with parent link + explanation.
CORRECTION_ALLOWED_TARGETS: Set[ReviewStatus] = {
    ReviewStatus.APPROVED,
    ReviewStatus.REJECTED,
    ReviewStatus.ADDITIONAL_INFO_REQUESTED,
    ReviewStatus.INVESTIGATION_REQUIRED,
    ReviewStatus.PENDING,
    ReviewStatus.IN_REVIEW,
}


class HumanReviewSubmission(BaseModel):
    """Validated input request from UI or API callers to append a review event."""

    source_run_id: str = Field(..., min_length=1)
    application_id: str = Field(..., min_length=1)
    action: HumanReviewAction
    reviewer_id: str = Field(..., min_length=2, max_length=64)
    reviewer_user_id: Optional[str] = Field(default=None, max_length=64)
    reviewer_username: Optional[str] = Field(default=None, max_length=64)
    reviewer_role: Optional[str] = Field(default=None, max_length=32)
    expected_previous_status: Optional[ReviewStatus] = Field(default=None)
    decision_reason: str = Field(..., min_length=5, max_length=500)
    comments: Optional[str] = Field(default=None, max_length=2000)
    additional_info_request: Optional[str] = Field(default=None, max_length=1000)
    additional_info_response: Optional[str] = Field(default=None, max_length=1000)
    investigation_instructions: Optional[str] = Field(default=None, max_length=1000)
    is_correction: bool = Field(default=False)
    parent_review_id: Optional[str] = Field(default=None)
    correction_explanation: Optional[str] = Field(default=None, max_length=500)
    confirmed: bool = Field(default=False)


class HumanReviewEvent(BaseModel):
    """Immutable, append-only human underwriter review audit record."""

    review_id: str
    source_run_id: str
    application_id: str
    applicant_id: str
    original_ai_recommendation: str
    original_pipeline_status: str
    action: HumanReviewAction
    human_decision: Optional[str] = Field(
        default=None,
        description="Final human lending outcome (APPROVE or REJECT) ONLY when terminal decision issued; None otherwise.",
    )
    reviewer_id: str
    reviewer_user_id: Optional[str] = None
    reviewer_username: Optional[str] = None
    reviewer_role: Optional[str] = None
    decision_reason: str
    comments: Optional[str] = None
    additional_info_request: Optional[str] = None
    additional_info_response: Optional[str] = None
    investigation_instructions: Optional[str] = None
    previous_review_status: ReviewStatus
    new_review_status: ReviewStatus
    is_correction: bool = False
    parent_review_id: Optional[str] = None
    correction_explanation: Optional[str] = None
    submission_hash: str
    review_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    event_type: str = "HUMAN_REVIEW_EVENT"


__all__ = [
    "ACTION_TO_TARGET_STATUS",
    "ALLOWED_REVIEW_TRANSITIONS",
    "CORRECTION_ALLOWED_TARGETS",
    "HumanReviewAction",
    "HumanReviewEvent",
    "HumanReviewSubmission",
    "ReviewStatus",
]
