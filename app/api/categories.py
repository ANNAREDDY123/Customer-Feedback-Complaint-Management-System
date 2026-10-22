
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.category import FeedbackCategory
from app.models.user import User, UserRole
from app.schemas.category import (
    CategoryCreate,
    CategoryPage,
    CategoryRead,
    CategoryStatusUpdate,
    CategoryUpdate,
)


router = APIRouter(
    prefix="/categories",
    tags=["Category Management"],
)

MANAGER_ROLES = (
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
)

STAFF_ROLES = (
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
    UserRole.SUPPORT_AGENT,
)


def get_category_or_404(
    db: Session,
    category_id: int,
) -> FeedbackCategory:
    category = db.get(FeedbackCategory, category_id)

    if category is None:
        raise HTTPException(
            status_code=404,
            detail="Feedback category not found",
        )

    return category


def ensure_unique_name(
    db: Session,
    name: str,
    exclude_id: int | None = None,
) -> None:
    statement = select(FeedbackCategory.id).where(
        func.lower(FeedbackCategory.name) == name.lower()
    )

    if exclude_id is not None:
        statement = statement.where(
            FeedbackCategory.id != exclude_id
        )

    if db.scalar(statement) is not None:
        raise HTTPException(
            status_code=409,
            detail="A category with this name already exists",
        )


def commit_category(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Category could not be saved due to a data conflict",
        )
    except Exception:
        db.rollback()
        raise


@router.post(
    "/",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    ensure_unique_name(db, payload.name)

    category = FeedbackCategory(
        name=payload.name,
        description=payload.description,
        is_active=True,
    )

    db.add(category)
    commit_category(db)
    db.refresh(category)

    return category


@router.get("/", response_model=CategoryPage)
def list_categories(
    q: str | None = Query(default=None, max_length=100),
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    sort_by: str = Query(
        default="name",
        pattern="^(name|created_at|updated_at)$",
    ),
    sort_order: str = Query(
        default="asc",
        pattern="^(asc|desc)$",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(FeedbackCategory)
    count_statement = select(func.count(FeedbackCategory.id))

    # Customers can see active categories only.
    # Staff can see active and inactive categories.
    if current_user.role == UserRole.CUSTOMER:
        statement = statement.where(
            FeedbackCategory.is_active.is_(True)
        )
        count_statement = count_statement.where(
            FeedbackCategory.is_active.is_(True)
        )

        if is_active is False:
            return CategoryPage(
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

    if is_active is not None:
        statement = statement.where(
            FeedbackCategory.is_active == is_active
        )
        count_statement = count_statement.where(
            FeedbackCategory.is_active == is_active
        )

    if q and q.strip():
        search_filter = FeedbackCategory.name.ilike(
            f"%{q.strip()}%"
        )
        statement = statement.where(search_filter)
        count_statement = count_statement.where(search_filter)

    sort_columns = {
        "name": FeedbackCategory.name,
        "created_at": FeedbackCategory.created_at,
        "updated_at": FeedbackCategory.updated_at,
    }

    column = sort_columns[sort_by]

    statement = statement.order_by(
        column.desc() if sort_order == "desc" else column.asc(),
        FeedbackCategory.id.asc(),
    )

    total = db.scalar(count_statement) or 0

    categories = db.scalars(
        statement
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return CategoryPage(
        items=categories,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
    )


@router.get("/{category_id}", response_model=CategoryRead)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    category = get_category_or_404(db, category_id)

    if (
        current_user.role == UserRole.CUSTOMER
        and not category.is_active
    ):
        raise HTTPException(
            status_code=404,
            detail="Feedback category not found",
        )

    if current_user.role not in STAFF_ROLES and (
        current_user.role != UserRole.CUSTOMER
    ):
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions",
        )

    return category


@router.patch("/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    category = get_category_or_404(db, category_id)

    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=400,
            detail="No category changes supplied",
        )

    if "name" in changes:
        if changes["name"] is None:
            raise HTTPException(
                status_code=422,
                detail="Category name cannot be null",
            )

        ensure_unique_name(
            db,
            changes["name"],
            exclude_id=category.id,
        )

    for field, value in changes.items():
        setattr(category, field, value)

    commit_category(db)
    db.refresh(category)

    return category


@router.patch(
    "/{category_id}/status",
    response_model=CategoryRead,
)
def update_category_status(
    category_id: int,
    payload: CategoryStatusUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGER_ROLES)),
):
    category = get_category_or_404(db, category_id)

    category.is_active = payload.is_active

    commit_category(db)
    db.refresh(category)

    return category
