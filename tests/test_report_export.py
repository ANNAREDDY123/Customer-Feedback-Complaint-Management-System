
import csv
from io import StringIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.security import create_access_token, hash_password
from app.db.database import Base
from app.main import app
from app.models.category import FeedbackCategory
from app.models.complaint import Complaint
from app.models.customer import Customer
from app.models.user import User, UserRole


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db

    with TestingSessionLocal() as db:
        db.add(
            FeedbackCategory(
                name="Export Test Category",
                description="Category for CSV export tests",
                is_active=True,
            )
        )
        db.commit()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def create_user(role, email):
    with TestingSessionLocal() as db:
        user = User(
            full_name="Export Test User",
            email=email,
            hashed_password=hash_password("StrongPass123!"),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    return {
        "Authorization": f"Bearer {create_access_token(str(user_id))}"
    }


def register_customer(client, email):
    response = client.post(
        "/auth/register",
        json={
            "full_name": "Export Test Customer",
            "email": email,
            "password": "StrongPass123!",
        },
    )
    assert response.status_code == 201

    login = client.post(
        "/auth/login",
        data={
            "username": email,
            "password": "StrongPass123!",
        },
    )
    assert login.status_code == 200

    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }

    profile = client.post(
        "/customers/",
        headers=headers,
        json={"city": "Hyderabad"},
    )
    assert profile.status_code == 201

    return headers


def create_complaint(client, customer_headers, title):
    with TestingSessionLocal() as db:
        category = db.scalar(
            select(FeedbackCategory).where(
                FeedbackCategory.name == "Export Test Category"
            )
        )
        category_id = category.id

    response = client.post(
        "/complaints/",
        headers=customer_headers,
        json={
            "category_id": category_id,
            "title": title,
            "description": "Complaint created for CSV export testing.",
            "priority": "HIGH",
            "severity": "HIGH",
            "attachment_urls": [],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_csv_export_returns_download_response(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "export-manager@example.com",
    )

    response = client.get(
        "/reports/export/csv",
        headers=manager,
    )

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment;" in response.headers["content-disposition"]
    assert "complaints_report.csv" in response.headers["content-disposition"]


def test_csv_export_contains_expected_headers(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "export-headers@example.com",
    )

    response = client.get(
        "/reports/export/csv",
        headers=manager,
    )

    assert response.status_code == 200

    rows = list(csv.reader(StringIO(response.text)))
    assert rows[0] == [
        "Complaint ID",
        "Reference Number",
        "Title",
        "Description",
        "Status",
        "Priority",
        "Severity",
        "Created At",
        "Updated At",
        "Category",
        "Customer ID",
        "Assigned Agent",
    ]


def test_csv_export_includes_complaint_data(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "export-data-manager@example.com",
    )
    customer = register_customer(
        client,
        "export-data-customer@example.com",
    )
    complaint = create_complaint(
        client,
        customer,
        "CSV export test complaint",
    )

    response = client.get(
        "/reports/export/csv",
        headers=manager,
    )

    assert response.status_code == 200
    assert complaint["reference_number"] in response.text
    assert "CSV export test complaint" in response.text


def test_csv_export_filters_by_date_range(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "export-date-manager@example.com",
    )
    customer = register_customer(
        client,
        "export-date-customer@example.com",
    )

    included = create_complaint(
        client,
        customer,
        "Included date range complaint",
    )
    excluded = create_complaint(
        client,
        customer,
        "Excluded date range complaint",
    )

    with TestingSessionLocal() as db:
        included_db = db.get(Complaint, included["id"])
        excluded_db = db.get(Complaint, excluded["id"])

        from datetime import datetime

        included_db.created_at = datetime(2026, 5, 15, 12, 0, 0)
        excluded_db.created_at = datetime(2026, 7, 15, 12, 0, 0)
        db.commit()

    response = client.get(
        "/reports/export/csv",
        headers=manager,
        params={
            "start_date": "2026-05-01T00:00:00",
            "end_date": "2026-05-31T23:59:59",
        },
    )

    assert response.status_code == 200
    assert included["reference_number"] in response.text
    assert excluded["reference_number"] not in response.text


def test_csv_export_rejects_invalid_date_range(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "export-invalid-date@example.com",
    )

    response = client.get(
        "/reports/export/csv",
        headers=manager,
        params={
            "start_date": "2026-06-30T00:00:00",
            "end_date": "2026-06-01T00:00:00",
        },
    )

    assert response.status_code == 422


def test_csv_export_requires_authentication(client):
    response = client.get("/reports/export/csv")

    assert response.status_code == 401


def test_customer_cannot_export_complaint_report(client):
    customer = register_customer(
        client,
        "export-forbidden-customer@example.com",
    )

    response = client.get(
        "/reports/export/csv",
        headers=customer,
    )

    assert response.status_code == 403
