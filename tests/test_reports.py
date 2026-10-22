
from datetime import datetime, timezone

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
from app.models.category import FeedbackCategory
from app.models.complaint import Complaint


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


def create_access_token(user):
    payload = {"sub": str(user.id)}
    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def authenticate(client, user):
    token = create_access_token(user)
    client.headers.update(
        {"Authorization": f"Bearer {token}"}
    )


def create_category(db, name="Technical Support"):
    category = FeedbackCategory(name=name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def report_manager(db, email="manager@example.com"):
    return create_user(
        db,
        email,
        role=UserRole.SUPPORT_MANAGER,
    )


def test_reports_overview_requires_authentication(client):
    response = client.get("/reports/overview")
    assert response.status_code in (401, 403)


def test_reports_categories_requires_authentication(client):
    response = client.get("/reports/categories")
    assert response.status_code in (401, 403)


def test_customer_cannot_access_reports(client, db):
    customer = create_user(db, "customer@example.com")
    authenticate(client, customer)

    response = client.get("/reports/overview")
    assert response.status_code == 403


def test_reports_overview_accessible_to_manager(client, db):
    manager = report_manager(db)
    authenticate(client, manager)

    response = client.get("/reports/overview")

    assert response.status_code == 200
    body = response.json()
    assert "total_complaints" in body
    assert body["total_complaints"] == 0


def test_categories_report_returns_empty_list(client, db):
    manager = report_manager(db)
    authenticate(client, manager)

    response = client.get("/reports/categories")

    assert response.status_code == 200
    assert response.json() == []


def test_categories_report_includes_category_without_complaints(
    client, db
):
    manager = report_manager(db)
    create_category(db, "Billing")
    authenticate(client, manager)

    response = client.get("/reports/categories")

    assert response.status_code == 200
    rows = response.json()

    assert len(rows) == 1
    assert rows[0]["category_name"] == "Billing"
    assert rows[0]["complaint_count"] == 0


@pytest.mark.parametrize(
    "endpoint, expected_key",
    [
        ("/reports/priorities", "priority"),
        ("/reports/severities", "severity"),
        ("/reports/statuses", "status"),
    ],
)
def test_enum_reports_return_lists(
    client, db, endpoint, expected_key
):
    manager = report_manager(db)
    authenticate(client, manager)

    response = client.get(endpoint)

    assert response.status_code == 200
    assert isinstance(response.json(), list)

    for item in response.json():
        assert expected_key in item
        assert "complaint_count" in item


def test_resolution_metrics_report(client, db):
    manager = report_manager(db)
    authenticate(client, manager)

    response = client.get("/reports/resolution-metrics")

    assert response.status_code == 200
    body = response.json()

    assert body["resolved_complaints"] == 0
    assert body["unresolved_complaints"] == 0
    assert body["average_resolution_hours"] is None


def test_sla_report(client, db):
    manager = report_manager(db)
    authenticate(client, manager)

    response = client.get("/reports/sla")

    assert response.status_code == 200
    body = response.json()

    assert body["total_complaints"] == 0
    assert body["response_breached"] == 0
    assert body["resolution_breached"] == 0
    assert body["response_compliant"] == 0
    assert body["resolution_compliant"] == 0


def test_dashboard_report_accessible_to_manager(client, db):
    manager = report_manager(db)
    authenticate(client, manager)

    response = client.get("/reports/dashboard")

    assert response.status_code == 200

    body = response.json()

    assert "generated_at" in body
    assert "overview" in body
    assert "categories" in body
    assert "priorities" in body
    assert "severities" in body
    assert "statuses" in body
    assert "resolution_metrics" in body
    assert "sla" in body

    assert body["overview"]["total_complaints"] == 0


def test_dashboard_report_requires_authentication(client):
    response = client.get("/reports/dashboard")

    assert response.status_code in (401, 403)


def test_customer_cannot_access_dashboard(client, db):
    customer = create_user(db, "dashboard_customer@example.com")
    authenticate(client, customer)

    response = client.get("/reports/dashboard")

    assert response.status_code == 403

