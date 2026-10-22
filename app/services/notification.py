
from sqlalchemy.orm import Session

from app.models.notification import Notification


def create_notification(
    db: Session,
    *,
    user_id: int,
    title: str,
    message: str,
    notification_type: str = "GENERAL",
    complaint_id: int | None = None,
) -> Notification:
    """Create a notification without committing the caller's transaction."""
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        complaint_id=complaint_id,
    )
    db.add(notification)
    return notification


def notify_complaint_event(
    db: Session,
    *,
    user_id: int | None,
    complaint_id: int,
    title: str,
    message: str,
    notification_type: str,
) -> Notification | None:
    """Create a complaint-related notification when a recipient exists."""
    if user_id is None:
        return None

    return create_notification(
        db,
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        complaint_id=complaint_id,
    )
