
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.schemas.audit_log import AuditLogResponse


router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit Logs"],
)

AUDIT_LOG_ROLES = (
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
)


@router.get("/", response_model=list[AuditLogResponse])
def list_audit_logs(
    action: str | None = Query(default=None, max_length=100),
    resource_type: str | None = Query(default=None, max_length=100),
    actor_user_id: int | None = Query(default=None, ge=1),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*AUDIT_LOG_ROLES)),
):
    if start_date is not None and end_date is not None:
        if start_date > end_date:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=422,
                detail="start_date must be earlier than or equal to end_date",
            )

    statement = select(AuditLog)

    if action:
        statement = statement.where(AuditLog.action == action)

    if resource_type:
        statement = statement.where(
            AuditLog.resource_type == resource_type
        )

    if actor_user_id is not None:
        statement = statement.where(
            AuditLog.actor_user_id == actor_user_id
        )

    if start_date is not None:
        statement = statement.where(AuditLog.created_at >= start_date)

    if end_date is not None:
        statement = statement.where(AuditLog.created_at <= end_date)

    statement = (
        statement
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    )

    return list(db.scalars(statement).all())
