
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def record_audit_log(
    db: Session,
    *,
    action: str,
    resource_type: str,
    actor_user_id: int | None = None,
    resource_id: str | int | None = None,
    details: str | None = None,
    extra_data: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    commit: bool = True,
) -> AuditLog:
    """Create an audit record for an application action."""

    audit_entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=(
            str(resource_id) if resource_id is not None else None
        ),
        details=details,
        extra_data=extra_data,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    db.add(audit_entry)

    try:
        db.flush()
        if commit:
            db.commit()
            db.refresh(audit_entry)
        return audit_entry
    except Exception:
        db.rollback()
        raise
