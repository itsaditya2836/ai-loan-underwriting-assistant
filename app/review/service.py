"""Server-Side Human Underwriter Review Workflow, Lifecycle & Audit Service (Stage 6).

Enforces:
- Strict separation between AI recommendation, pipeline status, and human review status
- Validated server-side state transitions via ALLOWED_REVIEW_TRANSITIONS
- Mandatory attribution, reasons, comments length bounds, and conditional fields
- Linked correction events when modifying prior terminal human decisions
- Duplicate submission prevention and append-only SQLite persistence
- Fail-safe DB error reporting without falsely claiming persistence success
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.database.audit import (
    get_audit_run_by_id,
    get_latest_runs_per_application,
)
from app.database.reviews import (
    ConcurrentReviewConflictError,
    find_duplicate_review_submission,
    get_human_review_by_id,
    get_latest_review_for_application,
    get_latest_review_for_run,
    get_review_history_for_application,
    get_review_history_for_run,
    init_reviews_table,
    insert_human_review_event,
)
from app.document_processing.security import mask_sensitive_text
from app.schemas.review import (
    ACTION_TO_TARGET_STATUS,
    ALLOWED_REVIEW_TRANSITIONS,
    CORRECTION_ALLOWED_TARGETS,
    HumanReviewAction,
    HumanReviewSubmission,
    ReviewStatus,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)

_REVIEWER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._() -]{2,64}$")
MAX_COMMENTS_LENGTH = 2000
MAX_REASON_LENGTH = 500
MAX_DETAIL_LENGTH = 1000


class InvalidReviewSubmissionError(ValueError):
    """Raised when human review input fails schema or business validation."""


class InvalidReviewTransitionError(ValueError):
    """Raised when a requested review status transition violates lifecycle rules."""


class DuplicateReviewSubmissionError(ValueError):
    """Raised when an identical review action payload was already recorded."""


def _sanitize_text(val: Optional[str], *, mask: bool = False) -> Optional[str]:
    """Strip control whitespace and optionally mask sensitive digits/identifiers."""
    if val is None:
        return None
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(val)).strip()
    if not cleaned:
        return None
    return mask_sensitive_text(cleaned) if mask else cleaned


def validate_review_transition(
    previous_status: ReviewStatus,
    target_status: ReviewStatus,
    *,
    is_correction: bool = False,
    parent_review_id: Optional[str] = None,
    correction_explanation: Optional[str] = None,
) -> None:
    """Validate allowed review lifecycle transitions explicitly."""
    if previous_status in {ReviewStatus.APPROVED, ReviewStatus.REJECTED}:
        if not is_correction:
            raise InvalidReviewTransitionError(
                f"Cannot transition from terminal status '{previous_status.value}' to "
                f"'{target_status.value}' without an explicit linked correction."
            )
        if not parent_review_id or not parent_review_id.strip():
            raise InvalidReviewTransitionError(
                "A decision correction requires linking parent_review_id to the prior review record."
            )
        if not correction_explanation or len(correction_explanation.strip()) < 5:
            raise InvalidReviewTransitionError(
                "A decision correction requires a descriptive correction_explanation (at least 5 characters)."
            )
        if target_status not in CORRECTION_ALLOWED_TARGETS:
            raise InvalidReviewTransitionError(
                f"Target status '{target_status.value}' is not valid for a linked correction."
            )
        return

    if is_correction:
        if not parent_review_id or not parent_review_id.strip():
            raise InvalidReviewTransitionError(
                "A linked correction requires parent_review_id."
            )
        if not correction_explanation or len(correction_explanation.strip()) < 5:
            raise InvalidReviewTransitionError(
                "A linked correction requires correction_explanation (at least 5 characters)."
            )
        if target_status not in CORRECTION_ALLOWED_TARGETS:
            raise InvalidReviewTransitionError(
                f"Invalid correction target status: {target_status.value}"
            )
        return

    if previous_status == target_status:
        raise InvalidReviewTransitionError(
            f"Case is already in review status '{previous_status.value}'."
        )

    allowed = ALLOWED_REVIEW_TRANSITIONS.get(previous_status, set())
    if target_status not in allowed:
        raise InvalidReviewTransitionError(
            f"Transition '{previous_status.value}' -> '{target_status.value}' is not permitted."
        )


def compute_review_submission_hash(payload: Dict[str, Any]) -> str:
    """Compute canonical SHA-256 fingerprint preventing accidental rerun duplicates."""
    canonical = {
        "source_run_id": payload.get("source_run_id"),
        "application_id": payload.get("application_id"),
        "action": payload.get("action"),
        "reviewer_id": payload.get("reviewer_id"),
        "decision_reason": payload.get("decision_reason"),
        "comments": payload.get("comments"),
        "additional_info_request": payload.get("additional_info_request"),
        "additional_info_response": payload.get("additional_info_response"),
        "investigation_instructions": payload.get("investigation_instructions"),
        "previous_review_status": payload.get("previous_review_status"),
        "is_correction": bool(payload.get("is_correction", False)),
        "parent_review_id": payload.get("parent_review_id"),
        "correction_explanation": payload.get("correction_explanation"),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True).encode("utf-8")
    ).hexdigest()


def validate_and_prepare_review_event(
    submission: HumanReviewSubmission | Dict[str, Any],
) -> Dict[str, Any]:
    """Validate submission server-side against run history, rules, and bounds."""
    if isinstance(submission, dict):
        raw = dict(submission)
    else:
        raw = submission.model_dump()

    source_run_id = _sanitize_text(raw.get("source_run_id"))
    application_id = _sanitize_text(raw.get("application_id"))
    if not source_run_id:
        raise InvalidReviewSubmissionError("Source underwriting run_id is required.")
    if not application_id:
        raise InvalidReviewSubmissionError("Application reference ID is required.")

    run_row = get_audit_run_by_id(source_run_id)
    if run_row is None:
        raise InvalidReviewSubmissionError(
            f"Underwriting run '{source_run_id}' does not exist in audit database."
        )
    if run_row["application_id"] != application_id:
        raise InvalidReviewSubmissionError(
            f"Run '{source_run_id}' belongs to '{run_row['application_id']}', "
            f"not '{application_id}'."
        )

    raw_action = raw.get("action")
    try:
        action = (
            raw_action
            if isinstance(raw_action, HumanReviewAction)
            else HumanReviewAction(str(raw_action))
        )
    except ValueError as exc:
        raise InvalidReviewSubmissionError(
            f"Unsupported human review action: '{raw_action}'."
        ) from exc

    reviewer_id = _sanitize_text(raw.get("reviewer_id"))
    if not reviewer_id:
        raise InvalidReviewSubmissionError("Reviewer identifier is mandatory.")
    if not _REVIEWER_ID_PATTERN.fullmatch(reviewer_id):
        raise InvalidReviewSubmissionError(
            "Reviewer identifier must be 2–64 characters using letters, digits, spaces, '.', '-', or '_'."
        )

    decision_reason = _sanitize_text(raw.get("decision_reason"), mask=True)
    if not decision_reason or len(decision_reason) < 5:
        raise InvalidReviewSubmissionError(
            "A mandatory decision reason (at least 5 characters) is required."
        )
    if len(decision_reason) > MAX_REASON_LENGTH:
        raise InvalidReviewSubmissionError(
            f"Decision reason cannot exceed {MAX_REASON_LENGTH} characters."
        )

    comments_raw = raw.get("comments")
    comments = _sanitize_text(comments_raw, mask=True)
    if comments and len(comments) > MAX_COMMENTS_LENGTH:
        raise InvalidReviewSubmissionError(
            f"Comments cannot exceed {MAX_COMMENTS_LENGTH} characters."
        )

    add_info_req = _sanitize_text(raw.get("additional_info_request"), mask=True)
    add_info_resp = _sanitize_text(raw.get("additional_info_response"), mask=True)
    inv_instr = _sanitize_text(raw.get("investigation_instructions"), mask=True)
    corr_expl = _sanitize_text(raw.get("correction_explanation"), mask=True)

    if add_info_req and len(add_info_req) > MAX_DETAIL_LENGTH:
        raise InvalidReviewSubmissionError(
            f"Additional information request exceeds {MAX_DETAIL_LENGTH} characters."
        )
    if add_info_resp and len(add_info_resp) > MAX_DETAIL_LENGTH:
        raise InvalidReviewSubmissionError(
            f"Additional information response exceeds {MAX_DETAIL_LENGTH} characters."
        )
    if inv_instr and len(inv_instr) > MAX_DETAIL_LENGTH:
        raise InvalidReviewSubmissionError(
            f"Investigation instructions exceed {MAX_DETAIL_LENGTH} characters."
        )

    if action == HumanReviewAction.REQUEST_ADDITIONAL_INFO and (
        not add_info_req or len(add_info_req) < 5
    ):
        raise InvalidReviewSubmissionError(
            "Requesting additional information requires a clear description of what is needed (at least 5 characters)."
        )

    if action == HumanReviewAction.RETURN_FOR_INVESTIGATION and (
        not inv_instr or len(inv_instr) < 5
    ):
        raise InvalidReviewSubmissionError(
            "Returning a case for investigation requires investigation instructions (at least 5 characters)."
        )

    requires_confirm = action in {
        HumanReviewAction.APPROVE,
        HumanReviewAction.REJECT,
        HumanReviewAction.REQUEST_ADDITIONAL_INFO,
        HumanReviewAction.RETURN_FOR_INVESTIGATION,
    }
    if requires_confirm and not bool(raw.get("confirmed", False)):
        raise InvalidReviewSubmissionError(
            "Explicit confirmation is required before recording this review decision."
        )

    # Determine authoritative previous review status from DB history for this run
    latest_review = get_latest_review_for_run(source_run_id)
    prev_status = (
        ReviewStatus(latest_review["new_review_status"])
        if latest_review is not None
        else ReviewStatus.PENDING
    )

    # Optimistic concurrency guard: fail if caller expected a different review status
    expected_prev_raw = raw.get("expected_previous_status")
    if expected_prev_raw is not None:
        expected_prev = (
            expected_prev_raw
            if isinstance(expected_prev_raw, ReviewStatus)
            else ReviewStatus(str(expected_prev_raw))
        )
        if prev_status != expected_prev:
            raise ConcurrentReviewConflictError(
                f"Optimistic concurrency check failed on run '{source_run_id}': "
                f"expected status '{expected_prev.value}', found '{prev_status.value}'."
            )

    target_status = ACTION_TO_TARGET_STATUS[action]

    is_correction = bool(raw.get("is_correction", False))
    parent_review_id = _sanitize_text(raw.get("parent_review_id"))
    if is_correction and not parent_review_id and latest_review is not None:
        parent_review_id = latest_review["review_id"]
    if parent_review_id:
        parent_row = get_human_review_by_id(parent_review_id)
        if parent_row is None or parent_row["source_run_id"] != source_run_id:
            raise InvalidReviewSubmissionError(
                f"Parent review reference '{parent_review_id}' does not match source run '{source_run_id}'."
            )

    validate_review_transition(
        prev_status,
        target_status,
        is_correction=is_correction,
        parent_review_id=parent_review_id,
        correction_explanation=corr_expl,
    )

    if action == HumanReviewAction.APPROVE:
        human_decision: Optional[str] = "APPROVE"
    elif action == HumanReviewAction.REJECT:
        human_decision = "REJECT"
    else:
        # Non-terminal actions (START_REVIEW, REQUEST_ADDITIONAL_INFO, RETURN_FOR_INVESTIGATION, RETURN_TO_PENDING)
        # MUST NOT be treated as approvals or rejections.
        human_decision = None

    reviewer_user_id = _sanitize_text(raw.get("reviewer_user_id"))
    reviewer_username = _sanitize_text(raw.get("reviewer_username"))
    reviewer_role = _sanitize_text(raw.get("reviewer_role"))

    event_payload = {
        "source_run_id": source_run_id,
        "application_id": application_id,
        "applicant_id": application_id,
        "original_ai_recommendation": run_row["recommendation"],
        "original_pipeline_status": run_row["pipeline_status"],
        "action": action.value,
        "human_decision": human_decision,
        "reviewer_id": reviewer_id,
        "reviewer_user_id": reviewer_user_id,
        "reviewer_username": reviewer_username,
        "reviewer_role": reviewer_role,
        "decision_reason": decision_reason,
        "comments": comments,
        "additional_info_request": add_info_req,
        "additional_info_response": add_info_resp,
        "investigation_instructions": inv_instr,
        "previous_review_status": prev_status.value,
        "new_review_status": target_status.value,
        "is_correction": is_correction,
        "parent_review_id": parent_review_id,
        "correction_explanation": corr_expl,
        "event_type": "HUMAN_REVIEW_EVENT",
        "review_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    sub_hash = compute_review_submission_hash(event_payload)
    event_payload["submission_hash"] = sub_hash

    existing_dup = find_duplicate_review_submission(sub_hash)
    if existing_dup is not None:
        raise DuplicateReviewSubmissionError(
            f"Duplicate human review submission blocked: identical decision already recorded as '{existing_dup['review_id']}'."
        )

    return event_payload


def submit_human_review(
    submission: HumanReviewSubmission | Dict[str, Any],
) -> Dict[str, Any]:
    """Validate and persist an append-only human underwriter review event."""
    init_reviews_table()
    payload = validate_and_prepare_review_event(submission)
    return insert_human_review_event(payload)


def submit_human_review_safe(
    submission: HumanReviewSubmission | Dict[str, Any],
) -> Dict[str, Any]:
    """Safely validate and persist a human review event without raising UI-crashing exceptions."""
    try:
        saved = submit_human_review(submission)
        return {
            "saved": True,
            "duplicate_blocked": False,
            "conflict": False,
            "event": saved,
            "error": None,
        }
    except DuplicateReviewSubmissionError as exc:
        return {
            "saved": False,
            "duplicate_blocked": True,
            "conflict": False,
            "event": None,
            "error": str(exc),
        }
    except ConcurrentReviewConflictError as exc:
        return {
            "saved": False,
            "duplicate_blocked": False,
            "conflict": True,
            "event": None,
            "error": str(exc),
        }
    except (InvalidReviewSubmissionError, InvalidReviewTransitionError) as exc:
        return {
            "saved": False,
            "duplicate_blocked": False,
            "conflict": False,
            "event": None,
            "error": str(exc),
        }
    except Exception as exc:
        logger.error("Human review persistence failed: %s", exc)
        return {
            "saved": False,
            "duplicate_blocked": False,
            "conflict": False,
            "event": None,
            "error": f"Database persistence failed: {exc}",
        }


def record_additional_info_return(
    *,
    source_run_id: str,
    application_id: str,
    reviewer_id: str,
    info_response: str,
    reason: Optional[str] = None,
    reviewer_user_id: Optional[str] = None,
    reviewer_username: Optional[str] = None,
    reviewer_role: Optional[str] = None,
) -> Dict[str, Any]:
    """Return an ADDITIONAL_INFO_REQUESTED / INVESTIGATION_REQUIRED case cleanly to PENDING without rerunning AI."""
    clean_resp = _sanitize_text(info_response, mask=True)
    if not clean_resp or len(clean_resp) < 5:
        return {
            "saved": False,
            "duplicate_blocked": False,
            "conflict": False,
            "event": None,
            "error": "Please provide additional information summary/details (at least 5 characters) before returning case to queue.",
        }
    payload = HumanReviewSubmission(
        source_run_id=source_run_id,
        application_id=application_id,
        action=HumanReviewAction.RETURN_TO_PENDING,
        reviewer_id=reviewer_id,
        reviewer_user_id=reviewer_user_id,
        reviewer_username=reviewer_username,
        reviewer_role=reviewer_role,
        decision_reason=reason
        or "Additional requested information recorded; returned to pending review queue.",
        additional_info_response=clean_resp,
        confirmed=True,
    )
    return submit_human_review_safe(payload)


def build_attention_triggers(
    run_row: Dict[str, Any],
    latest_review: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Identify objective backend reasons why a run/case requires underwriter attention."""
    triggers: List[str] = []
    rec = run_row.get("recommendation")
    pipe = run_row.get("pipeline_status")
    snap = run_row.get("details_snapshot") or {}
    doc_status = snap.get("document_verification_status") or (
        "INCOMPLETE"
        if int(run_row.get("documents_missing_count") or 0) > 0
        else "RECORDED"
    )
    review_status = (
        latest_review["new_review_status"]
        if latest_review is not None
        else ReviewStatus.PENDING.value
    )

    if pipe == "FAILED":
        triggers.append("PIPELINE_FAILED")
    elif pipe == "PARTIAL_SUCCESS":
        triggers.append("PARTIAL_PIPELINE")

    if rec == "MANUAL_REVIEW":
        triggers.append("AI_MANUAL_REVIEW")

    if int(run_row.get("documents_missing_count") or 0) > 0 or doc_status in {
        "INCOMPLETE",
        "UNVERIFIED",
        "FAILED",
        "UNAVAILABLE",
    }:
        triggers.append("INCOMPLETE_OR_UNVERIFIED_DOCS")

    if run_row.get("consistency_conflicts"):
        triggers.append("CONSISTENCY_CONFLICTS")

    agent_statuses = run_row.get("agent_statuses") or {}
    if (
        not run_row.get("risk_score_available", True)
        or run_row.get("risk_category") == "UNAVAILABLE"
        or run_row.get("anomaly_severity") == "UNAVAILABLE"
        or run_row.get("eligibility_status") == "UNAVAILABLE"
        or any(
            (v.get("status") if isinstance(v, dict) else v) in {"FAILED", "SKIPPED"}
            for v in agent_statuses.values()
        )
    ):
        triggers.append("UNAVAILABLE_OR_FAILED_AGENT")

    if review_status == ReviewStatus.ADDITIONAL_INFO_REQUESTED.value:
        triggers.append("ADDITIONAL_INFO_REQUESTED")
    elif review_status == ReviewStatus.INVESTIGATION_REQUIRED.value:
        triggers.append("INVESTIGATION_REQUIRED")
    elif review_status in {ReviewStatus.PENDING.value, ReviewStatus.IN_REVIEW.value}:
        triggers.append("AWAITING_HUMAN_DECISION")

    return triggers


def _is_attention_queue_case(
    review_status: str,
    triggers: List[str],
    include_finalized: bool,
) -> bool:
    """Return True if case requires human attention or finalized cases were requested."""
    if include_finalized:
        return True
    if review_status in {
        ReviewStatus.PENDING.value,
        ReviewStatus.IN_REVIEW.value,
        ReviewStatus.ADDITIONAL_INFO_REQUESTED.value,
        ReviewStatus.INVESTIGATION_REQUIRED.value,
    }:
        return True
    return bool(
        set(triggers)
        & {
            "PIPELINE_FAILED",
            "PARTIAL_PIPELINE",
            "AI_MANUAL_REVIEW",
            "INCOMPLETE_OR_UNVERIFIED_DOCS",
            "CONSISTENCY_CONFLICTS",
            "UNAVAILABLE_OR_FAILED_AGENT",
        }
        and review_status
        not in {ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value}
    )


def get_case_review_summary(
    application_id: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return strictly separated AI recommendation, pipeline status, and human review state."""
    init_reviews_table()
    target_run: Optional[Dict[str, Any]] = None
    if run_id:
        target_run = get_audit_run_by_id(run_id)
    if target_run is None and application_id:
        latest_runs = get_latest_runs_per_application(exclude_failed=False, limit=1000)
        for r in latest_runs:
            if r["application_id"] == application_id:
                target_run = r
                break

    if target_run is None:
        return {
            "has_run": False,
            "source_run_id": None,
            "ai_recommendation": "NOT_EVALUATED",
            "pipeline_status": "NOT_RUN",
            "human_review_status": ReviewStatus.PENDING.value,
            "human_decision": None,
            "latest_review": None,
            "review_history": get_review_history_for_application(application_id),
        }

    latest_rev = get_latest_review_for_run(target_run["run_id"])
    # Also fetch application-wide latest request details if run history is empty after document resubmit
    app_history = get_review_history_for_application(application_id)
    run_history = get_review_history_for_run(target_run["run_id"])

    review_status = (
        latest_rev["new_review_status"]
        if latest_rev is not None
        else ReviewStatus.PENDING.value
    )
    human_decision = (
        latest_rev.get("human_decision") if latest_rev is not None else None
    )
    if review_status not in {ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value}:
        human_decision = None

    return {
        "has_run": True,
        "source_run_id": target_run["run_id"],
        "ai_recommendation": target_run["recommendation"],
        "pipeline_status": target_run["pipeline_status"],
        "human_review_status": review_status,
        "human_decision": human_decision,
        "latest_review": latest_rev,
        "run_review_history": run_history,
        "application_review_history": app_history,
        "latest_application_review": get_latest_review_for_application(application_id),
    }


def list_review_queue(
    *,
    applicant_catalog_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    application_id_filter: Optional[str] = None,
    ai_recommendation_filter: Optional[str] = None,
    pipeline_status_filter: Optional[str] = None,
    risk_category_filter: Optional[str] = None,
    review_status_filter: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_finalized: bool = True,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Build deduplicated queue items joining each application's latest AI run and latest human review."""
    init_reviews_table()
    latest_runs = get_latest_runs_per_application(exclude_failed=False, limit=limit)
    catalog_map = applicant_catalog_by_id or {}

    queue_items: List[Dict[str, Any]] = []
    seen_apps: Set[str] = set()
    for run in latest_runs:
        aid = run["application_id"]
        if aid in seen_apps:
            continue
        seen_apps.add(aid)

        latest_rev = get_latest_review_for_run(run["run_id"])
        review_status = (
            latest_rev["new_review_status"]
            if latest_rev is not None
            else ReviewStatus.PENDING.value
        )
        human_decision = (
            latest_rev.get("human_decision")
            if latest_rev is not None
            and review_status
            in {ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value}
            else None
        )
        triggers = build_attention_triggers(run, latest_rev)

        if not _is_attention_queue_case(review_status, triggers, include_finalized):
            continue

        app_info = catalog_map.get(aid, {})
        app_name = str(app_info.get("name") or "Unknown Applicant")
        if application_id_filter:
            needle = application_id_filter.strip().lower()
            if needle not in aid.lower() and needle not in app_name.lower():
                continue

        if ai_recommendation_filter and ai_recommendation_filter != "ALL":
            if run.get("recommendation") != ai_recommendation_filter:
                continue

        if pipeline_status_filter and pipeline_status_filter != "ALL":
            if run.get("pipeline_status") != pipeline_status_filter:
                continue

        if risk_category_filter and risk_category_filter != "ALL":
            if run.get("risk_category") != risk_category_filter:
                continue

        if review_status_filter and review_status_filter != "ALL":
            if review_status_filter == "NEEDS_HUMAN_ACTION":
                if review_status not in {
                    ReviewStatus.PENDING.value,
                    ReviewStatus.IN_REVIEW.value,
                    ReviewStatus.ADDITIONAL_INFO_REQUESTED.value,
                    ReviewStatus.INVESTIGATION_REQUIRED.value,
                }:
                    continue
            elif review_status != review_status_filter:
                continue

        run_date = str(run.get("timestamp", ""))[:10]
        if start_date and run_date < start_date:
            continue
        if end_date and run_date > end_date:
            continue

        queue_items.append(
            {
                "applicant_id": aid,
                "applicant_name": app_name,
                "source_run_id": run["run_id"],
                "submission_timestamp": run.get("timestamp", ""),
                "ai_recommendation": run.get("recommendation"),
                "pipeline_status": run.get("pipeline_status"),
                "risk_category": run.get("risk_category"),
                "risk_score": run.get("risk_score"),
                "anomaly_severity": run.get("anomaly_severity"),
                "eligibility_status": run.get("eligibility_status"),
                "human_review_status": review_status,
                "human_decision": human_decision,
                "latest_reviewer_id": (
                    latest_rev.get("reviewer_id") if latest_rev else None
                ),
                "latest_review_id": latest_rev.get("review_id") if latest_rev else None,
                "latest_review_timestamp": (
                    latest_rev.get("review_timestamp") if latest_rev else None
                ),
                "additional_info_request": (
                    latest_rev.get("additional_info_request") if latest_rev else None
                ),
                "investigation_instructions": (
                    latest_rev.get("investigation_instructions") if latest_rev else None
                ),
                "attention_triggers": triggers,
                "run_record": run,
                "latest_review": latest_rev,
                "applicant_record": app_info,
            }
        )

    return queue_items


def compute_review_queue_metrics(queue_items: List[Dict[str, Any]]) -> Dict[str, int]:
    """Compute honest summary counts while keeping failed AI runs distinct from completed decisions."""
    counts = {
        "total_cases": len(queue_items),
        "pending_reviews": 0,
        "in_progress": 0,
        "approved_by_underwriter": 0,
        "rejected_by_underwriter": 0,
        "additional_info_requested": 0,
        "investigation_required": 0,
        "completed_ai_decisions": 0,
        "failed_pipeline_runs": 0,
    }
    for item in queue_items:
        st = item.get("human_review_status", ReviewStatus.PENDING.value)
        pipe = item.get("pipeline_status")
        if pipe == "FAILED":
            counts["failed_pipeline_runs"] += 1
        else:
            counts["completed_ai_decisions"] += 1

        if st == ReviewStatus.PENDING.value:
            counts["pending_reviews"] += 1
        elif st == ReviewStatus.IN_REVIEW.value:
            counts["in_progress"] += 1
        elif st == ReviewStatus.APPROVED.value:
            counts["approved_by_underwriter"] += 1
        elif st == ReviewStatus.REJECTED.value:
            counts["rejected_by_underwriter"] += 1
        elif st == ReviewStatus.ADDITIONAL_INFO_REQUESTED.value:
            counts["additional_info_requested"] += 1
        elif st == ReviewStatus.INVESTIGATION_REQUIRED.value:
            counts["investigation_required"] += 1

    return counts
