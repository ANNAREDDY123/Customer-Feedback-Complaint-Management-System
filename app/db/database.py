
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {}

if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(
        dbapi_connection,
        connection_record,
    ):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    # Import every model before creating tables.
    from app.models.user import User  # noqa: F401
    from app.models.customer import Customer  # noqa: F401
    from app.models.category import FeedbackCategory  # noqa: F401
    from app.models.feedback import Feedback, FeedbackHistory  # noqa: F401
    from app.models.complaint import (
        Complaint,
        ComplaintAssignmentHistory,
        ComplaintComment,
        ComplaintHistory,
    )  # noqa: F401
    from app.models.notification import Notification  # noqa: F401
    from app.models.audit_log import AuditLog  # noqa: F401

    Base.metadata.create_all(bind=engine)
