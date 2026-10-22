
from datetime import datetime

from pydantic import BaseModel


class CountReport(BaseModel):
    name: str
    count: int


class ComplaintOverviewReport(BaseModel):
    total_complaints: int
    open_complaints: int
    assigned_complaints: int
    in_progress_complaints: int
    waiting_for_customer_complaints: int
    reopened_complaints: int
    resolved_complaints: int
    closed_complaints: int


class CategoryReport(BaseModel):
    category_id: int
    category_name: str
    complaint_count: int


class PriorityReport(BaseModel):
    priority: str
    complaint_count: int


class SeverityReport(BaseModel):
    severity: str
    complaint_count: int


class StatusReport(BaseModel):
    status: str
    complaint_count: int


class ResolutionMetricsReport(BaseModel):
    resolved_complaints: int
    average_resolution_hours: float | None
    unresolved_complaints: int


class SLAReport(BaseModel):
    total_complaints: int
    response_breached: int
    resolution_breached: int
    response_compliant: int
    resolution_compliant: int


class ReportDateRange(BaseModel):
    start_date: datetime | None = None
    end_date: datetime | None = None


class ReportResponse(BaseModel):
    report_name: str
    generated_at: datetime
    data: list[CountReport]


class DashboardReport(BaseModel):
    generated_at: datetime
    overview: ComplaintOverviewReport
    categories: list[CategoryReport]
    priorities: list[PriorityReport]
    severities: list[SeverityReport]
    statuses: list[StatusReport]
    resolution_metrics: ResolutionMetricsReport
    sla: SLAReport
