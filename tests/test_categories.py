
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

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def make_user_headers(role: UserRole, email: str):
    with TestingSessionLocal() as db:
        user = User(
            full_name=f"Test {role.value}",
            email=email,
            hashed_password=hash_password("StrongPass123!"),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    token = create_access_token(str(user_id))
    return {"Authorization": f"Bearer {token}"}


def test_manager_can_create_category(client):
    headers = make_user_headers(
        UserRole.SUPPORT_MANAGER,
        "manager1@example.com",
    )

    response = client.post(
        "/categories/",
        headers=headers,
        json={
            "name": "Billing Experience",
            "description": "Feedback about billing services",
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Billing Experience"
    assert response.json()["is_active"] is True


def test_duplicate_category_name_is_rejected(client):
    headers = make_user_headers(
        UserRole.ADMIN,
        "admin1@example.com",
    )

    first = client.post(
        "/categories/",
        headers=headers,
        json={"name": "Billing Experience"},
    )
    second = client.post(
        "/categories/",
        headers=headers,
        json={"name": "billing experience"},
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_customer_cannot_create_category(client):
    headers = make_user_headers(
        UserRole.CUSTOMER,
        "customer1@example.com",
    )

    response = client.post(
        "/categories/",
        headers=headers,
        json={"name": "Unauthorized Category"},
    )

    assert response.status_code == 403


def test_support_agent_cannot_update_category(client):
    manager_headers = make_user_headers(
        UserRole.ADMIN,
        "admin2@example.com",
    )
    agent_headers = make_user_headers(
        UserRole.SUPPORT_AGENT,
        "agent1@example.com",
    )

    created = client.post(
        "/categories/",
        headers=manager_headers,
        json={"name": "Agent Restricted Category"},
    )
    assert created.status_code == 201

    response = client.patch(
        f"/categories/{created.json()['id']}",
        headers=agent_headers,
        json={"name": "Changed by Agent"},
    )

    assert response.status_code == 403


def test_manager_can_update_category(client):
    headers = make_user_headers(
        UserRole.SUPPORT_MANAGER,
        "manager2@example.com",
    )

    created = client.post(
        "/categories/",
        headers=headers,
        json={"name": "Original Category"},
    )
    assert created.status_code == 201

    response = client.patch(
        f"/categories/{created.json()['id']}",
        headers=headers,
        json={
            "name": "Updated Category",
            "description": "Updated description",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Category"
    assert response.json()["description"] == "Updated description"


def test_manager_can_deactivate_category(client):
    headers = make_user_headers(
        UserRole.ADMIN,
        "admin3@example.com",
    )

    created = client.post(
        "/categories/",
        headers=headers,
        json={"name": "Temporary Category"},
    )
    assert created.status_code == 201

    response = client.patch(
        f"/categories/{created.json()['id']}/status",
        headers=headers,
        json={"is_active": False},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_customer_cannot_view_inactive_category(client):
    admin_headers = make_user_headers(
        UserRole.ADMIN,
        "admin4@example.com",
    )
    customer_headers = make_user_headers(
        UserRole.CUSTOMER,
        "customer2@example.com",
    )

    created = client.post(
        "/categories/",
        headers=admin_headers,
        json={"name": "Hidden Category"},
    )
    assert created.status_code == 201
    category_id = created.json()["id"]

    deactivated = client.patch(
        f"/categories/{category_id}/status",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200

    response = client.get(
        f"/categories/{category_id}",
        headers=customer_headers,
    )

    assert response.status_code == 404


def test_category_search_and_pagination(client):
    headers = make_user_headers(
        UserRole.ADMIN,
        "admin5@example.com",
    )

    for name in (
        "Delivery Delay",
        "Delivery Quality",
        "Billing Issue",
    ):
        response = client.post(
            "/categories/",
            headers=headers,
            json={"name": name},
        )
        assert response.status_code == 201

    response = client.get(
        "/categories/?q=Delivery&page=1&page_size=1&sort_by=name&sort_order=asc",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 1
    assert data["total_pages"] == 2
    assert len(data["items"]) == 1


def test_invalid_category_sort_is_rejected(client):
    headers = make_user_headers(
        UserRole.ADMIN,
        "admin6@example.com",
    )

    response = client.get(
        "/categories/?sort_by=password",
        headers=headers,
    )

    assert response.status_code == 422


def test_categories_require_authentication(client):
    response = client.get("/categories/")
    assert response.status_code == 401


def test_customer_sees_only_active_categories(client):
    admin_headers = make_user_headers(
        UserRole.ADMIN,
        "admin7@example.com",
    )
    customer_headers = make_user_headers(
        UserRole.CUSTOMER,
        "customer3@example.com",
    )

    active = client.post(
        "/categories/",
        headers=admin_headers,
        json={"name": "Active Feedback Category"},
    )
    inactive = client.post(
        "/categories/",
        headers=admin_headers,
        json={"name": "Inactive Feedback Category"},
    )

    assert active.status_code == 201
    assert inactive.status_code == 201

    status_response = client.patch(
        f"/categories/{inactive.json()['id']}/status",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert status_response.status_code == 200

    response = client.get(
        "/categories/",
        headers=customer_headers,
    )

    assert response.status_code == 200

    names = [item["name"] for item in response.json()["items"]]
    assert "Active Feedback Category" in names
    assert "Inactive Feedback Category" not in names
