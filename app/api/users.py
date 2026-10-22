
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.user import User, UserRole
from app.schemas.auth import AccountStatusUpdate, UserRead


router = APIRouter(prefix="/users", tags=["User Management"])


@router.get("/", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return db.scalars(select(User).order_by(User.id)).all()


@router.patch("/{user_id}/status", response_model=UserRead)
def update_account_status(
    user_id: int,
    payload: AccountStatusUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    if admin.id == user_id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.is_active = payload.is_active

    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise

    return user


@router.get("/me", response_model=UserRead)
def read_my_account(
    current_user: User = Depends(get_current_user),
):
    return current_user
