
import csv
from datetime import datetime
from io import StringIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import FeedbackCategory
from app.models.complaint import Complaint
from app.models.customer import Customer
from app.models.user import User


def export_complaints_csv(
    db: Session,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> str:
    statement = (
        select(
            Complaint.id,
            Complaint.reference_number,
            Complaint.title,
            Complaint.description,
            Complaint.status,
            Complaint.priority,
            Complaint.severity,
            Complaint.created_at,
            Complaint.updated_at,
            FeedbackCategory.name.label("category_name"),
            Customer.id.label("customer_id"),
            User.full_name.label("assigned_agent_name"),
        )
        .join(
            FeedbackCategory,
            FeedbackCategory.id == Complaint.category_id,
        )
        .join(
            Customer,
            Customer.id == Complaint.customer_id,
        )
        .outerjoin(
            User,
            User.id == Complaint.assigned_agent_id,
        )
        .order_by(Complaint.created_at.desc(), Complaint.id.asc())
    )

    if start_date is not None:
        statement = statement.where(Complaint.created_at >= start_date)

    if end_date is not None:
        statement = statement.where(Complaint.created_at <= end_date)

    rows = db.execute(statement).all()

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "Complaint ID",
            "Reference Number",
            "Title",
            "Description",
            "Status",
            "Priority",
            "Severity",
            "Created At",
            "Updated At",
            "Category",
            "Customer ID",
            "Assigned Agent",
        ]
    )

    for row in rows:
        writer.writerow(
            [
                row.id,
                row.reference_number,
                row.title,
                row.description,
                row.status.value if row.status else "",
                row.priority.value if row.priority else "",
                row.severity.value if row.severity else "",
                row.created_at.isoformat() if row.created_at else "",
                row.updated_at.isoformat() if row.updated_at else "",
                row.category_name,
                row.customer_id,
                row.assigned_agent_name or "",
            ]
        )

    return output.getvalue()
