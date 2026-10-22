
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.database import SessionLocal
from app.models.user import User, UserRole


logger = logging.getLogger(__name__)


def create_initial_admin() -> None:
    email = settings.admin_email.strip().lower()
    password = settings.admin_password

    if not email or not password:
        logger.warning(
            "Initial admin not created: configure ADMIN_EMAIL "
            "and ADMIN_PASSWORD in the environment."
        )
        return

    if len(password) < 12:
        raise RuntimeError(
            "ADMIN_PASSWORD must be at least 12 characters long."
        )

    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            logger.info("Initial admin account already exists.")
            return

        admin = User(
            full_name="System Administrator",
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        logger.info("Initial administrator account created.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
