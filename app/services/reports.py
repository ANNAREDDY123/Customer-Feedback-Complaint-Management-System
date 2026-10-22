from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.category import FeedbackCategory
from app.models.complaint import Complaint, ComplaintStatus


def get_complaint_overview(db: Session) -> dict:
    counts = {
        status: count
        for status, count in db.execute(
            select(Complaint.status, func.count(Complaint.id))
            .group_by(Complaint.status)
        ).all()
    }

    total = sum(counts.values())

    return {
        "total_complaints": total,
        "open_complaints": counts.get(ComplaintStatus.OPEN, 0),
        "assigned_complaints": counts.get(ComplaintStatus.ASSIGNED, 0),
        "in_progress_complaints": counts.get(
            ComplaintStatus.IN_PROGRESS, 0
        ),
        "waiting_for_customer_complaints": counts.get(
            ComplaintStatus.WAITING_FOR_CUSTOMER, 0
        ),
        "reopened_complaints": counts.get(ComplaintStatus.REOPENED, 0),
        "resolved_complaints": counts.get(ComplaintStatus.RESOLVED, 0),
        "closed_complaints": counts.get(ComplaintStatus.CLOSED, 0),
    }


def get_category_report(db: Session) -> list[dict]:
    rows = db.execute(
        select(
            FeedbackCategory.id,
            FeedbackCategory.name,
            func.count(Complaint.id),
        )
        .outerjoin(
            Complaint,
            Complaint.category_id == FeedbackCategory.id,
        )
        .group_by(FeedbackCategory.id, FeedbackCategory.name)
        .order_by(FeedbackCategory.name)
    ).all()

    return [
        {
            "category_id": category_id,
            "category_name": category_name,
            "complaint_count": count,
        }
        for category_id, category_name, count in rows
    ]


def get_enum_report(db: Session, column) -> list[dict]:
    rows = db.execute(
        select(column, func.count(Complaint.id))
        .group_by(column)
        .order_by(column)
    ).all()

    return [
        {
            "name": value.value if hasattr(value, "value") else str(value),
            "count": count,
        }
        for value, count in rows
    ]


def get_resolution_metrics(db: Session) -> dict:
    resolved_count = db.scalar(
        select(func.count(Complaint.id)).where(
            Complaint.resolved_at.is_not(None)
        )
    ) or 0

    average_seconds = db.scalar(
        select(
            func.avg(
                func.julianday(Complaint.resolved_at)
                - func.julianday(Complaint.created_at)
            )
            * 86400
        ).where(
            Complaint.resolved_at.is_not(None)
        )
    )

    unresolved_count = db.scalar(
        select(func.count(Complaint.id)).where(
            Complaint.status.not_in(
                [ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED]
            )
        )
    ) or 0

    return {
        "resolved_complaints": resolved_count,
        "average_resolution_hours": (
            round(float(average_seconds) / 3600, 2)
            if average_seconds is not None
            else None
        ),
        "unresolved_complaints": unresolved_count,
    }


def get_sla_report(db: Session) -> dict:
    total = db.scalar(
        select(func.count(Complaint.id))
    ) or 0

    response_breached = db.scalar(
        select(func.count(Complaint.id)).where(
            Complaint.sla_response_breached_at.is_not(None)
        )
    ) or 0

    resolution_breached = db.scalar(
        select(func.count(Complaint.id)).where(
            Complaint.sla_resolution_breached_at.is_not(None)
        )
    ) or 0

    return {
        "total_complaints": total,
        "response_breached": response_breached,
        "resolution_breached": resolution_breached,
        "response_compliant": max(total - response_breached, 0),
        "resolution_compliant": max(total - resolution_breached, 0),
    }