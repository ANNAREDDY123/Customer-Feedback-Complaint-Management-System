
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.database import get_db
from app.models.complaint import Complaint
from app.models.user import UserRole
from app.schemas.reports import (
    CategoryReport,
    ComplaintOverviewReport,
    DashboardReport,
    PriorityReport,
    ResolutionMetricsReport,
    SLAReport,
    SeverityReport,
    StatusReport,
)
from app.services.report_export import export_complaints_csv
from app.services.reports import (
    get_category_report,
    get_complaint_overview,
    get_enum_report,
    get_resolution_metrics,
    get_sla_report,
)

router = APIRouter(
    prefix="/reports",
    tags=["Reporting and Analytics"],
)

REPORT_ROLES = (
    UserRole.ADMIN,
    UserRole.SUPPORT_MANAGER,
)


@router.get(
    "/dashboard",
    response_model=DashboardReport,
)
def dashboard_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(*REPORT_ROLES)),
):
    priorities = get_enum_report(db, Complaint.priority)
    severities = get_enum_report(db, Complaint.severity)
    statuses = get_enum_report(db, Complaint.status)

    return {
        "generated_at": datetime.now(timezone.utc),
        "overview": get_complaint_overview(db),
        "categories": get_category_report(db),
        "priorities": [
            {
                "priority": item["name"],
                "complaint_count": item["count"],
            }
            for item in priorities
        ],
        "severities": [
            {
                "severity": item["name"],
                "complaint_count": item["count"],
            }
            for item in severities
        ],
        "statuses": [
            {
                "status": item["name"],
                "complaint_count": item["count"],
            }
            for item in statuses
        ],
        "resolution_metrics": get_resolution_metrics(db),
        "sla": get_sla_report(db),
    }


@router.get(
    "/overview",
    response_model=ComplaintOverviewReport,
)
def complaint_overview(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(*REPORT_ROLES)),
):
    return get_complaint_overview(db)


@router.get(
    "/categories",
    response_model=list[CategoryReport],
)
def category_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(*REPORT_ROLES)),
):
    return get_category_report(db)


@router.get(
    "/priorities",
    response_model=list[PriorityReport],
)
def priority_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(*REPORT_ROLES)),
):
    rows = get_enum_report(db, Complaint.priority)

    return [
        {
            "priority": item["name"],
            "complaint_count": item["count"],
        }
        for item in rows
    ]


@router.get(
    "/severities",
    response_model=list[SeverityReport],
)
def severity_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(*REPORT_ROLES)),
):
    rows = get_enum_report(db, Complaint.severity)

    return [
        {
            "severity": item["name"],
            "complaint_count": item["count"],
        }
        for item in rows
    ]


@router.get(
    "/statuses",
    response_model=list[StatusReport],
)
def status_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(*REPORT_ROLES)),
):
    rows = get_enum_report(db, Complaint.status)

    return [
        {
            "status": item["name"],
            "complaint_count": item["count"],
        }
        for item in rows
    ]


@router.get(
    "/resolution-metrics",
    response_model=ResolutionMetricsReport,
)
def resolution_metrics(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(*REPORT_ROLES)),
):
    return get_resolution_metrics(db)


@router.get(
    "/sla",
    response_model=SLAReport,
)
def sla_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(*REPORT_ROLES)),
):
    return get_sla_report(db)


# LEVEL 14: Export complaints as CSV

@router.get("/export/csv")
def export_complaints_report(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(*REPORT_ROLES)),
):
    if (
        start_date is not None
        and end_date is not None
        and start_date > end_date
    ):
        raise HTTPException(
            status_code=422,
            detail="start_date must be earlier than or equal to end_date",
        )

    csv_content = export_complaints_csv(
        db,
        start_date=start_date,
        end_date=end_date,
    )

    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="complaints_report.csv"'
            )
        },
    )
