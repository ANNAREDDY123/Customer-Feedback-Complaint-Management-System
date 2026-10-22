
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.complaint import (
    Complaint,
    ComplaintAssignmentHistory,
    ComplaintHistory,
    ComplaintStatus,
)
from app.models.customer import Customer
from app.models.user import User, UserRole
from app.schemas.bulk_operations import (
    BulkAssignRequest,
    BulkOperationResult,
    BulkStatusRequest,
)
from app.services.notification import create_notification


router = APIRouter(
    prefix="/complaints/bulk",
    tags=["Bulk Complaint Operations"],
)

MANAGER_ROLES = (UserRole.ADMIN, UserRole.SUPPORT_MANAGER)


@router.post("/assign", response_model=BulkOperationResult)
def bulk_assign_complaints(
    payload: BulkAssignRequest,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    agent = db.get(User, payload.agent_id)

    if (
        agent is None
        or agent.role != UserRole.SUPPORT_AGENT
        or not agent.is_active
    ):
        raise HTTPException(
            status_code=400,
            detail="The selected support agent does not exist or is inactive",
        )

    complaints = db.scalars(
        select(Complaint)
        .where(Complaint.id.in_(payload.complaint_ids))
        .order_by(Complaint.id)
    ).all()

    if len(complaints) != len(payload.complaint_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more complaints were not found",
        )

    for complaint in complaints:
        if complaint.status in {
            ComplaintStatus.RESOLVED,
            ComplaintStatus.CLOSED,
        }:
            raise HTTPException(
                status_code=409,
                detail=f"Complaint {complaint.id} is resolved or closed",
            )

        if complaint.assigned_agent_id == agent.id:
            raise HTTPException(
                status_code=409,
                detail=f"Complaint {complaint.id} is already assigned to this agent",
            )

    try:
        for complaint in complaints:
            previous_agent_id = complaint.assigned_agent_id
            old_status = complaint.status.value

            complaint.assigned_agent_id = agent.id

            if complaint.status == ComplaintStatus.OPEN:
                complaint.status = ComplaintStatus.ASSIGNED

            db.add(
                ComplaintAssignmentHistory(
                    complaint_id=complaint.id,
                    previous_agent_id=previous_agent_id,
                    new_agent_id=agent.id,
                    assigned_by_user_id=manager.id,
                    note=(
                        payload.note.strip()
                        if payload.note and payload.note.strip()
                        else None
                    ),
                )
            )

            db.add(
                ComplaintHistory(
                    complaint_id=complaint.id,
                    actor_user_id=manager.id,
                    action=(
                        "ASSIGNED"
                        if previous_agent_id is None
                        else "REASSIGNED"
                    ),
                    old_value=(
                        f"agent_id={previous_agent_id}; status={old_status}"
                    ),
                    new_value=(
                        f"agent_id={agent.id}; status={complaint.status.value}"
                    ),
                )
            )

            create_notification(
                db,
                user_id=agent.id,
                title="Complaint assigned to you",
                message=(
                    f"Complaint '{complaint.title}' "
                    f"({complaint.reference_number}) has been assigned to you."
                ),
                notification_type="COMPLAINT_ASSIGNED",
                complaint_id=complaint.id,
            )

        db.commit()

    except Exception:
        db.rollback()
        raise

    return BulkOperationResult(
        message="Complaints assigned successfully",
        updated_count=len(complaints),
        complaint_ids=[complaint.id for complaint in complaints],
    )


@router.post("/status", response_model=BulkOperationResult)
def bulk_update_complaint_status(
    payload: BulkStatusRequest,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    if payload.status in {
        ComplaintStatus.RESOLVED,
        ComplaintStatus.CLOSED,
        ComplaintStatus.REOPENED,
        ComplaintStatus.ASSIGNED,
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Bulk status updates cannot set RESOLVED, CLOSED, REOPENED, "
                "or ASSIGNED. Use the dedicated workflow endpoints."
            ),
        )

    allowed_transitions = {
        ComplaintStatus.OPEN: {
            ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.WAITING_FOR_CUSTOMER,
        },
        ComplaintStatus.ASSIGNED: {
            ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.WAITING_FOR_CUSTOMER,
        },
        ComplaintStatus.IN_PROGRESS: {
            ComplaintStatus.WAITING_FOR_CUSTOMER,
        },
        ComplaintStatus.WAITING_FOR_CUSTOMER: {
            ComplaintStatus.IN_PROGRESS,
        },
        ComplaintStatus.REOPENED: {
            ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.WAITING_FOR_CUSTOMER,
        },
    }

    complaints = db.scalars(
        select(Complaint)
        .where(Complaint.id.in_(payload.complaint_ids))
        .order_by(Complaint.id)
    ).all()

    if len(complaints) != len(payload.complaint_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more complaints were not found",
        )

    for complaint in complaints:
        if complaint.status != payload.status and (
            payload.status not in allowed_transitions.get(complaint.status, set())
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Invalid status transition for complaint {complaint.id}: "
                    f"{complaint.status.value} to {payload.status.value}"
                ),
            )

    try:
        for complaint in complaints:
            old_status = complaint.status.value

            if complaint.status == payload.status:
                continue

            complaint.status = payload.status

            db.add(
                ComplaintHistory(
                    complaint_id=complaint.id,
                    actor_user_id=manager.id,
                    action="STATUS_CHANGED",
                    old_value=old_status,
                    new_value=payload.status.value,
                )
            )

            customer = db.get(Customer, complaint.customer_id)

            if customer is not None:
                create_notification(
                    db,
                    user_id=customer.user_id,
                    title="Complaint status updated",
                    message=(
                        f"Your complaint '{complaint.title}' "
                        f"status changed to {payload.status.value}."
                    ),
                    notification_type="STATUS_CHANGED",
                    complaint_id=complaint.id,
                )

        db.commit()

    except Exception:
        db.rollback()
        raise

    return BulkOperationResult(
        message="Complaint statuses updated successfully",
        updated_count=len(complaints),
        complaint_ids=[complaint.id for complaint in complaints],
    )
