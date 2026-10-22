
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.complaint import Complaint
from app.models.customer import Customer
from app.models.user import User, UserRole
from app.schemas.sla import ComplaintSLARead
from app.services.sla import get_sla_status


router = APIRouter(prefix="/complaints", tags=["SLA Management"])

STAFF_ROLES = {
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
    UserRole.SUPPORT_AGENT,
}


def check_complaint_access(
    db: Session,
    complaint: Complaint,
    user: User,
) -> None:
    if user.role in STAFF_ROLES:
        if (
            user.role == UserRole.SUPPORT_AGENT
            and complaint.assigned_agent_id != user.id
        ):
            raise HTTPException(
                status_code=403,
                detail="Agents can access only complaints assigned to them",
            )
        return

    customer = db.get(Customer, complaint.customer_id)
    if (
        user.role != UserRole.CUSTOMER
        or customer is None
        or customer.user_id != user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You can only access your own complaints",
        )


@router.get("/{complaint_id}/sla", response_model=ComplaintSLARead)
def read_complaint_sla(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(
            status_code=404,
            detail="Complaint not found",
        )

    check_complaint_access(db, complaint, current_user)

    result = get_sla_status(complaint)

    # Persist any newly detected breaches.
    db.commit()

    return result


@router.get("/sla/breaches", response_model=list[ComplaintSLARead])
def list_sla_breaches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {
        UserRole.ADMIN,
        UserRole.SUPPORT_MANAGER,
    }:
        raise HTTPException(
            status_code=403,
            detail="Only administrators and support managers can view SLA breaches",
        )

    complaints = db.scalars(
        select(Complaint).order_by(Complaint.created_at.desc())
    ).all()

    results = []
    for complaint in complaints:
        result = get_sla_status(complaint)
        if (
            result["response_breached"]
            or result["resolution_breached"]
        ):
            results.append(result)

    db.commit()
    return results
