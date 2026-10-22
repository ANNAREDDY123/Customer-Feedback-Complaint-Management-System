
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.category import FeedbackCategory
from app.models.customer import Customer
from app.models.feedback import (
    Feedback,
    FeedbackHistory,
    FeedbackStatus,
)
from app.models.user import User, UserRole
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackHistoryRead,
    FeedbackRead,
    FeedbackStatusUpdate,
    FeedbackUpdate,
)


router = APIRouter(prefix="/feedback", tags=["Feedback Management"])

STAFF_ROLES = (
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
    UserRole.SUPPORT_AGENT,
)
MANAGER_ROLES = (UserRole.ADMIN, UserRole.SUPPORT_MANAGER)


def get_feedback_or_404(db: Session, feedback_id: int) -> Feedback:
    feedback = db.get(Feedback, feedback_id)
    if feedback is None:
        raise HTTPException(
            status_code=404,
            detail="Feedback not found",
        )
    return feedback


def check_feedback_access(feedback: Feedback, user: User) -> None:
    if user.role in STAFF_ROLES:
        return

    customer = user_customer_id(feedback)
    if customer is None or customer != user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only access your own feedback",
        )


def user_customer_id(feedback: Feedback) -> int | None:
    # customer_id is a Customer profile ID, not the user ID.
    # Ownership is checked separately against the customer profile.
    return None


def add_history(
    db: Session,
    feedback: Feedback,
    actor: User,
    action: str,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    db.add(
        FeedbackHistory(
            feedback_id=feedback.id,
            actor_user_id=actor.id,
            action=action,
            old_value=old_value,
            new_value=new_value,
        )
    )


def ensure_feedback_owner_or_staff(
    db: Session, feedback: Feedback, user: User
) -> None:
    if user.role in STAFF_ROLES:
        return

    customer = db.get(Customer, feedback.customer_id)
    if (
        user.role != UserRole.CUSTOMER
        or customer is None
        or customer.user_id != user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You can only access your own feedback",
        )


@router.post(
    "/",
    response_model=FeedbackRead,
    status_code=status.HTTP_201_CREATED,
)
def submit_feedback(
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=403,
            detail="Only customer accounts can submit feedback",
        )

    customer = db.scalar(
        select(Customer).where(Customer.user_id == current_user.id)
    )
    if customer is None:
        raise HTTPException(
            status_code=400,
            detail="Create your customer profile before submitting feedback",
        )

    if not customer.is_active:
        raise HTTPException(
            status_code=403,
            detail="Your customer profile is inactive",
        )

    category = db.get(FeedbackCategory, payload.category_id)
    if category is None or not category.is_active:
        raise HTTPException(
            status_code=400,
            detail="Feedback category does not exist or is inactive",
        )

    feedback = Feedback(
        customer_id=customer.id,
        category_id=category.id,
        rating=payload.rating,
        description=payload.description,
        status=FeedbackStatus.SUBMITTED,
    )
    db.add(feedback)

    try:
        db.flush()
        add_history(
            db,
            feedback,
            current_user,
            "CREATED",
            new_value=(
                f"rating={feedback.rating}; "
                f"category_id={feedback.category_id}; "
                f"status={feedback.status.value}"
            ),
        )
        db.commit()
        db.refresh(feedback)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Feedback could not be saved due to a data conflict",
        )
    except Exception:
        db.rollback()
        raise

    return feedback


@router.get("/", response_model=list[FeedbackRead])
def list_feedback(
    feedback_status: FeedbackStatus | None = Query(default=None, alias="status"),
    category_id: int | None = Query(default=None, gt=0),
    rating: int | None = Query(default=None, ge=1, le=5),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(Feedback).order_by(Feedback.created_at.desc())

    if current_user.role == UserRole.CUSTOMER:
        customer = db.scalar(
            select(Customer).where(Customer.user_id == current_user.id)
        )
        if customer is None:
            return []
        statement = statement.where(Feedback.customer_id == customer.id)
    elif current_user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if feedback_status is not None:
        statement = statement.where(Feedback.status == feedback_status)
    if category_id is not None:
        statement = statement.where(Feedback.category_id == category_id)
    if rating is not None:
        statement = statement.where(Feedback.rating == rating)

    return db.scalars(statement).all()


@router.get("/{feedback_id}", response_model=FeedbackRead)
def get_feedback(
    feedback_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    feedback = get_feedback_or_404(db, feedback_id)
    ensure_feedback_owner_or_staff(db, feedback, current_user)
    return feedback


@router.patch("/{feedback_id}", response_model=FeedbackRead)
def update_feedback(
    feedback_id: int,
    payload: FeedbackUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    feedback = get_feedback_or_404(db, feedback_id)
    ensure_feedback_owner_or_staff(db, feedback, current_user)

    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=403,
            detail="Use the feedback status endpoint to manage feedback workflow",
        )

    if feedback.status != FeedbackStatus.SUBMITTED:
        raise HTTPException(
            status_code=409,
            detail="Feedback can only be edited while its status is SUBMITTED",
        )

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No changes supplied")

    old_values = []
    new_values = []

    for field, new_value in changes.items():
        old_value = getattr(feedback, field)
        if old_value != new_value:
            old_values.append(f"{field}={old_value}")
            new_values.append(f"{field}={new_value}")
            setattr(feedback, field, new_value)

    if old_values:
        add_history(
            db,
            feedback,
            current_user,
            "UPDATED",
            old_value="; ".join(old_values),
            new_value="; ".join(new_values),
        )

    try:
        db.commit()
        db.refresh(feedback)
    except Exception:
        db.rollback()
        raise

    return feedback


@router.patch("/{feedback_id}/status", response_model=FeedbackRead)
def update_feedback_status(
    feedback_id: int,
    payload: FeedbackStatusUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    feedback = get_feedback_or_404(db, feedback_id)

    allowed_transitions = {
        FeedbackStatus.SUBMITTED: {
            FeedbackStatus.UNDER_REVIEW,
            FeedbackStatus.ARCHIVED,
        },
        FeedbackStatus.UNDER_REVIEW: {
            FeedbackStatus.RESPONDED,
            FeedbackStatus.ARCHIVED,
        },
        FeedbackStatus.RESPONDED: {FeedbackStatus.ARCHIVED},
        FeedbackStatus.ARCHIVED: set(),
    }

    if payload.status == feedback.status:
        return feedback

    if payload.status not in allowed_transitions[feedback.status]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Invalid feedback status transition: "
                f"{feedback.status.value} to {payload.status.value}"
            ),
        )

    old_status = feedback.status.value
    feedback.status = payload.status
    add_history(
        db,
        feedback,
        manager,
        "STATUS_CHANGED",
        old_value=old_status,
        new_value=payload.status.value,
    )

    try:
        db.commit()
        db.refresh(feedback)
    except Exception:
        db.rollback()
        raise

    return feedback


@router.get("/{feedback_id}/history", response_model=list[FeedbackHistoryRead])
def get_feedback_history(
    feedback_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    feedback = get_feedback_or_404(db, feedback_id)
    ensure_feedback_owner_or_staff(db, feedback, current_user)

    return db.scalars(
        select(FeedbackHistory)
        .where(FeedbackHistory.feedback_id == feedback_id)
        .order_by(FeedbackHistory.created_at, FeedbackHistory.id)
    ).all()
