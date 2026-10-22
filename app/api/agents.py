
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.security import hash_password
from app.db.database import get_db
from app.models.complaint import Complaint, ComplaintStatus
from app.models.user import User, UserRole
from app.schemas.agent import AgentCreate, AgentRead, AgentWorkload


router = APIRouter(prefix="/agents", tags=["Agent Management"])

MANAGER_ROLES = (UserRole.ADMIN, UserRole.SUPPORT_MANAGER)


@router.post(
    "/",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_agent(
    payload: AgentCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    email = str(payload.email).lower()

    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists",
        )

    agent = User(
        full_name=payload.full_name.strip(),
        email=email,
        hashed_password=hash_password(payload.password),
        role=UserRole.SUPPORT_AGENT,
        is_active=True,
    )
    db.add(agent)

    try:
        db.commit()
        db.refresh(agent)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists",
        )

    return agent


@router.get("/", response_model=list[AgentRead])
def list_agents(
    active_only: bool = True,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    statement = select(User).where(User.role == UserRole.SUPPORT_AGENT)

    if active_only:
        statement = statement.where(User.is_active.is_(True))

    return db.scalars(statement.order_by(User.full_name.asc())).all()


@router.get("/workload", response_model=list[AgentWorkload])
def list_agent_workloads(
    active_only: bool = True,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    agents_statement = select(User).where(User.role == UserRole.SUPPORT_AGENT)

    if active_only:
        agents_statement = agents_statement.where(User.is_active.is_(True))

    agents = db.scalars(agents_statement.order_by(User.full_name.asc())).all()
    results = []

    for agent in agents:
        assigned_count = db.scalar(
            select(func.count(Complaint.id)).where(
                Complaint.assigned_agent_id == agent.id,
                Complaint.status.not_in(
                    [ComplaintStatus.CLOSED, ComplaintStatus.RESOLVED]
                ),
            )
        ) or 0

        in_progress_count = db.scalar(
            select(func.count(Complaint.id)).where(
                Complaint.assigned_agent_id == agent.id,
                Complaint.status == ComplaintStatus.IN_PROGRESS,
            )
        ) or 0

        waiting_count = db.scalar(
            select(func.count(Complaint.id)).where(
                Complaint.assigned_agent_id == agent.id,
                Complaint.status == ComplaintStatus.WAITING_FOR_CUSTOMER,
            )
        ) or 0

        results.append(
            AgentWorkload(
                agent_id=agent.id,
                agent_name=agent.full_name,
                agent_email=agent.email,
                is_active=agent.is_active,
                assigned_complaints=assigned_count,
                open_complaints=assigned_count - in_progress_count - waiting_count,
                in_progress_complaints=in_progress_count,
                waiting_for_customer=waiting_count,
            )
        )

    return results


@router.get("/{agent_id}/workload", response_model=AgentWorkload)
def get_agent_workload(
    agent_id: int,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    agent = db.get(User, agent_id)
    if agent is None or agent.role != UserRole.SUPPORT_AGENT:
        raise HTTPException(status_code=404, detail="Support agent not found")

    assigned_count = db.scalar(
        select(func.count(Complaint.id)).where(
            Complaint.assigned_agent_id == agent.id,
            Complaint.status.not_in(
                [ComplaintStatus.CLOSED, ComplaintStatus.RESOLVED]
            ),
        )
    ) or 0

    in_progress_count = db.scalar(
        select(func.count(Complaint.id)).where(
            Complaint.assigned_agent_id == agent.id,
            Complaint.status == ComplaintStatus.IN_PROGRESS,
        )
    ) or 0

    waiting_count = db.scalar(
        select(func.count(Complaint.id)).where(
            Complaint.assigned_agent_id == agent.id,
            Complaint.status == ComplaintStatus.WAITING_FOR_CUSTOMER,
        )
    ) or 0

    return AgentWorkload(
        agent_id=agent.id,
        agent_name=agent.full_name,
        agent_email=agent.email,
        is_active=agent.is_active,
        assigned_complaints=assigned_count,
        open_complaints=assigned_count - in_progress_count - waiting_count,
        in_progress_complaints=in_progress_count,
        waiting_for_customer=waiting_count,
    )
