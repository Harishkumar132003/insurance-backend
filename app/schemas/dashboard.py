from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


DashboardPeriod = Literal["7d", "30d", "90d", "this_month", "this_year", "custom"]


class DashboardKPIs(BaseModel):
    """Top stat strip — the four "what should I look at right now?" numbers."""
    action_needed_count: int
    awaiting_insurer_count: int
    # Average seconds waiting on the insurer across the cases counted above.
    # Null when no cases are awaiting (so the FE renders "—").
    awaiting_insurer_avg_wait_seconds: float | None = None
    outstanding_receivables_amount: float = 0.0
    outstanding_receivables_count: int = 0
    approved_this_month_count: int = 0
    approved_this_month_amount: float = 0.0


class FunnelStep(BaseModel):
    """One step of the money funnel — amount + how many cases reached it."""
    key: str
    label: str
    amount: float = 0.0
    count: int = 0


class ActivityItem(BaseModel):
    claim_case_id: UUID
    uhid: str | None = None
    patient_name: str | None = None
    provider_name: str | None = None
    # Only populated on the super-admin feed (cross-hospital). The hospital
    # dashboard leaves it null since every row belongs to the same hospital.
    hospital_name: str | None = None
    stage: str                 # PRE_AUTH / CLAIM
    status: str                # raw status
    amount: float | None = None
    remarks: str | None = None
    created_at: datetime


class InsurerStats(BaseModel):
    provider_id: UUID
    name: str
    cases: int = 0
    approved: int = 0
    denied: int = 0
    avg_tat_seconds: float | None = None      # provider TAT (decision time)
    outstanding_amount: float = 0.0
    approval_rate: float | None = None        # 0..1, null when no decisions
    denial_rate: float | None = None


class StatusBucket(BaseModel):
    key: str
    label: str
    count: int = 0


class VolumePoint(BaseModel):
    week_start: date
    submitted: int = 0
    settled: int = 0


class DiagnosisStat(BaseModel):
    diagnosis: str
    count: int


class CancellationReason(BaseModel):
    reason: str
    count: int


class HospitalAdminDashboard(BaseModel):
    period: DashboardPeriod
    generated_at: datetime
    # Resolved window — populated for every request so the FE always knows
    # what the response represents (especially handy for "custom").
    period_start: datetime
    period_end: datetime
    kpis: DashboardKPIs
    funnel: list[FunnelStep] = Field(default_factory=list)
    recent_activity: list[ActivityItem] = Field(default_factory=list)
    insurers: list[InsurerStats] = Field(default_factory=list)
    status_distribution: list[StatusBucket] = Field(default_factory=list)
    volume_trend: list[VolumePoint] = Field(default_factory=list)
    top_diagnoses: list[DiagnosisStat] = Field(default_factory=list)
    adr_resolution_days: float | None = None
    cancellation_reasons: list[CancellationReason] = Field(default_factory=list)


# ─── Super-admin (platform-wide) dashboard ────────────────────────────

class SuperAdminKPIs(BaseModel):
    """Headline numbers for the whole platform. Counts/amounts under
    "in window" honour the selected date range; receivables are current
    (all unpaid invoices regardless of when the case was created)."""
    total_cases: int = 0                       # cases created in window
    action_needed_count: int = 0
    awaiting_insurer_count: int = 0
    awaiting_insurer_avg_wait_seconds: float | None = None
    approved_cases: int = 0
    approved_amount: float = 0.0
    approval_rate: float | None = None         # 0..1 over decisions in window
    outstanding_receivables_amount: float = 0.0
    outstanding_receivables_count: int = 0


class HospitalStats(BaseModel):
    """One leaderboard row per hospital."""
    hospital_id: UUID
    name: str
    cases: int = 0
    approved: int = 0
    denied: int = 0
    approval_rate: float | None = None
    avg_tat_seconds: float | None = None
    outstanding_amount: float = 0.0


class ProviderStats(BaseModel):
    """Per-payer performance across the whole platform."""
    provider_id: UUID
    name: str
    is_onboarded: bool = False
    cases: int = 0
    approved: int = 0
    denied: int = 0
    approval_rate: float | None = None
    avg_tat_seconds: float | None = None
    outstanding_amount: float = 0.0


class AdoptionStats(BaseModel):
    """Platform reach + how much volume flows through the onboarded
    (in-app) path vs the external (email) path."""
    hospitals_total: int = 0
    hospitals_active: int = 0                   # have >=1 non-cancelled case
    providers_total: int = 0
    providers_onboarded: int = 0
    providers_external: int = 0
    active_mappings: int = 0                     # active hospital↔provider MOUs
    users_total: int = 0
    users_by_role: dict[str, int] = Field(default_factory=dict)
    onboarded_case_count: int = 0               # cases in window via onboarded
    external_case_count: int = 0                # cases in window via external
    onboarded_case_share: float | None = None   # 0..1, null when no cases


class SuperAdminDashboard(BaseModel):
    period: DashboardPeriod
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    kpis: SuperAdminKPIs
    adoption: AdoptionStats
    funnel: list[FunnelStep] = Field(default_factory=list)
    hospitals: list[HospitalStats] = Field(default_factory=list)
    providers: list[ProviderStats] = Field(default_factory=list)
    status_distribution: list[StatusBucket] = Field(default_factory=list)
    volume_trend: list[VolumePoint] = Field(default_factory=list)
    recent_activity: list[ActivityItem] = Field(default_factory=list)
