from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from jose import jwt

from app.main import app
from app.db.database import Base, get_db
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import ALGORITHM
from app.models.user import User, UserRole
from app.models.notification import Notification
from app.services.notification import create_notification


# ---------------------------------------------------------
# Test database setup
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

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


def create_test_notification(
    db,
    user_id,
    title="Test notification",
    message="This is a test notification",
    notification_type="GENERAL",
    is_read=False,
):
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        is_read=is_read,
        created_at=datetime.now(timezone.utc),
    )

    db.add(notification)
    db.commit()
    db.refresh(notification)

    return notification


def create_access_token(user):
    from jose import jwt
    from app.core.config import settings
    from app.core.security import ALGORITHM

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


# ---------------------------------------------------------
# Notification service tests
# ---------------------------------------------------------

def test_create_notification(db):
    user = create_user(db, "customer1@example.com")

    notification = create_notification(
        db,
        user_id=user.id,
        title="Complaint created",
        message="Your complaint was created",
        notification_type="COMPLAINT_CREATED",
    )

    db.commit()
    db.refresh(notification)

    assert notification.id is not None
    assert notification.user_id == user.id
    assert notification.title == "Complaint created"
    assert notification.is_read is False


def test_create_notification_with_complaint_id(db):
    user = create_user(db, "customer2@example.com")

    notification = create_notification(
        db,
        user_id=user.id,
        title="Complaint updated",
        message="Your complaint was updated",
        notification_type="STATUS_CHANGED",
        complaint_id=123,
    )

    db.commit()
    db.refresh(notification)

    assert notification.complaint_id == 123


# ---------------------------------------------------------
# Notification API tests
# ---------------------------------------------------------

def test_list_notifications(client, db):
    user = create_user(db, "list@example.com")
    create_test_notification(db, user.id)
    authenticate(client, user)

    response = client.get("/notifications")

    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


def test_unread_count(client, db):
    user = create_user(db, "unread@example.com")
    create_test_notification(db, user.id, is_read=False)
    create_test_notification(
        db,
        user.id,
        title="Already read",
        is_read=True,
    )
    authenticate(client, user)

    response = client.get("/notifications/unread-count")

    assert response.status_code == 200
    assert response.json()["unread_count"] == 1


def test_filter_unread_notifications(client, db):
    user = create_user(db, "filter@example.com")
    create_test_notification(db, user.id, is_read=False)
    create_test_notification(db, user.id, is_read=True)
    authenticate(client, user)

    response = client.get(
        "/notifications",
        params={"unread_only": True},
    )

    assert response.status_code == 200
    body = response.json()

    assert len(body["items"]) == 1
    assert body["items"][0]["is_read"] is False


def test_mark_notification_as_read(client, db):
    user = create_user(db, "markread@example.com")
    notification = create_test_notification(db, user.id)
    authenticate(client, user)

    response = client.patch(
        f"/notifications/{notification.id}/read"
    )

    assert response.status_code == 200
    assert response.json()["is_read"] is True


def test_mark_notification_as_read_is_idempotent(client, db):
    user = create_user(db, "idempotent@example.com")
    notification = create_test_notification(
        db,
        user.id,
        is_read=True,
    )
    authenticate(client, user)

    response = client.patch(
        f"/notifications/{notification.id}/read"
    )

    assert response.status_code == 200
    assert response.json()["is_read"] is True


def test_cannot_read_another_users_notification(client, db):
    owner = create_user(db, "owner@example.com")
    another_user = create_user(db, "another@example.com")

    notification = create_test_notification(db, owner.id)
    authenticate(client, another_user)

    response = client.patch(
        f"/notifications/{notification.id}/read"
    )

    assert response.status_code == 404


def test_missing_notification_returns_404(client, db):
    user = create_user(db, "missing@example.com")
    authenticate(client, user)

    response = client.patch("/notifications/99999/read")

    assert response.status_code == 404


def test_read_all_notifications(client, db):
    user = create_user(db, "readall@example.com")
    create_test_notification(db, user.id, is_read=False)
    create_test_notification(db, user.id, is_read=False)
    authenticate(client, user)

    response = client.patch("/notifications/read-all")

    assert response.status_code == 200

    unread_response = client.get("/notifications/unread-count")
    assert unread_response.status_code == 200
    assert unread_response.json()["unread_count"] == 0


def test_notifications_are_scoped_to_current_user(client, db):
    user1 = create_user(db, "first@example.com")
    user2 = create_user(db, "second@example.com")

    create_test_notification(db, user1.id, title="First user's notification")
    create_test_notification(db, user2.id, title="Second user's notification")

    authenticate(client, user1)

    response = client.get("/notifications")

    assert response.status_code == 200
    items = response.json()["items"]

    assert len(items) == 1
    assert items[0]["title"] == "First user's notification"


def test_notification_list_requires_authentication(client):
    response = client.get("/notifications")

    assert response.status_code in (401, 403)


# ---------------------------------------------------------
# Notification ownership and data integrity
# ---------------------------------------------------------

def test_notification_default_unread(db):
    user = create_user(db, "default@example.com")

    notification = Notification(
        user_id=user.id,
        title="Default unread",
        message="Unread by default",
        notification_type="GENERAL",
    )

    db.add(notification)
    db.commit()
    db.refresh(notification)

    assert notification.is_read is False
    assert notification.read_at is None


def test_notification_created_timestamp(db):
    user = create_user(db, "timestamp@example.com")

    notification = create_test_notification(db, user.id)

    assert notification.created_at is not None


def test_notification_query_by_user(db):
    user = create_user(db, "query@example.com")

    create_test_notification(db, user.id, title="One")
    create_test_notification(db, user.id, title="Two")

    notifications = db.scalars(
        select(Notification).where(
            Notification.user_id == user.id
        )
    ).all()

    assert len(notifications) == 2