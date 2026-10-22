
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
    ComplaintComment,
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
                name="Resolution Test Category",
                description="Category for resolution tests",
                is_active=True,
            )
        )
        db.commit()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def create_user(role, email, name="Resolution Test User"):
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
    email = "resolution.customer@example.com"

    response = client.post(
        "/auth/register",
        json={
            "full_name": "Resolution Customer",
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
                FeedbackCategory.name == "Resolution Test Category"
            )
        )
        category_id = category.id

    response = client.post(
        "/complaints/",
        headers=customer_headers,
        json={
            "category_id": category_id,
            "title": "Complaint requiring resolution",
            "description": "This complaint needs investigation and resolution.",
            "priority": "HIGH",
            "severity": "HIGH",
            "attachment_urls": [],
        },
    )

    assert response.status_code == 201
    return response.json()


def test_customer_can_add_visible_comment(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)

    response = client.post(
        f"/complaints/{complaint['id']}/comments",
        headers=customer,
        json={
            "content": "Please provide an update on my complaint.",
            "is_internal": False,
        },
    )

    assert response.status_code == 201
    assert response.json()["content"] == (
        "Please provide an update on my complaint."
    )
    assert response.json()["is_internal"] is False


def test_customer_cannot_add_internal_note(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)

    response = client.post(
        f"/complaints/{complaint['id']}/comments",
        headers=customer,
        json={
            "content": "Internal investigation note",
            "is_internal": True,
        },
    )

    assert response.status_code == 403


def test_customer_cannot_see_internal_notes(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "resolution.manager.notes@example.com",
    )

    add_note = client.post(
        f"/complaints/{complaint['id']}/comments",
        headers=manager,
        json={
            "content": "Internal review completed.",
            "is_internal": True,
        },
    )
    assert add_note.status_code == 201

    response = client.get(
        f"/complaints/{complaint['id']}/comments",
        headers=customer,
    )

    assert response.status_code == 200
    assert all(
        not comment["is_internal"]
        for comment in response.json()
    )


def test_staff_can_add_internal_note(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "resolution.manager.internal@example.com",
    )

    response = client.post(
        f"/complaints/{complaint['id']}/comments",
        headers=manager,
        json={
            "content": "Investigating the reported issue.",
            "is_internal": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["is_internal"] is True


def test_complaint_cannot_be_closed_before_resolution(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "resolution.manager.close@example.com",
    )

    response = client.post(
        f"/complaints/{complaint['id']}/close",
        headers=manager,
    )

    assert response.status_code == 409


def test_manager_can_resolve_complaint(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "resolution.manager.resolve@example.com",
    )

    response = client.post(
        f"/complaints/{complaint['id']}/resolve",
        headers=manager,
        json={
            "resolution_details": (
                "The reported issue was investigated and fixed."
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "RESOLVED"
    assert response.json()["resolution_details"] == (
        "The reported issue was investigated and fixed."
    )
    assert response.json()["resolved_by_user_id"] is not None
    assert response.json()["resolved_at"] is not None


def test_manager_can_close_resolved_complaint(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "resolution.manager.closed@example.com",
    )

    resolved = client.post(
        f"/complaints/{complaint['id']}/resolve",
        headers=manager,
        json={
            "resolution_details": (
                "The reported issue was investigated and fixed."
            )
        },
    )
    assert resolved.status_code == 200

    response = client.post(
        f"/complaints/{complaint['id']}/close",
        headers=manager,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CLOSED"
    assert response.json()["closed_at"] is not None


def test_customer_cannot_resolve_complaint(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)

    response = client.post(
        f"/complaints/{complaint['id']}/resolve",
        headers=customer,
        json={
            "resolution_details": (
                "The reported issue was investigated and fixed."
            )
        },
    )

    assert response.status_code == 403


def test_customer_can_reopen_resolved_complaint(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "resolution.manager.reopen@example.com",
    )

    resolved = client.post(
        f"/complaints/{complaint['id']}/resolve",
        headers=manager,
        json={
            "resolution_details": (
                "The reported issue was investigated and fixed."
            )
        },
    )
    assert resolved.status_code == 200

    response = client.post(
        f"/complaints/{complaint['id']}/reopen",
        headers=customer,
        json={
            "reason": "The same issue is happening again."
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "REOPENED"


def test_reopen_requires_a_valid_reason(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)

    response = client.post(
        f"/complaints/{complaint['id']}/reopen",
        headers=customer,
        json={"reason": "No"},
    )

    assert response.status_code == 422


def test_resolution_status_history_is_recorded(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "resolution.manager.history@example.com",
    )

    resolved = client.post(
        f"/complaints/{complaint['id']}/resolve",
        headers=manager,
        json={
            "resolution_details": (
                "The reported issue was investigated and fixed."
            )
        },
    )
    assert resolved.status_code == 200

    with TestingSessionLocal() as db:
        history = db.scalars(
            select(ComplaintHistory).where(
                ComplaintHistory.complaint_id == complaint["id"]
            )
        ).all()

    assert any(item.action == "RESOLVED" for item in history)


def test_internal_note_is_saved_in_database(client):
    customer = register_customer(client)
    complaint = create_complaint(client, customer)
    manager = create_user(
        UserRole.SUPPORT_MANAGER,
        "resolution.manager.database@example.com",
    )

    response = client.post(
        f"/complaints/{complaint['id']}/comments",
        headers=manager,
        json={
            "content": "Database persistence check.",
            "is_internal": True,
        },
    )
    assert response.status_code == 201

    with TestingSessionLocal() as db:
        saved = db.scalar(
            select(ComplaintComment).where(
                ComplaintComment.complaint_id == complaint["id"]
            )
        )

    assert saved is not None
    assert saved.content == "Database persistence check."
    assert saved.is_internal is True
