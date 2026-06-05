from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import dashboard_controller, super_admin_dashboard_controller
from app.core.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import (
    DashboardPeriod,
    HospitalAdminDashboard,
    SuperAdminDashboard,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/hospital-admin", response_model=HospitalAdminDashboard)
def hospital_admin_dashboard(
    period: DashboardPeriod = Query(default="30d"),
    start: str | None = Query(default=None, description="ISO date / datetime — start of range (used with period=custom)"),
    end: str | None = Query(default=None, description="ISO date / datetime — end of range (used with period=custom)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One-shot payload powering the hospital-admin dashboard. All metrics
    are aggregated in Postgres; the response is typed end-to-end."""
    return dashboard_controller.get_hospital_admin_dashboard(
        db, current_user, period, start=start, end=end,
    )


@router.get("/super-admin", response_model=SuperAdminDashboard)
def super_admin_dashboard(
    period: DashboardPeriod = Query(default="30d"),
    start: str | None = Query(default=None, description="ISO date / datetime — start of range (used with period=custom)"),
    end: str | None = Query(default=None, description="ISO date / datetime — end of range (used with period=custom)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Platform-wide rollup for super admins — every metric spans all
    hospitals and payers, with per-hospital and per-provider breakdowns."""
    return super_admin_dashboard_controller.get_super_admin_dashboard(
        db, current_user, period, start=start, end=end,
    )
