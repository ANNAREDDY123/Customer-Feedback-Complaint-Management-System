from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.complaint import (
    Complaint,
    ComplaintComment,
    ComplaintHistory,
    ComplaintStatus,
)
from app.models.customer import Customer
from app.models.user import User, UserRole
from app.schemas.resolution import (
    ComplaintCommentCreate,
    ComplaintCommentRead,
    ComplaintReopenRequest,
    ComplaintResolveRequest,
    ComplaintResolutionRead,
)
from app.services.sla import record_first_response
from app.services.notification import create_notification

router = APIRouter(prefix="/complaints", tags=["Complaint Resolution"])

STAFF_ROLES = {
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
    UserRole.SUPPORT_AGENT,
}

MANAGER_ROLES = {
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_complaint_or_404(db: Session, complaint_id: int) -> Complaint:
    complaint = db.get(Complaint, complaint_id)

    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")

    return complaint


def ensure_access(db: Session, complaint: Complaint, user: User) -> None:
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


def add_status_history(
    db: Session,
    complaint: Complaint,
    actor: User,
    action: str,
    old_status: str,
    new_status: str,
    reason: str | None = None,
) -> None:
    details = f"status={new_status}"

    if reason:
        details += f"; reason={reason}"

    db.add(
        ComplaintHistory(
            complaint_id=complaint.id,
            actor_user_id=actor.id,
            action=action,
            old_value=old_status,
            new_value=details,
        )
    )


def notify_customer(
    db: Session,
    complaint: Complaint,
    title: str,
    message: str,
    notification_type: str,
) -> None:
    """Create a notification for the customer who owns the complaint."""
    customer = db.get(Customer, complaint.customer_id)

    if customer is None:
        return

    create_notification(
        db,
        user_id=customer.user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        complaint_id=complaint.id,
    )


def commit_or_rollback(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


# LEVEL 9: Complaint comments and public-comment notifications

@router.post(
    "/{complaint_id}/comments",
    response_model=ComplaintCommentRead,
    status_code=status.HTTP_201_CREATED,
)
def add_complaint_comment(
    complaint_id: int,
    payload: ComplaintCommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    complaint = get_complaint_or_404(db, complaint_id)
    ensure_access(db, complaint, current_user)

    if payload.is_internal and current_user.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only support staff can create internal notes",
        )

    if (
        current_user.role == UserRole.SUPPORT_AGENT
        and complaint.assigned_agent_id != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="Agents can comment only on complaints assigned to them",
        )

    comment = ComplaintComment(
        complaint_id=complaint.id,
        author_user_id=current_user.id,
        content=payload.content,
        is_internal=payload.is_internal,
    )
    db.add(comment)

    db.add(
        ComplaintHistory(
            complaint_id=complaint.id,
            actor_user_id=current_user.id,
            action=(
                "INTERNAL_NOTE_ADDED"
                if payload.is_internal
                else "COMMENT_ADDED"
            ),
            new_value=payload.content,
        )
    )

    # Only the first public comment from support staff counts
    # as the complaint's first response.
    if current_user.role in STAFF_ROLES and not payload.is_internal:
        record_first_response(complaint)

    # Notify the customer only when staff post a public comment.
    # Never expose internal notes through notifications.
    if current_user.role in STAFF_ROLES and not payload.is_internal:
        notify_customer(
            db,
            complaint,
            title="New response to your complaint",
            message=(
                f"Support staff added a response to your complaint "
                f"'{complaint.title}' ({complaint.reference_number})."
            ),
            notification_type="COMPLAINT_COMMENT",
        )

    commit_or_rollback(db)
    db.refresh(comment)
    return comment


@router.get(
    "/{complaint_id}/comments",
    response_model=list[ComplaintCommentRead],
)
def list_complaint_comments(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    complaint = get_complaint_or_404(db, complaint_id)
    ensure_access(db, complaint, current_user)

    statement = select(ComplaintComment).where(
        ComplaintComment.complaint_id == complaint.id
    )

    # Customers must never receive internal notes.
    if current_user.role == UserRole.CUSTOMER:
        statement = statement.where(
            ComplaintComment.is_internal.is_(False)
        )

    return db.scalars(
        statement.order_by(
            ComplaintComment.created_at,
            ComplaintComment.id,
        )
    ).all()


# LEVEL 7 + LEVEL 9: Resolve complaint and notify customer

@router.post(
    "/{complaint_id}/resolve",
    response_model=ComplaintResolutionRead,
)
def resolve_complaint(
    complaint_id: int,
    payload: ComplaintResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only support staff can resolve complaints",
        )

    complaint = get_complaint_or_404(db, complaint_id)
    ensure_access(db, complaint, current_user)

    allowed = {
        ComplaintStatus.OPEN,
        ComplaintStatus.ASSIGNED,
        ComplaintStatus.IN_PROGRESS,
        ComplaintStatus.WAITING_FOR_CUSTOMER,
        ComplaintStatus.REOPENED,
    }

    if complaint.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot resolve a complaint in "
                f"{complaint.status.value} status"
            ),
        )

    old_status = complaint.status.value
    now = utc_now()

    record_first_response(complaint)

    complaint.status = ComplaintStatus.RESOLVED
    complaint.resolution_details = payload.resolution_details
    complaint.resolved_by_user_id = current_user.id
    complaint.resolved_at = now
    complaint.closed_at = None

    add_status_history(
        db,
        complaint,
        current_user,
        "RESOLVED",
        old_status,
        ComplaintStatus.RESOLVED.value,
        payload.resolution_details,
    )

    notify_customer(
        db,
        complaint,
        title="Complaint resolved",
        message=(
            f"Your complaint '{complaint.title}' "
            f"({complaint.reference_number}) has been resolved."
        ),
        notification_type="COMPLAINT_RESOLVED",
    )

    commit_or_rollback(db)
    db.refresh(complaint)
    return complaint


# LEVEL 7 + LEVEL 9: Close complaint and notify customer

@router.post(
    "/{complaint_id}/close",
    response_model=ComplaintResolutionRead,
)
def close_complaint(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only admins or support managers can close complaints",
        )

    complaint = get_complaint_or_404(db, complaint_id)
    ensure_access(db, complaint, current_user)

    if complaint.status != ComplaintStatus.RESOLVED:
        raise HTTPException(
            status_code=409,
            detail="A complaint must be resolved before it can be closed",
        )

    old_status = complaint.status.value
    complaint.status = ComplaintStatus.CLOSED
    complaint.closed_at = utc_now()

    add_status_history(
        db,
        complaint,
        current_user,
        "CLOSED",
        old_status,
        ComplaintStatus.CLOSED.value,
    )

    notify_customer(
        db,
        complaint,
        title="Complaint closed",
        message=(
            f"Your complaint '{complaint.title}' "
            f"({complaint.reference_number}) has been closed."
        ),
        notification_type="COMPLAINT_CLOSED",
    )

    commit_or_rollback(db)
    db.refresh(complaint)
    return complaint


# LEVEL 7 + LEVEL 9: Reopen complaint and notify customer

@router.post(
    "/{complaint_id}/reopen",
    response_model=ComplaintResolutionRead,
)
def reopen_complaint(
    complaint_id: int,
    payload: ComplaintReopenRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    complaint = get_complaint_or_404(db, complaint_id)
    ensure_access(db, complaint, current_user)

    if complaint.status not in {
        ComplaintStatus.RESOLVED,
        ComplaintStatus.CLOSED,
    }:
        raise HTTPException(
            status_code=409,
            detail="Only resolved or closed complaints can be reopened",
        )

    if current_user.role == UserRole.SUPPORT_AGENT:
        if complaint.assigned_agent_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Agents can reopen only complaints assigned to them",
            )

    old_status = complaint.status.value
    complaint.status = ComplaintStatus.REOPENED
    complaint.closed_at = None

    add_status_history(
        db,
        complaint,
        current_user,
        "REOPENED",
        old_status,
        ComplaintStatus.REOPENED.value,
        payload.reason,
    )

    # If a customer reopens their complaint, notify staff only when
    # an assigned agent exists. If staff reopen it, notify the customer.
    if current_user.role == UserRole.CUSTOMER:
        if complaint.assigned_agent_id is not None:
            create_notification(
                db,
                user_id=complaint.assigned_agent_id,
                title="Complaint reopened",
                message=(
                    f"Complaint '{complaint.title}' "
                    f"({complaint.reference_number}) was reopened."
                ),
                notification_type="COMPLAINT_REOPENED",
                complaint_id=complaint.id,
            )
    else:
        notify_customer(
            db,
            complaint,
            title="Complaint reopened",
            message=(
                f"Your complaint '{complaint.title}' "
                f"({complaint.reference_number}) has been reopened."
            ),
            notification_type="COMPLAINT_REOPENED",
        )

    commit_or_rollback(db)
    db.refresh(complaint)
    return complaint