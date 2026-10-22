
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
from app.models.customer import Customer
from app.models.feedback import Feedback, FeedbackHistory, FeedbackStatus
from app.models.user import User, UserRole


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(
    bind=test_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    with TestSessionLocal() as db:
        for name in ("Product Quality", "Customer Support"):
            if not db.scalar(
                select(FeedbackCategory).where(
                    FeedbackCategory.name == name
                )
            ):
                db.add(
                    FeedbackCategory(name=name, is_active=True)
                )
        db.commit()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


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

    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    profile = client.post(
        "/customers/",
        headers=headers,
        json={"city": "Hyderabad"},
    )
    assert profile.status_code == 201

    return headers


def create_manager_token(email="manager@example.com"):
    with TestSessionLocal() as db:
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

    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def submit_feedback(client, headers, rating=5):
    return client.post(
        "/feedback/",
        headers=headers,
        json={
            "category_id": 1,
            "rating": rating,
            "description": "The service was very good.",
        },
    )


def test_customer_can_submit_feedback(client):
    headers = register_customer(client)
    response = submit_feedback(client, headers)

    assert response.status_code == 201
    assert response.json()["rating"] == 5
    assert response.json()["status"] == "SUBMITTED"


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_invalid_feedback_rating_is_rejected(client, rating):
    headers = register_customer(client)
    response = submit_feedback(client, headers, rating=rating)

    assert response.status_code == 422


def test_customer_can_view_own_feedback_and_history(client):
    headers = register_customer(client)
    created = submit_feedback(client, headers)
    assert created.status_code == 201

    feedback_id = created.json()["id"]

    detail = client.get(
        f"/feedback/{feedback_id}",
        headers=headers,
    )
    history = client.get(
        f"/feedback/{feedback_id}/history",
        headers=headers,
    )

    assert detail.status_code == 200
    assert history.status_code == 200
    assert any(item["action"] == "CREATED" for item in history.json())


def test_customer_cannot_view_another_customers_feedback(client):
    first_headers = register_customer(client, "first@example.com")
    second_headers = register_customer(client, "second@example.com")

    created = submit_feedback(client, first_headers)
    assert created.status_code == 201

    response = client.get(
        f"/feedback/{created.json()['id']}",
        headers=second_headers,
    )

    assert response.status_code == 403


def test_customer_can_update_submitted_feedback(client):
    headers = register_customer(client)
    created = submit_feedback(client, headers)
    feedback_id = created.json()["id"]

    response = client.patch(
        f"/feedback/{feedback_id}",
        headers=headers,
        json={
            "rating": 4,
            "description": "Updated service feedback.",
        },
    )

    assert response.status_code == 200
    assert response.json()["rating"] == 4

    history = client.get(
        f"/feedback/{feedback_id}/history",
        headers=headers,
    )
    assert any(item["action"] == "UPDATED" for item in history.json())


def test_manager_can_change_feedback_status(client):
    customer_headers = register_customer(client)
    created = submit_feedback(client, customer_headers)
    feedback_id = created.json()["id"]

    manager_headers = create_manager_token()

    response = client.patch(
        f"/feedback/{feedback_id}/status",
        headers=manager_headers,
        json={"status": "UNDER_REVIEW"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "UNDER_REVIEW"


def test_invalid_feedback_status_transition_is_rejected(client):
    customer_headers = register_customer(client)
    created = submit_feedback(client, customer_headers)
    feedback_id = created.json()["id"]

    manager_headers = create_manager_token()

    response = client.patch(
        f"/feedback/{feedback_id}/status",
        headers=manager_headers,
        json={"status": "RESPONDED"},
    )

    assert response.status_code == 409


def test_feedback_requires_authentication(client):
    response = client.get("/feedback/")
    assert response.status_code == 401
