from datetime import datetime
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.category import FeedbackCategory
from app.models.complaint import (
    Complaint,
    ComplaintAssignmentHistory,
    ComplaintHistory,
    ComplaintPriority,
    ComplaintSeverity,
    ComplaintStatus,
)
from app.models.customer import Customer
from app.models.user import User, UserRole
from app.schemas.complaint import (
    ComplaintCreate,
    ComplaintHistoryRead,
    ComplaintPage,
    ComplaintRead,
    ComplaintStatusUpdate,
    ComplaintUpdate,
)
from app.services.sla import initialize_sla
from app.services.notification import create_notification
from app.services.audit_log import record_audit_log

router = APIRouter(prefix="/complaints", tags=["Complaint Management"])

STAFF_ROLES = (
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
    UserRole.SUPPORT_AGENT,
)

MANAGER_ROLES = (
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
)


def get_complaint_or_404(db: Session, complaint_id: int) -> Complaint:
    complaint = db.get(Complaint, complaint_id)

    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")

    return complaint


def get_customer_profile(db: Session, user: User) -> Customer:
    customer = db.scalar(
        select(Customer).where(Customer.user_id == user.id)
    )

    if customer is None:
        raise HTTPException(
            status_code=400,
            detail="Create your customer profile before creating a complaint",
        )

    if not customer.is_active:
        raise HTTPException(
            status_code=403,
            detail="Your customer profile is inactive",
        )

    return customer


def ensure_complaint_access(
    db: Session,
    complaint: Complaint,
    user: User,
) -> None:
    if user.role in STAFF_ROLES:
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


def add_history(
    db: Session,
    complaint: Complaint,
    actor: User,
    action: str,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    db.add(
        ComplaintHistory(
            complaint_id=complaint.id,
            actor_user_id=actor.id,
            action=action,
            old_value=old_value,
            new_value=new_value,
        )
    )


def commit_changes(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The complaint could not be saved due to a data conflict",
        )
    except Exception:
        db.rollback()
        raise


# LEVEL 6: Assigned complaints

@router.get("/assigned", response_model=ComplaintPage)
def list_my_assigned_complaints(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.SUPPORT_AGENT:
        raise HTTPException(
            status_code=403,
            detail="Only support agents can view their assigned complaints",
        )

    filters = [
        Complaint.assigned_agent_id == current_user.id,
        Complaint.status.not_in(
            [ComplaintStatus.CLOSED, ComplaintStatus.RESOLVED]
        ),
    ]

    total = db.scalar(
        select(func.count(Complaint.id)).where(*filters)
    ) or 0

    items = db.scalars(
        select(Complaint)
        .where(*filters)
        .order_by(Complaint.priority.desc(), Complaint.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return ComplaintPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
    )


# LEVEL 5 + LEVEL 8 + LEVEL 9: Create complaint with SLA and notification

@router.post(
    "/",
    response_model=ComplaintRead,
    status_code=status.HTTP_201_CREATED,
)
def create_complaint(
    payload: ComplaintCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=403,
            detail="Only customers can create complaints",
        )

    customer = get_customer_profile(db, current_user)
    category = db.get(FeedbackCategory, payload.category_id)

    if category is None or not category.is_active:
        raise HTTPException(
            status_code=400,
            detail="The selected category does not exist or is inactive",
        )

    complaint = Complaint(
        customer_id=customer.id,
        category_id=category.id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        severity=payload.severity,
        status=ComplaintStatus.OPEN,
        attachment_urls=payload.attachment_urls,
    )

    db.add(complaint)

    try:
        db.flush()
        initialize_sla(complaint)

        add_history(
            db,
            complaint,
            current_user,
            "CREATED",
            new_value=(
                f"status={complaint.status.value}; "
                f"priority={complaint.priority.value}; "
                f"severity={complaint.severity.value}; "
                f"response_due_at={complaint.response_due_at}; "
                f"resolution_due_at={complaint.resolution_due_at}"
            ),
        )

        create_notification(
            db,
            user_id=current_user.id,
            title="Complaint created",
            message=(
                f"Your complaint '{complaint.title}' "
                f"({complaint.reference_number}) was created successfully."
            ),
            notification_type="COMPLAINT_CREATED",
            complaint_id=complaint.id,
        )

        record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="COMPLAINT_CREATED",
            resource_type="complaint",
            resource_id=complaint.id,
            details="Customer created a complaint",
            extra_data={
                "reference_number": complaint.reference_number,
                "status": complaint.status.value,
                "priority": complaint.priority.value,
                "severity": complaint.severity.value,
            },
            commit=False,
        )

        db.commit()
        db.refresh(complaint)

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The complaint could not be created due to a data conflict",
        )
    except Exception:
        db.rollback()
        raise

    return complaint


# LEVEL 5 + LEVEL 12: Advanced search, filtering, sorting and pagination

@router.get("/", response_model=ComplaintPage)
def list_complaints(
    q: str | None = Query(default=None, max_length=100),
    complaint_status: ComplaintStatus | None = Query(
        default=None, alias="status"
    ),
    priority: ComplaintPriority | None = None,
    severity: ComplaintSeverity | None = None,
    category_id: int | None = Query(default=None, gt=0),
    assigned_agent_id: int | None = Query(default=None, gt=0),
    customer_id: int | None = Query(default=None, gt=0),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    sla_breached: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    sort_by: str = Query(
        default="created_at",
        pattern="^(created_at|updated_at|priority|severity|status|reference_number)$",
    ),
    sort_order: str = Query(
        default="desc",
        pattern="^(asc|desc)$",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(Complaint)
    count_statement = select(func.count(Complaint.id))

    if (
        created_from is not None
        and created_to is not None
        and created_from > created_to
    ):
        raise HTTPException(
            status_code=422,
            detail="created_from must be earlier than or equal to created_to",
        )

    if current_user.role == UserRole.CUSTOMER:
        customer = db.scalar(
            select(Customer).where(Customer.user_id == current_user.id)
        )

        if customer is None:
            return ComplaintPage(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                total_pages=0,
            )

        owner_filter = Complaint.customer_id == customer.id
        statement = statement.where(owner_filter)
        count_statement = count_statement.where(owner_filter)

        if customer_id is not None and customer_id != customer.id:
            return ComplaintPage(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                total_pages=0,
            )

    elif current_user.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions",
        )

    if q and q.strip():
        term = f"%{q.strip()}%"
        search_filter = or_(
            Complaint.reference_number.ilike(term),
            Complaint.title.ilike(term),
            Complaint.description.ilike(term),
        )
        statement = statement.where(search_filter)
        count_statement = count_statement.where(search_filter)

    filters = [
        (complaint_status, Complaint.status),
        (priority, Complaint.priority),
        (severity, Complaint.severity),
        (category_id, Complaint.category_id),
    ]

    for value, column in filters:
        if value is not None:
            condition = column == value
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)

    extra_filters = []

    if assigned_agent_id is not None:
        extra_filters.append(
            Complaint.assigned_agent_id == assigned_agent_id
        )

    if customer_id is not None:
        extra_filters.append(
            Complaint.customer_id == customer_id
        )

    if created_from is not None:
        extra_filters.append(Complaint.created_at >= created_from)

    if created_to is not None:
        extra_filters.append(Complaint.created_at <= created_to)

    if sla_breached is True:
        extra_filters.append(
            or_(
                Complaint.sla_response_breached_at.is_not(None),
                Complaint.sla_resolution_breached_at.is_not(None),
            )
        )
    elif sla_breached is False:
        extra_filters.append(
            Complaint.sla_response_breached_at.is_(None)
            & Complaint.sla_resolution_breached_at.is_(None)
        )

    for condition in extra_filters:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    sort_columns = {
        "created_at": Complaint.created_at,
        "updated_at": Complaint.updated_at,
        "priority": Complaint.priority,
        "severity": Complaint.severity,
        "status": Complaint.status,
        "reference_number": Complaint.reference_number,
    }

    sort_column = sort_columns[sort_by]

    statement = statement.order_by(
        sort_column.asc() if sort_order == "asc" else sort_column.desc(),
        Complaint.id.asc(),
    )

    total = db.scalar(count_statement) or 0

    items = db.scalars(
        statement.offset((page - 1) * page_size).limit(page_size)
    ).all()

    return ComplaintPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
    )

# LEVEL 5: Get complaint details

@router.get("/{complaint_id}", response_model=ComplaintRead)
def get_complaint(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    complaint = get_complaint_or_404(db, complaint_id)
    ensure_complaint_access(db, complaint, current_user)
    return complaint


# LEVEL 5: Update complaint details

@router.patch("/{complaint_id}", response_model=ComplaintRead)
def update_complaint(
    complaint_id: int,
    payload: ComplaintUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    complaint = get_complaint_or_404(db, complaint_id)
    ensure_complaint_access(db, complaint, current_user)

    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(status_code=400, detail="No changes supplied")

    if current_user.role == UserRole.CUSTOMER:
        if complaint.status not in {
            ComplaintStatus.OPEN,
            ComplaintStatus.REOPENED,
        }:
            raise HTTPException(
                status_code=409,
                detail="Customers can edit complaints only while OPEN or REOPENED",
            )
    elif current_user.role not in MANAGER_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only the complaint owner or authorized managers can edit complaints",
        )

    old_values = []
    new_values = []

    for field, new_value in changes.items():
        if new_value is None:
            raise HTTPException(
                status_code=422,
                detail=f"{field} cannot be null",
            )

        old_value = getattr(complaint, field)

        if old_value != new_value:
            old_values.append(f"{field}={old_value}")
            new_values.append(f"{field}={new_value}")
            setattr(complaint, field, new_value)

    if old_values:
        add_history(
            db,
            complaint,
            current_user,
            "UPDATED",
            old_value="; ".join(old_values),
            new_value="; ".join(new_values),
        )

    commit_changes(db)
    db.refresh(complaint)
    return complaint


# LEVEL 5 + LEVEL 7 + LEVEL 9 + LEVEL 15: Update complaint status

@router.patch("/{complaint_id}/status", response_model=ComplaintRead)
def update_complaint_status(
    complaint_id: int,
    payload: ComplaintStatusUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    complaint = get_complaint_or_404(db, complaint_id)

    if payload.status in {
        ComplaintStatus.RESOLVED,
        ComplaintStatus.CLOSED,
        ComplaintStatus.REOPENED,
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Use the dedicated resolve, close, or reopen endpoint "
                "for this status transition"
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
        ComplaintStatus.RESOLVED: set(),
        ComplaintStatus.CLOSED: set(),
        ComplaintStatus.REOPENED: {
            ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.WAITING_FOR_CUSTOMER,
        },
    }

    if payload.status == complaint.status:
        return complaint

    if payload.status == ComplaintStatus.ASSIGNED:
        raise HTTPException(
            status_code=409,
            detail="Use the assignment endpoint to assign a complaint",
        )

    if payload.status not in allowed_transitions[complaint.status]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Invalid complaint status transition from "
                f"{complaint.status.value} to {payload.status.value}"
            ),
        )

    old_status = complaint.status.value
    complaint.status = payload.status

    add_history(
        db,
        complaint,
        manager,
        "STATUS_CHANGED",
        old_value=old_status,
        new_value=payload.status.value,
    )

    record_audit_log(
        db,
        actor_user_id=manager.id,
        action="COMPLAINT_STATUS_CHANGED",
        resource_type="complaint",
        resource_id=complaint.id,
        details="Complaint status changed",
        extra_data={
            "reference_number": complaint.reference_number,
            "old_status": old_status,
            "new_status": payload.status.value,
        },
        commit=False,
    )

    customer = db.get(Customer, complaint.customer_id)
    if customer is not None:
        create_notification(
            db,
            user_id=customer.user_id,
            title="Complaint status updated",
            message=(
                f"Your complaint '{complaint.title}' "
                f"status changed to {complaint.status.value}."
            ),
            notification_type="STATUS_CHANGED",
            complaint_id=complaint.id,
        )

    commit_changes(db)
    db.refresh(complaint)
    return complaint


# LEVEL 5: Complaint history

@router.get(
    "/{complaint_id}/history",
    response_model=list[ComplaintHistoryRead],
)
def get_complaint_history(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    complaint = get_complaint_or_404(db, complaint_id)
    ensure_complaint_access(db, complaint, current_user)

    return db.scalars(
        select(ComplaintHistory)
        .where(ComplaintHistory.complaint_id == complaint_id)
        .order_by(ComplaintHistory.created_at, ComplaintHistory.id)
    ).all()

# LEVEL 6 + LEVEL 9: Assign or reassign a complaint


@router.patch("/{complaint_id}/assign", response_model=ComplaintRead)
def assign_complaint(
    complaint_id: int,
    agent_id: int = Query(gt=0),
    note: str | None = Query(default=None, max_length=500),
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    complaint = get_complaint_or_404(db, complaint_id)
    agent = db.get(User, agent_id)

    if (
        agent is None
        or agent.role != UserRole.SUPPORT_AGENT
        or not agent.is_active
    ):
        raise HTTPException(
            status_code=400,
            detail="The selected support agent does not exist or is inactive",
        )

    if complaint.status in {
        ComplaintStatus.RESOLVED,
        ComplaintStatus.CLOSED,
    }:
        raise HTTPException(
            status_code=409,
            detail="Resolved or closed complaints cannot be assigned",
        )

    previous_agent_id = complaint.assigned_agent_id

    if previous_agent_id == agent.id:
        raise HTTPException(
            status_code=409,
            detail="This complaint is already assigned to that agent",
        )

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
            note=note.strip() if note and note.strip() else None,
        )
    )

    add_history(
        db,
        complaint,
        manager,
        "ASSIGNED" if previous_agent_id is None else "REASSIGNED",
        old_value=f"agent_id={previous_agent_id}; status={old_status}",
        new_value=f"agent_id={agent.id}; status={complaint.status.value}",
    )

    record_audit_log(
        db,
        actor_user_id=manager.id,
        action=(
            "COMPLAINT_ASSIGNED"
            if previous_agent_id is None
            else "COMPLAINT_REASSIGNED"
        ),
        resource_type="complaint",
        resource_id=complaint.id,
        details=(
            "Complaint assigned to support agent"
            if previous_agent_id is None
            else "Complaint reassigned to another support agent"
        ),
        extra_data={
            "reference_number": complaint.reference_number,
            "previous_agent_id": previous_agent_id,
            "new_agent_id": agent.id,
            "previous_status": old_status,
            "new_status": complaint.status.value,
        },
        commit=False,
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

    commit_changes(db)
    db.refresh(complaint)
    return complaint


# LEVEL 6: Assignment history

@router.get("/{complaint_id}/assignment-history")
def get_assignment_history(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    complaint = get_complaint_or_404(db, complaint_id)
    ensure_complaint_access(db, complaint, current_user)

    records = db.scalars(
        select(ComplaintAssignmentHistory)
        .where(ComplaintAssignmentHistory.complaint_id == complaint_id)
        .order_by(
            ComplaintAssignmentHistory.created_at,
            ComplaintAssignmentHistory.id,
        )
    ).all()

    return [
        {
            "id": record.id,
            "complaint_id": record.complaint_id,
            "previous_agent_id": record.previous_agent_id,
            "new_agent_id": record.new_agent_id,
            "assigned_by_user_id": record.assigned_by_user_id,
            "note": record.note,
            "created_at": record.created_at,
        }
        for record in records
    ]