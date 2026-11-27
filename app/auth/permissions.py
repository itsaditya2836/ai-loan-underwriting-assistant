"""Role-Based Access Control (RBAC) permission matrix and enforcement.

Defines:
- Permission enum covering all protected operations.
- Role-to-permission mapping for Administrator, Loan Officer, Underwriter, Supervisor.
- Maker-Checker constraint helpers (no self-approval, no self-review).
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, Optional

from app.auth.models import Role


class Permission(str, Enum):
    """Granular permissions for the underwriting system."""

    # User management
    USER_CREATE = "USER_CREATE"
    USER_UPDATE = "USER_UPDATE"
    USER_VIEW = "USER_VIEW"
    USER_DEACTIVATE = "USER_DEACTIVATE"
    ROLE_ASSIGN = "ROLE_ASSIGN"

    # Applicant management
    APPLICANT_CREATE = "APPLICANT_CREATE"
    APPLICANT_VIEW_OWN = "APPLICANT_VIEW_OWN"
    APPLICANT_VIEW_ALL = "APPLICANT_VIEW_ALL"

    # Document management
    DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
    DOCUMENT_VIEW = "DOCUMENT_VIEW"

    # Underwriting pipeline
    UNDERWRITING_INITIATE = "UNDERWRITING_INITIATE"
    UNDERWRITING_VIEW_RESULTS = "UNDERWRITING_VIEW_RESULTS"

    # Human review
    REVIEW_VIEW_ASSIGNED = "REVIEW_VIEW_ASSIGNED"
    REVIEW_VIEW_ALL = "REVIEW_VIEW_ALL"
    REVIEW_SUBMIT_DECISION = "REVIEW_SUBMIT_DECISION"
    REVIEW_REQUEST_INFO = "REVIEW_REQUEST_INFO"
    REVIEW_RETURN_INVESTIGATION = "REVIEW_RETURN_INVESTIGATION"
    REVIEW_CORRECT_DECISION = "REVIEW_CORRECT_DECISION"

    # Audit
    AUDIT_VIEW_ALL = "AUDIT_VIEW_ALL"
    AUDIT_VIEW_OWN = "AUDIT_VIEW_OWN"

    # Settings
    SETTINGS_VIEW = "SETTINGS_VIEW"
    SETTINGS_MODIFY = "SETTINGS_MODIFY"


# ---------------------------------------------------------------------------
# Role → Permission Matrix
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: Dict[Role, FrozenSet[Permission]] = {
    Role.ADMINISTRATOR: frozenset(Permission),  # All permissions
    Role.LOAN_OFFICER: frozenset(
        {
            Permission.APPLICANT_CREATE,
            Permission.APPLICANT_VIEW_OWN,
            Permission.DOCUMENT_UPLOAD,
            Permission.DOCUMENT_VIEW,
            Permission.UNDERWRITING_INITIATE,
            Permission.UNDERWRITING_VIEW_RESULTS,
            Permission.AUDIT_VIEW_OWN,
        }
    ),
    Role.UNDERWRITER: frozenset(
        {
            Permission.APPLICANT_VIEW_ALL,
            Permission.DOCUMENT_VIEW,
            Permission.UNDERWRITING_VIEW_RESULTS,
            Permission.REVIEW_VIEW_ASSIGNED,
            Permission.REVIEW_SUBMIT_DECISION,
            Permission.REVIEW_REQUEST_INFO,
            Permission.REVIEW_RETURN_INVESTIGATION,
            Permission.AUDIT_VIEW_OWN,
        }
    ),
    Role.SUPERVISOR: frozenset(
        {
            Permission.APPLICANT_VIEW_ALL,
            Permission.DOCUMENT_VIEW,
            Permission.UNDERWRITING_VIEW_RESULTS,
            Permission.REVIEW_VIEW_ALL,
            Permission.REVIEW_SUBMIT_DECISION,
            Permission.REVIEW_REQUEST_INFO,
            Permission.REVIEW_RETURN_INVESTIGATION,
            Permission.REVIEW_CORRECT_DECISION,
            Permission.AUDIT_VIEW_ALL,
        }
    ),
}


def get_role_permissions(role: Role) -> FrozenSet[Permission]:
    """Return the permission set for a given role."""
    return ROLE_PERMISSIONS.get(role, frozenset())


def check_permission(role: Role, permission: Permission) -> bool:
    """Check whether a role has a specific permission."""
    return permission in get_role_permissions(role)


class MakerCheckerError(ValueError):
    """Raised when a Maker-Checker constraint is violated."""


def enforce_not_self_review(
    reviewer_user_id: str,
    submitter_user_id: Optional[str],
    *,
    operation: str = "review",
) -> None:
    """Enforce that a user cannot review their own submission.

    Args:
        reviewer_user_id: Authenticated user attempting the review.
        submitter_user_id: User who submitted the application or initiated underwriting.
        operation: Description of the blocked operation for the error message.

    Raises:
        MakerCheckerError: If reviewer and submitter are the same user.
    """
    if submitter_user_id and reviewer_user_id and reviewer_user_id == submitter_user_id:
        raise MakerCheckerError(
            f"Maker-Checker violation: User '{reviewer_user_id}' cannot {operation} "
            f"their own submission."
        )


def enforce_correction_requires_supervisor(role: Role) -> None:
    """Enforce that only Supervisors (or Administrators) can perform decision corrections.

    Raises:
        MakerCheckerError: If the user's role does not have REVIEW_CORRECT_DECISION.
    """
    if not check_permission(role, Permission.REVIEW_CORRECT_DECISION):
        raise MakerCheckerError(
            f"Decision corrections require Supervisor or Administrator privileges. "
            f"Current role '{role.value}' does not have REVIEW_CORRECT_DECISION permission."
        )


__all__ = [
    "MakerCheckerError",
    "Permission",
    "ROLE_PERMISSIONS",
    "check_permission",
    "enforce_correction_requires_supervisor",
    "enforce_not_self_review",
    "get_role_permissions",
]
