
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.api.auth import router as auth_router
from app.api.categories import router as categories_router
from app.api.complaints import router as complaints_router
from app.api.customers import router as customers_router
from app.api.feedback import router as feedback_router
from app.api.users import router as users_router
from app.api.agents import router as agents_router
from app.api.resolution import router as resolution_router
from app.api.sla import router as sla_router
from app.api.notifications import router as notifications_router
from app.api import reports
from app.api.bulk_operations import router as bulk_operations_router
from app.api.audit_logs import router as audit_logs_router
from app.core.bootstrap import create_initial_admin
from app.core.config import settings
from app.db.database import SessionLocal, create_tables
from app.models.category import FeedbackCategory
from app.models.audit_log import AuditLog


DEFAULT_CATEGORIES = [
    (
        "Product Quality",
        "Feedback about product quality and reliability.",
    ),
    (
        "Customer Support",
        "Feedback about support and assistance.",
    ),
    (
        "Service Experience",
        "Feedback about the overall service.",
    ),
    (
        "Delivery Experience",
        "Feedback about shipping and delivery.",
    ),
    (
        "Technical Issue",
        "Feedback about technical problems.",
    ),
]


def seed_feedback_categories():
    with SessionLocal() as db:
        for name, description in DEFAULT_CATEGORIES:
            existing = db.scalar(
                select(FeedbackCategory).where(
                    FeedbackCategory.name == name
                )
            )
            if existing is None:
                db.add(
                    FeedbackCategory(
                        name=name,
                        description=description,
                        is_active=True,
                    )
                )
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    seed_feedback_categories()
    create_initial_admin()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Customer Feedback & Complaint Management System. "
        "Includes authentication, customer management, feedback, "
        "categories, and complaint tracking."
    ),
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(customers_router)
app.include_router(feedback_router)
app.include_router(categories_router)
app.include_router(complaints_router)
app.include_router(agents_router)
app.include_router(resolution_router)
app.include_router(sla_router)
app.include_router(notifications_router)
app.include_router(reports.router)
app.include_router(bulk_operations_router)
app.include_router(audit_logs_router)

@app.get("/", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "application": settings.app_name,
    }
