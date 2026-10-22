
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.complaint import (
    ComplaintPriority,
    ComplaintSeverity,
    ComplaintStatus,
)
from app.services.sla import (
    get_sla_status,
    get_sla_targets,
    initialize_sla,
    record_first_response,
    refresh_sla_breaches,
)


BASE_TIME = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


def make_complaint(
    priority=ComplaintPriority.MEDIUM,
    severity=ComplaintSeverity.MEDIUM,
    status=ComplaintStatus.OPEN,
):
    return SimpleNamespace(
        id=1,
        reference_number="CMP-TEST-001",
        priority=priority,
        severity=severity,
        status=status,
        created_at=BASE_TIME,
        first_response_at=None,
        response_due_at=None,
        resolution_due_at=None,
        sla_response_breached_at=None,
        sla_resolution_breached_at=None,
        resolved_at=None,
    )


def test_low_priority_sla_targets():
    complaint = make_complaint(priority=ComplaintPriority.LOW)

    targets = get_sla_targets(complaint)

    assert targets["response_minutes"] == 1440
    assert targets["resolution_minutes"] == 4320


def test_medium_priority_sla_targets():
    complaint = make_complaint(priority=ComplaintPriority.MEDIUM)

    targets = get_sla_targets(complaint)

    assert targets["response_minutes"] == 480
    assert targets["resolution_minutes"] == 2880


def test_high_priority_sla_targets():
    complaint = make_complaint(priority=ComplaintPriority.HIGH)

    targets = get_sla_targets(complaint)

    assert targets["response_minutes"] == 120
    assert targets["resolution_minutes"] == 1440


def test_critical_severity_overrides_priority():
    complaint = make_complaint(
        priority=ComplaintPriority.LOW,
        severity=ComplaintSeverity.CRITICAL,
    )

    targets = get_sla_targets(complaint)

    assert targets["response_minutes"] == 30
    assert targets["resolution_minutes"] == 240


def test_initialize_sla_sets_deadlines():
    complaint = make_complaint(
        priority=ComplaintPriority.HIGH,
    )

    initialize_sla(complaint)

    assert complaint.response_due_at == BASE_TIME + timedelta(hours=2)
    assert complaint.resolution_due_at == BASE_TIME + timedelta(hours=24)
    assert complaint.first_response_at is None
    assert complaint.sla_response_breached_at is None
    assert complaint.sla_resolution_breached_at is None


def test_initialize_sla_uses_explicit_start_time():
    complaint = make_complaint()
    start = BASE_TIME + timedelta(days=1)

    initialize_sla(complaint, start_time=start)

    assert complaint.response_due_at == start + timedelta(hours=8)
    assert complaint.resolution_due_at == start + timedelta(hours=48)


def test_first_response_is_recorded():
    complaint = make_complaint()
    initialize_sla(complaint)

    response_time = BASE_TIME + timedelta(hours=2)
    record_first_response(complaint, response_time)

    assert complaint.first_response_at == response_time
    assert complaint.sla_response_breached_at is None


def test_late_first_response_records_breach():
    complaint = make_complaint()
    initialize_sla(complaint)

    response_time = complaint.response_due_at + timedelta(seconds=1)
    record_first_response(complaint, response_time)

    assert complaint.first_response_at == response_time
    assert complaint.sla_response_breached_at == complaint.response_due_at


def test_first_response_is_recorded_only_once():
    complaint = make_complaint()
    initialize_sla(complaint)

    first_response = BASE_TIME + timedelta(hours=1)
    later_response = BASE_TIME + timedelta(hours=12)

    record_first_response(complaint, first_response)
    record_first_response(complaint, later_response)

    assert complaint.first_response_at == first_response


def test_missing_response_after_deadline_records_breach():
    complaint = make_complaint()
    initialize_sla(complaint)

    refresh_sla_breaches(
        complaint,
        now=complaint.response_due_at + timedelta(seconds=1),
    )

    assert complaint.sla_response_breached_at == complaint.response_due_at


def test_unresolved_complaint_after_deadline_records_breach():
    complaint = make_complaint()
    initialize_sla(complaint)

    refresh_sla_breaches(
        complaint,
        now=complaint.resolution_due_at + timedelta(seconds=1),
    )

    assert (
        complaint.sla_resolution_breached_at
        == complaint.resolution_due_at
    )


def test_late_resolution_records_breach():
    complaint = make_complaint(status=ComplaintStatus.RESOLVED)
    initialize_sla(complaint)

    complaint.resolved_at = (
        complaint.resolution_due_at + timedelta(minutes=5)
    )

    refresh_sla_breaches(
        complaint,
        now=complaint.resolved_at + timedelta(minutes=1),
    )

    assert (
        complaint.sla_resolution_breached_at
        == complaint.resolution_due_at
    )


def test_on_time_resolution_does_not_record_breach():
    complaint = make_complaint(status=ComplaintStatus.RESOLVED)
    initialize_sla(complaint)

    complaint.resolved_at = (
        complaint.resolution_due_at - timedelta(minutes=5)
    )

    refresh_sla_breaches(complaint, now=complaint.resolved_at)

    assert complaint.sla_resolution_breached_at is None


def test_sla_status_reports_breaches_and_remaining_time():
    complaint = make_complaint()
    initialize_sla(complaint)

    check_time = complaint.response_due_at + timedelta(minutes=10)
    result = get_sla_status(complaint, now=check_time)

    assert result["complaint_id"] == 1
    assert result["reference_number"] == "CMP-TEST-001"
    assert result["response_breached"] is True
    assert result["resolution_breached"] is False
    assert result["response_remaining_seconds"] < 0
    assert result["resolution_remaining_seconds"] is not None


def test_resolved_complaint_has_no_resolution_countdown():
    complaint = make_complaint(status=ComplaintStatus.RESOLVED)
    initialize_sla(complaint)
    complaint.resolved_at = BASE_TIME + timedelta(hours=1)

    result = get_sla_status(complaint, now=BASE_TIME + timedelta(hours=2))

    assert result["resolution_remaining_seconds"] is None
