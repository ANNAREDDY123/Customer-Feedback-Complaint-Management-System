
from datetime import datetime, timedelta, timezone

from app.models.complaint import (
    Complaint,
    ComplaintPriority,
    ComplaintSeverity,
    ComplaintStatus,
)


SLA_TARGETS = {
    ComplaintPriority.LOW: {
        "response_minutes": 24 * 60,
        "resolution_minutes": 72 * 60,
    },
    ComplaintPriority.MEDIUM: {
        "response_minutes": 8 * 60,
        "resolution_minutes": 48 * 60,
    },
    ComplaintPriority.HIGH: {
        "response_minutes": 2 * 60,
        "resolution_minutes": 24 * 60,
    },
}

CRITICAL_TARGETS = {
    "response_minutes": 30,
    "resolution_minutes": 4 * 60,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_datetime(value: datetime | None) -> datetime | None:
    """Normalize datetimes to UTC for safe comparisons."""
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def get_sla_targets(complaint: Complaint) -> dict[str, int]:
    """Return the configured response and resolution targets."""
    if complaint.severity == ComplaintSeverity.CRITICAL:
        return CRITICAL_TARGETS.copy()

    return SLA_TARGETS[complaint.priority].copy()


def initialize_sla(
    complaint: Complaint,
    start_time: datetime | None = None,
) -> None:
    """Initialize SLA deadlines when a complaint is created."""
    start = normalize_datetime(
        start_time or complaint.created_at
    ) or utc_now()

    targets = get_sla_targets(complaint)

    complaint.response_due_at = start + timedelta(
        minutes=targets["response_minutes"]
    )
    complaint.resolution_due_at = start + timedelta(
        minutes=targets["resolution_minutes"]
    )
    complaint.first_response_at = None
    complaint.sla_response_breached_at = None
    complaint.sla_resolution_breached_at = None


def record_first_response(
    complaint: Complaint,
    response_time: datetime | None = None,
) -> None:
    """Record the first staff response and any late-response breach."""
    if complaint.first_response_at is not None:
        return

    response_time = normalize_datetime(
        response_time or utc_now()
    )
    complaint.first_response_at = response_time

    response_due = normalize_datetime(complaint.response_due_at)

    if (
        response_due is not None
        and response_time > response_due
        and complaint.sla_response_breached_at is None
    ):
        complaint.sla_response_breached_at = response_due


def refresh_sla_breaches(
    complaint: Complaint,
    now: datetime | None = None,
) -> None:
    """Record response and resolution breaches, including late completion."""
    current = normalize_datetime(now or utc_now())

    response_due = normalize_datetime(complaint.response_due_at)
    first_response = normalize_datetime(complaint.first_response_at)

    # A response breach applies when the first response was late,
    # or when the deadline has passed without a first response.
    response_was_late = (
        response_due is not None
        and first_response is not None
        and first_response > response_due
    )
    response_is_overdue = (
        response_due is not None
        and first_response is None
        and current > response_due
    )

    if (
        (response_was_late or response_is_overdue)
        and complaint.sla_response_breached_at is None
    ):
        complaint.sla_response_breached_at = response_due

    resolution_due = normalize_datetime(complaint.resolution_due_at)
    resolved_at = normalize_datetime(complaint.resolved_at)

    # A resolution breach applies if resolution happened after its
    # deadline, or the complaint is still unresolved after the deadline.
    resolution_was_late = (
        resolution_due is not None
        and resolved_at is not None
        and resolved_at > resolution_due
    )
    resolution_is_overdue = (
        resolution_due is not None
        and resolved_at is None
        and complaint.status not in {
            ComplaintStatus.RESOLVED,
            ComplaintStatus.CLOSED,
        }
        and current > resolution_due
    )

    if (
        (resolution_was_late or resolution_is_overdue)
        and complaint.sla_resolution_breached_at is None
    ):
        complaint.sla_resolution_breached_at = resolution_due


def get_sla_status(
    complaint: Complaint,
    now: datetime | None = None,
) -> dict:
    """Return SLA deadlines, breach state and remaining time."""
    current = normalize_datetime(now or utc_now())

    refresh_sla_breaches(complaint, current)

    response_due = normalize_datetime(complaint.response_due_at)
    resolution_due = normalize_datetime(complaint.resolution_due_at)
    first_response = normalize_datetime(complaint.first_response_at)
    resolved_at = normalize_datetime(complaint.resolved_at)

    response_remaining = (
        int((response_due - current).total_seconds())
        if response_due is not None and first_response is None
        else None
    )

    resolution_remaining = (
        int((resolution_due - current).total_seconds())
        if resolution_due is not None
        and resolved_at is None
        and complaint.status not in {
            ComplaintStatus.RESOLVED,
            ComplaintStatus.CLOSED,
        }
        else None
    )

    return {
        "complaint_id": complaint.id,
        "reference_number": complaint.reference_number,
        "priority": complaint.priority.value,
        "severity": complaint.severity.value,
        "status": complaint.status.value,
        "first_response_at": complaint.first_response_at,
        "response_due_at": complaint.response_due_at,
        "resolution_due_at": complaint.resolution_due_at,
        "response_breached": (
            complaint.sla_response_breached_at is not None
        ),
        "resolution_breached": (
            complaint.sla_resolution_breached_at is not None
        ),
        "response_remaining_seconds": response_remaining,
        "resolution_remaining_seconds": resolution_remaining,
    }
