from datetime import datetime, timedelta
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
from app.models.complaint import Complaint, ComplaintHistory  # noqa: F401
from app.models.customer import Customer  # noqa: F401
from app.models.feedback import Feedback, FeedbackHistory  # noqa: F401
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
                name="Test Complaint Category",
                description="Category for complaint tests",
                is_active=True,
            )
        )
        db.commit()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def register_customer(client, email="customer@example.com"):
    response = client.post(
        "/auth/register",
        json={
            "full_name": "Test Customer",
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


def create_manager_headers(email="manager@example.com"):
    with TestingSessionLocal() as db:
        user = User(
            full_name="Test Manager",
            email=email,
            hashed_password=hash_password("StrongPass123!"),
            role=UserRole.SUPPORT_MANAGER,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    token = create_access_token(str(user_id))
    return {"Authorization": f"Bearer {token}"}


def get_test_category_id():
    with TestingSessionLocal() as db:
        category = db.scalar(
            select(FeedbackCategory).where(
                FeedbackCategory.name == "Test Complaint Category"
            )
        )
        return category.id


def create_complaint(client, headers, **overrides):
    payload = {
        "category_id": get_test_category_id(),
        "title": "Delivery arrived damaged",
        "description": (
            "The delivered product was damaged and needs attention."
        ),
        "priority": "HIGH",
        "severity": "HIGH",
        "attachment_urls": [
            "https://example.com/evidence/photo.png"
        ],
    }
    payload.update(overrides)
    return client.post("/complaints/", headers=headers, json=payload)


def test_customer_can_create_complaint(client):
    headers = register_customer(client)

    response = create_complaint(client, headers)

    assert response.status_code == 201
    data = response.json()
    assert data["reference_number"].startswith("CMP-")
    assert data["status"] == "OPEN"
    assert data["priority"] == "HIGH"
    assert data["severity"] == "HIGH"
    assert data["attachment_urls"] == [
        "https://example.com/evidence/photo.png"
    ]


def test_complaint_reference_numbers_are_unique(client):
    headers = register_customer(client)

    first = create_complaint(client, headers)
    second = create_complaint(
        client,
        headers,
        title="Another damaged product",
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert (
        first.json()["reference_number"]
        != second.json()["reference_number"]
    )


@pytest.mark.parametrize("priority", ["INVALID", "URGENT"])
def test_invalid_priority_is_rejected(client, priority):
    headers = register_customer(client)

    response = create_complaint(client, headers, priority=priority)

    assert response.status_code == 422


def test_invalid_attachment_url_is_rejected(client):
    headers = register_customer(client)

    response = create_complaint(
        client,
        headers,
        attachment_urls=["file:///C:/private.txt"],
    )

    assert response.status_code == 422


def test_complaint_requires_valid_category(client):
    headers = register_customer(client)

    response = create_complaint(client, headers, category_id=99999)

    assert response.status_code == 400


def test_customer_can_view_own_complaint_and_history(client):
    headers = register_customer(client)
    created = create_complaint(client, headers)
    assert created.status_code == 201

    complaint_id = created.json()["id"]

    detail = client.get(
        f"/complaints/{complaint_id}",
        headers=headers,
    )
    history = client.get(
        f"/complaints/{complaint_id}/history",
        headers=headers,
    )

    assert detail.status_code == 200
    assert history.status_code == 200
    assert any(
        record["action"] == "CREATED"
        for record in history.json()
    )


def test_customer_cannot_view_another_customers_complaint(client):
    first_headers = register_customer(client, "first@example.com")
    second_headers = register_customer(client, "second@example.com")

    created = create_complaint(client, first_headers)
    assert created.status_code == 201

    response = client.get(
        f"/complaints/{created.json()['id']}",
        headers=second_headers,
    )

    assert response.status_code == 403


def test_customer_complaint_list_is_limited_to_their_own(client):
    first_headers = register_customer(client, "first-list@example.com")
    second_headers = register_customer(client, "second-list@example.com")

    created = create_complaint(client, first_headers)
    assert created.status_code == 201

    response = client.get(
        "/complaints/",
        headers=second_headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []


def test_manager_can_filter_and_paginate_complaints(client):
    customer_headers = register_customer(client)
    created = create_complaint(client, customer_headers)
    assert created.status_code == 201

    manager_headers = create_manager_headers()

    response = client.get(
        "/complaints/?priority=HIGH&page=1&page_size=5&sort_by=created_at",
        headers=manager_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["priority"] == "HIGH"


def test_manager_can_update_complaint_status(client):
    customer_headers = register_customer(client)
    created = create_complaint(client, customer_headers)
    complaint_id = created.json()["id"]

    manager_headers = create_manager_headers()

    response = client.patch(
        f"/complaints/{complaint_id}/status",
        headers=manager_headers,
        json={"status": "IN_PROGRESS"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"


def test_invalid_complaint_status_transition_is_rejected(client):
    customer_headers = register_customer(client)
    created = create_complaint(client, customer_headers)
    complaint_id = created.json()["id"]

    manager_headers = create_manager_headers()

    response = client.patch(
        f"/complaints/{complaint_id}/status",
        headers=manager_headers,
        json={"status": "CLOSED"},
    )

    assert response.status_code == 409


def test_customer_cannot_change_complaint_status(client):
    customer_headers = register_customer(client)
    created = create_complaint(client, customer_headers)

    response = client.patch(
        f"/complaints/{created.json()['id']}/status",
        headers=customer_headers,
        json={"status": "RESOLVED"},
    )

    assert response.status_code == 403


def test_complaint_requires_authentication(client):
    response = client.get("/complaints/")

    assert response.status_code == 401


def test_manager_can_filter_complaints_by_customer_id(client):
    customer_headers = register_customer(client, "filter-customer@example.com")
    created = create_complaint(client, customer_headers)
    assert created.status_code == 201

    complaint_id = created.json()["id"]

    with TestingSessionLocal() as db:
        complaint = db.get(Complaint, complaint_id)
        customer_id = complaint.customer_id

    manager_headers = create_manager_headers("filter-manager@example.com")

    response = client.get(
        "/complaints/",
        headers=manager_headers,
        params={"customer_id": customer_id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert all(item["id"] == complaint_id for item in data["items"])


def test_manager_can_filter_complaints_by_creation_date(client):
    customer_headers = register_customer(client, "date-filter@example.com")
    created = create_complaint(client, customer_headers)
    assert created.status_code == 201

    complaint_id = created.json()["id"]

    with TestingSessionLocal() as db:
        complaint = db.get(Complaint, complaint_id)
        complaint.created_at = datetime(2025, 6, 15, 12, 0, 0)
        db.commit()

    manager_headers = create_manager_headers("date-manager@example.com")

    response = client.get(
        "/complaints/",
        headers=manager_headers,
        params={
            "created_from": "2025-06-01T00:00:00",
            "created_to": "2025-06-30T23:59:59",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == complaint_id


def test_manager_can_filter_sla_breached_complaints(client):
    customer_headers = register_customer(client, "sla-filter@example.com")
    created = create_complaint(client, customer_headers)
    assert created.status_code == 201

    complaint_id = created.json()["id"]

    with TestingSessionLocal() as db:
        complaint = db.get(Complaint, complaint_id)
        complaint.sla_resolution_breached_at = datetime(2025, 6, 15, 12, 0, 0)
        db.commit()

    manager_headers = create_manager_headers("sla-manager@example.com")

    response = client.get(
        "/complaints/",
        headers=manager_headers,
        params={"sla_breached": "true"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == complaint_id


def test_manager_can_filter_complaints_without_sla_breach(client):
    customer_headers = register_customer(client, "sla-clear@example.com")
    created = create_complaint(client, customer_headers)
    assert created.status_code == 201

    complaint_id = created.json()["id"]

    with TestingSessionLocal() as db:
        complaint = db.get(Complaint, complaint_id)
        complaint.sla_response_breached_at = None
        complaint.sla_resolution_breached_at = None
        db.commit()

    manager_headers = create_manager_headers("sla-clear-manager@example.com")

    response = client.get(
        "/complaints/",
        headers=manager_headers,
        params={"sla_breached": "false"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == complaint_id


def test_invalid_creation_date_range_is_rejected(client):
    manager_headers = create_manager_headers("invalid-date-manager@example.com")

    response = client.get(
        "/complaints/",
        headers=manager_headers,
        params={
            "created_from": "2025-06-30T00:00:00",
            "created_to": "2025-06-01T00:00:00",
        },
    )

    assert response.status_code == 422


def test_customer_cannot_filter_another_customers_complaints(client):
    first_headers = register_customer(client, "isolation-first@example.com")
    second_headers = register_customer(client, "isolation-second@example.com")

    created = create_complaint(client, first_headers)
    assert created.status_code == 201

    with TestingSessionLocal() as db:
        complaint = db.get(Complaint, created.json()["id"])
        other_customer_id = complaint.customer_id

    response = client.get(
        "/complaints/",
        headers=second_headers,
        params={"customer_id": other_customer_id},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []



def test_manager_can_filter_complaints_by_assigned_agent(client):
    customer_headers = register_customer(
        client, "assigned-agent-customer@example.com"
    )
    created = create_complaint(client, customer_headers)
    assert created.status_code == 201

    complaint_id = created.json()["id"]
    agent_headers = create_manager_headers(
        "assigned-agent@example.com"
    )

    with TestingSessionLocal() as db:
        agent = db.scalar(
            select(User).where(
                User.email == "assigned-agent@example.com"
            )
        )
        complaint = db.get(Complaint, complaint_id)

        assert agent is not None
        complaint.assigned_agent_id = agent.id
        db.commit()
        agent_id = agent.id

    manager_headers = create_manager_headers(
        "assigned-filter-manager@example.com"
    )

    response = client.get(
        "/complaints/",
        headers=manager_headers,
        params={"assigned_agent_id": agent_id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == complaint_id
    assert data["items"][0]["assigned_agent_id"] == agent_id

