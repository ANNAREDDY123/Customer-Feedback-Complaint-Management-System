
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import (
    NotificationListRead,
    NotificationRead,
)


router = APIRouter(prefix="/notifications", tags=["Notifications"])


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("", response_model=NotificationListRead)
def list_notifications(
    unread_only: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List notifications belonging only to the logged-in user."""
    filters = [Notification.user_id == current_user.id]

    if unread_only:
        filters.append(Notification.is_read.is_(False))

    total = db.scalar(
        select(func.count(Notification.id)).where(*filters)
    ) or 0

    unread_count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    ) or 0

    items = db.scalars(
        select(Notification)
        .where(*filters)
        .order_by(
            Notification.created_at.desc(),
            Notification.id.desc(),
        )
        .offset(skip)
        .limit(limit)
    ).all()

    return {
        "items": items,
        "total": total,
        "unread_count": unread_count,
    }


@router.get("/unread-count", response_model=dict[str, int])
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    ) or 0

    return {"unread_count": count}


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = db.get(Notification, notification_id)

    if notification is None:
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )

    if notification.user_id != current_user.id:
        # Avoid revealing another user's notification details.
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = utc_now()
        db.commit()
        db.refresh(notification)

    return notification


@router.patch("/read-all", response_model=dict[str, int])
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notifications = db.scalars(
        select(Notification).where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    ).all()

    now = utc_now()

    for notification in notifications:
        notification.is_read = True
        notification.read_at = now

    db.commit()

    return {"updated_count": len(notifications)}
