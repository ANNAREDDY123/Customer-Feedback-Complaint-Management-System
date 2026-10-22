
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.security import create_access_token, hash_password
from app.db.database import Base
from app.main import app
from app.models.customer import Customer
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

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def register_and_login(client, email="customer@example.com"):
    response = client.post(
        "/auth/register",
        json={
            "full_name": "Test Customer",
            "email": email,
            "password": "StrongPass123!",
        },
    )
    assert response.status_code == 201

    response = client.post(
        "/auth/login",
        data={
            "username": email,
            "password": "StrongPass123!",
        },
    )
    assert response.status_code == 200

    return response.json()["access_token"]


def create_staff_token(role, email):
    with TestSessionLocal() as db:
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

    return create_access_token(str(user_id))


def test_customer_can_create_own_profile(client):
    token = register_and_login(client)
    response = client.post(
        "/customers/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "phone": "9876543210",
            "city": "Hyderabad",
            "state": "Telangana",
        },
    )

    assert response.status_code == 201
    assert response.json()["user_id"] > 0
    assert response.json()["city"] == "Hyderabad"


def test_customer_can_view_own_profile(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/customers/",
        headers=headers,
        json={"city": "Hyderabad"},
    )
    assert created.status_code == 201

    response = client.get("/customers/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == created.json()["id"]


def test_customer_cannot_create_duplicate_profile(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/customers/",
        headers=headers,
        json={"city": "Hyderabad"},
    )
    second = client.post(
        "/customers/",
        headers=headers,
        json={"city": "Warangal"},
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_customer_cannot_list_all_profiles(client):
    token = register_and_login(client)

    response = client.get(
        "/customers/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_customer_cannot_access_another_customer_profile(client):
    first_token = register_and_login(client, "first@example.com")
    second_token = register_and_login(client, "second@example.com")

    first_profile = client.post(
        "/customers/",
        headers={"Authorization": f"Bearer {first_token}"},
        json={"city": "Hyderabad"},
    )
    assert first_profile.status_code == 201

    response = client.get(
        f"/customers/{first_profile.json()['id']}",
        headers={"Authorization": f"Bearer {second_token}"},
    )

    assert response.status_code == 403


def test_manager_can_search_and_paginate_customers(client):
    token = register_and_login(client)
    customer_response = client.post(
        "/customers/",
        headers={"Authorization": f"Bearer {token}"},
        json={"city": "Hyderabad"},
    )
    assert customer_response.status_code == 201

    manager_token = create_staff_token(
        UserRole.SUPPORT_MANAGER,
        "manager@example.com",
    )

    response = client.get(
        "/customers/?city=Hyderabad&page=1&page_size=5&sort_by=full_name&sort_order=asc",
        headers={"Authorization": f"Bearer {manager_token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["email"] == "customer@example.com"


def test_manager_can_deactivate_customer_profile(client):
    customer_token = register_and_login(client)
    profile = client.post(
        "/customers/",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"city": "Hyderabad"},
    )
    assert profile.status_code == 201

    manager_token = create_staff_token(
        UserRole.SUPPORT_MANAGER,
        "manager-status@example.com",
    )
    response = client.patch(
        f"/customers/{profile.json()['id']}/status",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"is_active": False},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_customer_list_rejects_invalid_sort_field(client):
    token = create_staff_token(
        UserRole.ADMIN,
        "admin-sort@example.com",
    )

    response = client.get(
        "/customers/?sort_by=password",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
