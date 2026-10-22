
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from jose import jwt

from app.main import app
from app.db.database import Base, get_db
from app.core.config import settings
from app.core.security import ALGORITHM
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog


TEST_DATABASE_URL = "sqlite://"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def create_user(db, email, role=UserRole.CUSTOMER):
    user = User(
        email=email,
        full_name=email.split("@")[0],
        hashed_password="test-password-hash",
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(client, user):
    token = jwt.encode(
        {"sub": str(user.id)},
        settings.secret_key,
        algorithm=ALGORITHM,
    )
    client.headers.update(
        {"Authorization": f"Bearer {token}"}
    )


def create_audit_log(
    db,
    *,
    actor_user_id=None,
    action="COMPLAINT_CREATED",
    resource_type="complaint",
    resource_id="123",
    details="Test audit record",
):
    record = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        extra_data={"source": "test"},
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_audit_logs_require_authentication(client):
    response = client.get("/audit-logs/")
    assert response.status_code in (401, 403)


def test_customer_cannot_view_audit_logs(client, db):
    customer = create_user(db, "customer@example.com")
    authenticate(client, customer)

    response = client.get("/audit-logs/")

    assert response.status_code == 403


@pytest.mark.parametrize(
    "role",
    [UserRole.ADMIN, UserRole.SUPPORT_MANAGER],
)
def test_authorized_roles_can_view_audit_logs(client, db, role):
    user = create_user(
        db,
        f"{role.value.lower()}@example.com",
        role=role,
    )
    create_audit_log(db, actor_user_id=user.id)
    authenticate(client, user)

    response = client.get("/audit-logs/")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["action"] == "COMPLAINT_CREATED"
    assert rows[0]["resource_type"] == "complaint"
    assert rows[0]["resource_id"] == "123"
    assert rows[0]["extra_data"] == {"source": "test"}


def test_audit_logs_can_filter_by_action(client, db):
    manager = create_user(
        db,
        "manager@example.com",
        role=UserRole.SUPPORT_MANAGER,
    )
    create_audit_log(
        db,
        actor_user_id=manager.id,
        action="COMPLAINT_CREATED",
    )
    create_audit_log(
        db,
        actor_user_id=manager.id,
        action="COMPLAINT_UPDATED",
    )
    authenticate(client, manager)

    response = client.get(
        "/audit-logs/",
        params={"action": "COMPLAINT_UPDATED"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["action"] == "COMPLAINT_UPDATED"


def test_audit_logs_can_filter_by_resource_type(client, db):
    manager = create_user(
        db,
        "manager@example.com",
        role=UserRole.SUPPORT_MANAGER,
    )
    create_audit_log(
        db,
        actor_user_id=manager.id,
        resource_type="complaint",
    )
    create_audit_log(
        db,
        actor_user_id=manager.id,
        resource_type="feedback",
    )
    authenticate(client, manager)

    response = client.get(
        "/audit-logs/",
        params={"resource_type": "feedback"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["resource_type"] == "feedback"


def test_audit_logs_support_pagination(client, db):
    manager = create_user(
        db,
        "manager@example.com",
        role=UserRole.SUPPORT_MANAGER,
    )
    for index in range(3):
        create_audit_log(
            db,
            actor_user_id=manager.id,
            action=f"ACTION_{index}",
        )
    authenticate(client, manager)

    response = client.get(
        "/audit-logs/",
        params={"offset": 0, "limit": 2},
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_audit_logs_reject_invalid_date_range(client, db):
    manager = create_user(
        db,
        "manager@example.com",
        role=UserRole.SUPPORT_MANAGER,
    )
    authenticate(client, manager)

    response = client.get(
        "/audit-logs/",
        params={
            "start_date": "2026-10-22T12:00:00",
            "end_date": "2026-10-21T12:00:00",
        },
    )

    assert response.status_code == 422


def test_audit_logs_reject_limit_above_maximum(client, db):
    manager = create_user(
        db,
        "manager@example.com",
        role=UserRole.SUPPORT_MANAGER,
    )
    authenticate(client, manager)

    response = client.get(
        "/audit-logs/",
        params={"limit": 201},
    )

    assert response.status_code == 422


def test_record_audit_log_service_persists_record(db):
    from app.services.audit_log import record_audit_log

    user = create_user(db, "audit-service@example.com")

    record = record_audit_log(
        db,
        actor_user_id=user.id,
        action="TEST_ACTION",
        resource_type="test_resource",
        resource_id=42,
        details="Audit service test",
        extra_data={"test": True},
    )

    assert record.id is not None

    saved = db.get(AuditLog, record.id)
    assert saved is not None
    assert saved.actor_user_id == user.id
    assert saved.action == "TEST_ACTION"
    assert saved.resource_type == "test_resource"
    assert saved.resource_id == "42"
    assert saved.extra_data == {"test": True}
