
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
from app.models.complaint import (
    Complaint,
    ComplaintAssignmentHistory,
    ComplaintHistory,
)
from app.models.customer import Customer
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
                name="Agent Test Category",
                description="Category for assignment tests",
                is_active=True,
            )
        )
        db.commit()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def create_user(role, email, name="Test User"):
    with TestingSessionLocal() as db:
        user = User(
            full_name=name,
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


def register_customer(client):
    email = "assignment.customer@example.com"

    response = client.post(
        "/auth/register",
        json={
            "full_name": "Assignment Customer",
            "email": email,
            "password": "StrongPass123!",
        },
    )
    assert response.status_code == 201

    login = client.post(
        "/auth/login",
        data={"username": email, "password": "StrongPass123!"},
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
                FeedbackCategory.name == "Agent Test Category"
            )
        )
        category_id = category.id

    response = client.post(
        "/complaints/",
        headers=customer_headers,
        json={
            "category_id": category_id,
            "title": "Support required for my order",
            "description": "My order has an issue that requires support.",
            "priority": "HIGH",
            "severity": "HIGH",
            "attachment_urls": [],
        },
    )
    assert response.status_code == 201
    return response.json()


def create_agent(client, manager_headers, email="agent@example.com"):
    response = client.post(
        "/agents/",
        headers=manager_headers,
        json={
            "full_name": "Support Agent One",
            "email": email,
            "password": "StrongAgentPass123!",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_manager_can_create_support_agent(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "manager-create@example.com"
    )

    response = client.post(
        "/agents/",
        headers=manager,
        json={
            "full_name": "New Support Agent",
            "email": "new.agent@example.com",
            "password": "StrongAgentPass123!",
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == "new.agent@example.com"


def test_customer_cannot_create_support_agent(client):
    customer_headers = register_customer(client)

    response = client.post(
        "/agents/",
        headers=customer_headers,
        json={
            "full_name": "Unauthorized Agent",
            "email": "unauthorized.agent@example.com",
            "password": "StrongAgentPass123!",
        },
    )

    assert response.status_code == 403


def test_manager_can_assign_complaint(client):
    customer_headers = register_customer(client)
    complaint = create_complaint(client, customer_headers)
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "manager-assign@example.com"
    )
    agent = create_agent(client, manager)

    response = client.patch(
        f"/complaints/{complaint['id']}/assign?agent_id={agent['id']}",
        headers=manager,
    )

    assert response.status_code == 200
    assert response.json()["assigned_agent_id"] == agent["id"]
    assert response.json()["status"] == "ASSIGNED"


def test_assignment_history_is_recorded(client):
    customer_headers = register_customer(client)
    complaint = create_complaint(client, customer_headers)
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "manager-history@example.com"
    )
    agent = create_agent(client, manager)

    assigned = client.patch(
        f"/complaints/{complaint['id']}/assign?agent_id={agent['id']}",
        headers=manager,
    )
    assert assigned.status_code == 200

    response = client.get(
        f"/complaints/{complaint['id']}/assignment-history",
        headers=customer_headers,
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["new_agent_id"] == agent["id"]


def test_customer_cannot_assign_complaint(client):
    customer_headers = register_customer(client)
    complaint = create_complaint(client, customer_headers)
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "manager-agent-create@example.com"
    )
    agent = create_agent(client, manager)

    response = client.patch(
        f"/complaints/{complaint['id']}/assign?agent_id={agent['id']}",
        headers=customer_headers,
    )

    assert response.status_code == 403


def test_agent_can_view_assigned_complaints(client):
    customer_headers = register_customer(client)
    complaint = create_complaint(client, customer_headers)
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "manager-list@example.com"
    )
    agent = create_agent(client, manager)

    assignment = client.patch(
        f"/complaints/{complaint['id']}/assign?agent_id={agent['id']}",
        headers=manager,
    )
    assert assignment.status_code == 200

    agent_headers = {
        "Authorization": f"Bearer {create_access_token(str(agent['id']))}"
    }
    response = client.get("/complaints/assigned", headers=agent_headers)

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == complaint["id"]


def test_manager_can_view_agent_workload(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "manager-workload@example.com"
    )
    agent = create_agent(client, manager)

    response = client.get(
        "/agents/workload",
        headers=manager,
    )

    assert response.status_code == 200
    assert any(item["agent_id"] == agent["id"] for item in response.json())


def test_duplicate_agent_email_is_rejected(client):
    manager = create_user(
        UserRole.SUPPORT_MANAGER, "manager-duplicate@example.com"
    )
    create_agent(client, manager, "duplicate.agent@example.com")

    response = client.post(
        "/agents/",
        headers=manager,
        json={
            "full_name": "Duplicate Agent",
            "email": "duplicate.agent@example.com",
            "password": "StrongAgentPass123!",
        },
    )

    assert response.status_code == 409
