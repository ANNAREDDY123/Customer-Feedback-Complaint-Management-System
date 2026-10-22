
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.db.database import Base
from app.main import app
from app.models.user import User, UserRole
from app.core.security import hash_password


TEST_DATABASE_URL = "sqlite://"

test_engine = create_engine(
    TEST_DATABASE_URL,
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


def register_customer(client):
    return client.post(
        "/auth/register",
        json={
            "full_name": "Test Customer",
            "email": "customer@example.com",
            "password": "StrongPass123!",
        },
    )


def test_register_customer(client):
    response = register_customer(client)

    assert response.status_code == 201
    assert response.json()["email"] == "customer@example.com"
    assert response.json()["role"] == "CUSTOMER"
    assert "hashed_password" not in response.json()


def test_duplicate_email_is_rejected(client):
    first = register_customer(client)
    second = register_customer(client)

    assert first.status_code == 201
    assert second.status_code == 409


def test_login_and_current_user(client):
    register_customer(client)

    login_response = client.post(
        "/auth/login",
        data={
            "username": "customer@example.com",
            "password": "StrongPass123!",
        },
    )

    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    me_response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["email"] == "customer@example.com"


def test_wrong_password_is_rejected(client):
    register_customer(client)

    response = client.post(
        "/auth/login",
        data={
            "username": "customer@example.com",
            "password": "WrongPassword123!",
        },
    )

    assert response.status_code == 401


def test_current_user_requires_authentication(client):
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_customer_cannot_list_users(client):
    register_customer(client)

    login_response = client.post(
        "/auth/login",
        data={
            "username": "customer@example.com",
            "password": "StrongPass123!",
        },
    )
    token = login_response.json()["access_token"]

    response = client.get(
        "/users/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_deactivated_user_cannot_login(client):
    with TestSessionLocal() as db:
        db.add(
            User(
                full_name="Inactive Customer",
                email="inactive@example.com",
                hashed_password=hash_password("StrongPass123!"),
                role=UserRole.CUSTOMER,
                is_active=False,
            )
        )
        db.commit()

    response = client.post(
        "/auth/login",
        data={
            "username": "inactive@example.com",
            "password": "StrongPass123!",
        },
    )

    assert response.status_code == 403
