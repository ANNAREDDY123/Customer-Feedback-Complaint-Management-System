
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.database import get_db
from app.models.customer import Customer
from app.models.user import User, UserRole
from app.schemas.customer import (
    CustomerCreate,
    CustomerListItem,
    CustomerPage,
    CustomerRead,
    CustomerStatusUpdate,
    CustomerUpdate,
)


router = APIRouter(prefix="/customers", tags=["Customer Management"])

MANAGERS = (UserRole.ADMIN, UserRole.SUPPORT_MANAGER)
SUPPORT_STAFF = (
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
    UserRole.SUPPORT_AGENT,
)


def get_customer_or_404(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer profile not found",
        )
    return customer


def ensure_owner_or_staff(customer: Customer, user: User) -> None:
    if user.role in SUPPORT_STAFF:
        return
    if user.role == UserRole.CUSTOMER and customer.user_id == user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this customer profile",
    )


@router.post(
    "/",
    response_model=CustomerRead,
    status_code=status.HTTP_201_CREATED,
)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.CUSTOMER:
        if payload.user_id is not None and payload.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only create your own customer profile",
            )
        target_user_id = current_user.id
    elif current_user.role in MANAGERS:
        if payload.user_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="user_id is required when staff creates a customer profile",
            )
        target_user_id = payload.user_id
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers and authorized managers can create profiles",
        )

    target_user = db.get(User, target_user_id)
    if target_user is None or target_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer user account not found",
        )

    existing = db.scalar(
        select(Customer).where(Customer.user_id == target_user_id)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A customer profile already exists for this user",
        )

    customer = Customer(
        user_id=target_user_id,
        phone=payload.phone,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
    )
    db.add(customer)

    try:
        db.commit()
        db.refresh(customer)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A customer profile already exists or the user is invalid",
        )

    return customer


@router.get("/me", response_model=CustomerRead)
def get_my_customer_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is available to customer accounts only",
        )

    customer = db.scalar(
        select(Customer).where(Customer.user_id == current_user.id)
    )
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer profile not found. Create your profile first.",
        )

    return customer


@router.get("/", response_model=CustomerPage)
def list_customers(
    q: str | None = Query(default=None, max_length=100),
    city: str | None = Query(default=None, max_length=100),
    state: str | None = Query(default=None, max_length=100),
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    sort_by: str = Query(
        default="created_at",
        pattern="^(created_at|full_name|email|city)$",
    ),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*SUPPORT_STAFF)),
):
    statement = select(Customer, User.full_name, User.email).join(
        User, Customer.user_id == User.id
    )
    count_statement = (
        select(func.count(Customer.id))
        .join(User, Customer.user_id == User.id)
    )

    if q:
        term = f"%{q.strip()}%"
        search_filter = or_(
            User.full_name.ilike(term),
            User.email.ilike(term),
            Customer.phone.ilike(term),
            Customer.city.ilike(term),
        )
        statement = statement.where(search_filter)
        count_statement = count_statement.where(search_filter)

    if city:
        city_filter = Customer.city.ilike(f"%{city.strip()}%")
        statement = statement.where(city_filter)
        count_statement = count_statement.where(city_filter)

    if state:
        state_filter = Customer.state.ilike(f"%{state.strip()}%")
        statement = statement.where(state_filter)
        count_statement = count_statement.where(state_filter)

    if is_active is not None:
        statement = statement.where(Customer.is_active == is_active)
        count_statement = count_statement.where(Customer.is_active == is_active)

    sort_columns = {
        "created_at": Customer.created_at,
        "full_name": User.full_name,
        "email": User.email,
        "city": Customer.city,
    }
    sort_column = sort_columns[sort_by]
    statement = statement.order_by(
        sort_column.asc() if sort_order == "asc" else sort_column.desc(),
        Customer.id.asc(),
    )

    total = db.scalar(count_statement) or 0
    rows = db.execute(
        statement.offset((page - 1) * page_size).limit(page_size)
    ).all()

    items = [
        CustomerListItem(
            id=customer.id,
            user_id=customer.user_id,
            phone=customer.phone,
            address=customer.address,
            city=customer.city,
            state=customer.state,
            postal_code=customer.postal_code,
            is_active=customer.is_active,
            created_at=customer.created_at,
            updated_at=customer.updated_at,
            full_name=full_name,
            email=email,
        )
        for customer, full_name, email in rows
    ]

    return CustomerPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
    )


@router.get("/{customer_id}", response_model=CustomerListItem)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = get_customer_or_404(db, customer_id)
    ensure_owner_or_staff(customer, current_user)

    user = db.get(User, customer.user_id)
    return CustomerListItem(
        id=customer.id,
        user_id=customer.user_id,
        phone=customer.phone,
        address=customer.address,
        city=customer.city,
        state=customer.state,
        postal_code=customer.postal_code,
        is_active=customer.is_active,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
        full_name=user.full_name,
        email=user.email,
    )


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = get_customer_or_404(db, customer_id)
    ensure_owner_or_staff(customer, current_user)

    if (
        current_user.role == UserRole.SUPPORT_AGENT
        and payload.model_dump(exclude_unset=True)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Support agents have read-only access to customer profiles",
        )

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(customer, field, value)

    try:
        db.commit()
        db.refresh(customer)
    except Exception:
        db.rollback()
        raise

    return customer


@router.patch("/{customer_id}/status", response_model=CustomerRead)
def update_customer_status(
    customer_id: int,
    payload: CustomerStatusUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(*MANAGERS)),
):
    customer = get_customer_or_404(db, customer_id)
    customer.is_active = payload.is_active

    try:
        db.commit()
        db.refresh(customer)
    except Exception:
        db.rollback()
        raise

    return customer
