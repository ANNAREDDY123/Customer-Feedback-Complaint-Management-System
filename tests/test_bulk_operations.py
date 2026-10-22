
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
from app.models.complaint import Complaint, ComplaintHistory
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
                name="Bulk Test Category",
                description="Category for bulk operation tests",
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
            full_name="Bulk Test User",
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
            "full_name": "Bulk Test Customer",
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


def create_complaint(client, customer_headers):
    with TestingSessionLocal() as db:
        category = db.scalar(
            select(FeedbackCategory).where(
                FeedbackCategory.name == "Bulk Test Category"
            )
        )
        category_id = category.id

    response = client.post(
        "/complaints/",
        headers=customer_headers,
        json={
            "category_id": category_id,
            "title": "Bulk operation test complaint",
            "description": "Complaint created for bulk operation tests.",
            "priority": "HIGH",
            "severity": "HIGH",
            "attachment_urls": [],
        },
    )
    assert response.status_code == 201
    return response.json()


def create_agent(client, manager_headers, email):
    response = client.post(
        "/agents/",
        headers=manager_headers,
        json={
            "full_name": "Bulk Test Agent",
            "email": email,
            "password": "StrongAgentPass123!",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_manager_can_bulk_assign_complaints(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "bulk-assign-manager@example.com"
    )
    customer = register_customer(client, "bulk-assign-customer@example.com")

    first = create_complaint(client, customer)
    second = create_complaint(client, customer)

    agent = create_agent(
        client, manager, "bulk-assign-agent@example.com"
    )

    response = client.post(
        "/complaints/bulk/assign",
        headers=manager,
        json={
            "complaint_ids": [first["id"], second["id"]],
            "agent_id": agent["id"],
            "note": "Bulk assignment test",
        },
    )

    assert response.status_code == 200
    assert response.json()["updated_count"] == 2

    with TestingSessionLocal() as db:
        for complaint_id in [first["id"], second["id"]]:
            complaint = db.get(Complaint, complaint_id)
            assert complaint.assigned_agent_id == agent["id"]


def test_manager_can_bulk_update_status(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "bulk-status-manager@example.com"
    )
    customer = register_customer(client, "bulk-status-customer@example.com")

    first = create_complaint(client, customer)
    second = create_complaint(client, customer)

    response = client.post(
        "/complaints/bulk/status",
        headers=manager,
        json={
            "complaint_ids": [first["id"], second["id"]],
            "status": "IN_PROGRESS",
        },
    )

    assert response.status_code == 200
    assert response.json()["updated_count"] == 2

    with TestingSessionLocal() as db:
        for complaint_id in [first["id"], second["id"]]:
            complaint = db.get(Complaint, complaint_id)
            assert complaint.status.value == "IN_PROGRESS"


def test_customer_cannot_bulk_assign_complaints(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "bulk-permission-manager@example.com"
    )
    customer = register_customer(client, "bulk-permission-customer@example.com")
    complaint = create_complaint(client, customer)
    agent = create_agent(
        client, manager, "bulk-permission-agent@example.com"
    )

    response = client.post(
        "/complaints/bulk/assign",
        headers=customer,
        json={
            "complaint_ids": [complaint["id"]],
            "agent_id": agent["id"],
        },
    )

    assert response.status_code == 403


def test_bulk_assign_rejects_missing_complaint_id(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "bulk-missing-manager@example.com"
    )
    agent = create_agent(
        client, manager, "bulk-missing-agent@example.com"
    )

    response = client.post(
        "/complaints/bulk/assign",
        headers=manager,
        json={
            "complaint_ids": [999999],
            "agent_id": agent["id"],
        },
    )

    assert response.status_code == 404


def test_bulk_assign_rejects_invalid_agent(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "bulk-invalid-agent-manager@example.com"
    )
    customer = register_customer(client, "bulk-invalid-agent-customer@example.com")
    complaint = create_complaint(client, customer)

    response = client.post(
        "/complaints/bulk/assign",
        headers=manager,
        json={
            "complaint_ids": [complaint["id"]],
            "agent_id": 999999,
        },
    )

    assert response.status_code == 400


def test_bulk_assign_is_atomic_when_one_complaint_is_closed(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "bulk-atomic-manager@example.com"
    )
    customer = register_customer(client, "bulk-atomic-customer@example.com")

    first = create_complaint(client, customer)
    second = create_complaint(client, customer)

    agent = create_agent(
        client, manager, "bulk-atomic-agent@example.com"
    )

    with TestingSessionLocal() as db:
        complaint = db.get(Complaint, second["id"])
        complaint.status = __import__(
            "app.models.complaint", fromlist=["ComplaintStatus"]
        ).ComplaintStatus.CLOSED
        db.commit()

    response = client.post(
        "/complaints/bulk/assign",
        headers=manager,
        json={
            "complaint_ids": [first["id"], second["id"]],
            "agent_id": agent["id"],
        },
    )

    assert response.status_code == 409

    with TestingSessionLocal() as db:
        first_db = db.get(Complaint, first["id"])
        second_db = db.get(Complaint, second["id"])

        assert first_db.assigned_agent_id is None
        assert second_db.assigned_agent_id is None


def test_bulk_status_rejects_invalid_transition_atomically(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "bulk-transition-manager@example.com"
    )
    customer = register_customer(client, "bulk-transition-customer@example.com")

    first = create_complaint(client, customer)
    second = create_complaint(client, customer)

    from app.models.complaint import ComplaintStatus

    with TestingSessionLocal() as db:
        complaint = db.get(Complaint, second["id"])
        complaint.status = ComplaintStatus.CLOSED
        db.commit()

    response = client.post(
        "/complaints/bulk/status",
        headers=manager,
        json={
            "complaint_ids": [first["id"], second["id"]],
            "status": "IN_PROGRESS",
        },
    )

    assert response.status_code == 409

    with TestingSessionLocal() as db:
        first_db = db.get(Complaint, first["id"])
        assert first_db.status.value == "OPEN"


def test_bulk_assign_rejects_duplicate_ids(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "bulk-duplicate-manager@example.com"
    )
    customer = register_customer(client, "bulk-duplicate-customer@example.com")
    complaint = create_complaint(client, customer)
    agent = create_agent(
        client, manager, "bulk-duplicate-agent@example.com"
    )

    response = client.post(
        "/complaints/bulk/assign",
        headers=manager,
        json={
            "complaint_ids": [complaint["id"], complaint["id"]],
            "agent_id": agent["id"],
        },
    )

    assert response.status_code == 422
