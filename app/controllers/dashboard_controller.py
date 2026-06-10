"""Hospital-admin dashboard.

One endpoint, one DB round-trip per widget. Every query is a single-pass
aggregation pushed to Postgres — the controller assembles the typed response
without doing any per-row work in Python. This keeps the endpoint <100ms even
for tens of thousands of cases as long as the existing indexes are in place
(hospitalization.hospital_id, status_history.claim_case_id,
claim.claim_case_id, invoice.claim_case_id, pre_auth_patient.form_data_id).
"""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status as http_status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.dashboard import (
    ActivityItem,
    CancellationReason,
    DashboardKPIs,
    DashboardPeriod,
    DiagnosisStat,
    FunnelStep,
    HospitalAdminDashboard,
    InsurerStats,
    StatusBucket,
    VolumePoint,
)


# Status buckets used across queries.
ACTION_NEEDED_STATUSES = (
    "DENIED", "ADR_NMI", "ENHANCEMENT_DENIED",
    "CLAIM_DENIED", "CLAIM_ADR_NMI",
)
AWAITING_INSURER_STATUSES = (
    "SUBMITTED", "ENHANCE_SUBMITTED", "RECONSIDER", "RECONSIDER_SUBMITTED",
    "ADR_SUBMITTED",
    "CLAIM_SUBMITTED", "CLAIM_ADR_SUBMITTED", "CLAIM_RECONSIDER",
)
APPROVED_STATUSES = ("APPROVED", "PARTIALLY_APPROVED", "ENHANCEMENT_APPROVED")
DENIED_STATUSES = ("DENIED", "ENHANCEMENT_DENIED", "CLAIM_DENIED")


def _coerce_bound(value) -> datetime | None:
    """Accept a date / datetime / ISO string and return a tz-aware datetime
    (UTC) or None. Used to normalise the optional `start`/`end` query params."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            # Plain YYYY-MM-DD or full ISO 8601 — both supported.
            if len(s) == 10:
                d = date.fromisoformat(s)
                return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date: {value!r} (expected YYYY-MM-DD or ISO 8601)",
            )
    return None


def _resolve_window(
    period: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Return (since, until) for any request. Custom range overrides the
    preset; presets use NOW() as the upper bound."""
    now = datetime.now(timezone.utc)
    if period == "custom":
        since = start or (now - timedelta(days=30))
        until = end or now
        if until <= since:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="end must be after start",
            )
        return since, until
    if period == "7d":
        return now - timedelta(days=7), now
    if period == "30d":
        return now - timedelta(days=30), now
    if period == "90d":
        return now - timedelta(days=90), now
    if period == "this_month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
    if period == "this_year":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), now
    return now - timedelta(days=30), now


def get_hospital_admin_dashboard(
    db: Session,
    current_user: User,
    period: DashboardPeriod = "30d",
    start: str | None = None,
    end: str | None = None,
) -> HospitalAdminDashboard:
    if current_user.role != "HOSPITAL_ADMIN":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only hospital admins can view the dashboard",
        )
    if not current_user.hospital_id:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="User is not linked to a hospital",
        )

    hospital_id = current_user.hospital_id
    since, until = _resolve_window(period, _coerce_bound(start), _coerce_bound(end))
    params = {"hospital_id": hospital_id, "since": since, "until": until}

    return HospitalAdminDashboard(
        period=period,
        period_start=since,
        period_end=until,
        generated_at=datetime.now(timezone.utc),
        kpis=_kpis(db, params),
        funnel=_funnel(db, params),
        recent_activity=_recent_activity(db, params),
        insurers=_insurers(db, params),
        status_distribution=_status_distribution(db, hospital_id),
        volume_trend=_volume_trend(db, params),
        top_diagnoses=_top_diagnoses(db, params),
        adr_resolution_days=_adr_resolution_days(db, hospital_id),
        cancellation_reasons=_cancellation_reasons(db, params),
    )


# ─── KPI strip ────────────────────────────────────────────────────────

def _kpis(db: Session, params: dict) -> DashboardKPIs:
    """All four KPIs are scoped to the active date range — they only consider
    cases whose `hospitalization.created_at` lies in [since, until). The
    "approved" KPI additionally filters approval events themselves by range."""
    row = db.execute(text("""
        WITH cases AS (
            SELECT h.id, h.case_status AS status
              FROM hospitalization h
             WHERE h.hospital_id = :hospital_id
               AND h.case_status <> 'CANCELLED'
               AND h.created_at >= :since
               AND h.created_at <  :until
        ),
        latest AS (
            SELECT DISTINCT ON (sh.claim_case_id)
                   sh.claim_case_id, sh.status, sh.created_at
              FROM status_history sh
              JOIN cases c ON c.id = sh.claim_case_id
             ORDER BY sh.claim_case_id, sh.created_at DESC
        )
        SELECT
            (SELECT count(*) FROM cases c
              LEFT JOIN latest l ON l.claim_case_id = c.id
              WHERE l.status = ANY(:action_statuses) OR c.status = 'DRAFT'
            ) AS action_needed,
            (SELECT count(*) FROM latest WHERE status = ANY(:awaiting_statuses))
              AS awaiting_count,
            (SELECT AVG(EXTRACT(EPOCH FROM (NOW() - created_at)))
               FROM latest WHERE status = ANY(:awaiting_statuses))
              AS awaiting_avg_seconds
    """), {
        **params,
        "action_statuses": list(ACTION_NEEDED_STATUSES),
        "awaiting_statuses": list(AWAITING_INSURER_STATUSES),
    }).mappings().first()

    # Outstanding receivables — invoices on cases born in range.
    receivables = db.execute(text("""
        SELECT COUNT(i.id) AS invoice_count,
               COALESCE(SUM(i.insurer_amount - COALESCE(p.paid, 0)), 0) AS outstanding
          FROM invoice i
          JOIN hospitalization h ON h.id = i.claim_case_id
          LEFT JOIN (
            SELECT invoice_id, SUM(amount) AS paid
              FROM invoice_payment GROUP BY invoice_id
          ) p ON p.invoice_id = i.id
         WHERE h.hospital_id = :hospital_id
           AND i.status <> 'PAID'
           AND h.created_at >= :since
           AND h.created_at <  :until
    """), params).mappings().first()

    # Approved in period — approval events whose status_history.created_at
    # falls in the active range. Doesn't require the case itself to have been
    # born in the range (an old case can still be approved this week).
    approved = db.execute(text("""
        SELECT COUNT(DISTINCT sh.claim_case_id) AS cases,
               COALESCE(SUM(sh.approved_amount), 0) AS amount
          FROM status_history sh
          JOIN hospitalization h ON h.id = sh.claim_case_id
         WHERE h.hospital_id = :hospital_id
           AND sh.status = ANY(:approved_statuses)
           AND sh.created_at >= :since
           AND sh.created_at <  :until
    """), {**params, "approved_statuses": list(APPROVED_STATUSES)}).mappings().first()

    return DashboardKPIs(
        action_needed_count=row["action_needed"] or 0,
        awaiting_insurer_count=row["awaiting_count"] or 0,
        awaiting_insurer_avg_wait_seconds=(
            float(row["awaiting_avg_seconds"]) if row["awaiting_avg_seconds"] is not None else None
        ),
        outstanding_receivables_amount=float(receivables["outstanding"] or 0),
        outstanding_receivables_count=receivables["invoice_count"] or 0,
        approved_this_month_count=approved["cases"] or 0,
        approved_this_month_amount=float(approved["amount"] or 0),
    )


# ─── Money funnel ─────────────────────────────────────────────────────

def _funnel(db: Session, params: dict) -> list[FunnelStep]:
    """Six funnel steps in one query. All values are scoped to the period
    (case created_at >= since) — represents the *cohort* born in this window."""
    row = db.execute(text("""
        WITH cases AS (
            SELECT id FROM hospitalization
             WHERE hospital_id = :hospital_id
               AND created_at >= :since
               AND created_at <  :until
               AND case_status <> 'CANCELLED'
        ),
        requested AS (
            -- Latest PRE_AUTH form per case, summed.
            SELECT COUNT(DISTINCT pa.claim_case_id) AS cnt,
                   COALESCE(SUM(s.total_cost), 0)    AS amt
              FROM cases c
              JOIN pre_auth pa ON pa.claim_case_id = c.id AND pa.stage = 'PRE_AUTH'
              JOIN pre_auth_stay s ON s.form_data_id = pa.id
        ),
        approved AS (
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(h.approved_amount), 0) AS amt
              FROM cases c
              JOIN hospitalization h ON h.id = c.id
             WHERE h.approved_amount IS NOT NULL AND h.approved_amount > 0
        ),
        claimed AS (
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(cl.claimed_amount), 0) AS amt
              FROM cases c
              JOIN claims cl ON cl.claim_case_id = c.id
        ),
        claim_approved AS (
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(cl.approved_amount), 0) AS amt
              FROM cases c
              JOIN claims cl ON cl.claim_case_id = c.id
             WHERE cl.approved_amount IS NOT NULL AND cl.approved_amount > 0
        ),
        invoiced AS (
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(i.insurer_amount), 0) AS amt
              FROM cases c
              JOIN invoice i ON i.claim_case_id = c.id
        ),
        paid AS (
            SELECT COUNT(DISTINCT i.id) AS cnt,
                   COALESCE(SUM(p.amount), 0)         AS amt
              FROM cases c
              JOIN invoice i ON i.claim_case_id = c.id
              JOIN invoice_payment p ON p.invoice_id = i.id
        )
        SELECT requested.cnt       AS req_c, requested.amt       AS req_a,
               approved.cnt        AS app_c, approved.amt        AS app_a,
               claimed.cnt         AS cla_c, claimed.amt         AS cla_a,
               claim_approved.cnt  AS cap_c, claim_approved.amt  AS cap_a,
               invoiced.cnt        AS inv_c, invoiced.amt        AS inv_a,
               paid.cnt            AS pay_c, paid.amt            AS pay_a
          FROM requested, approved, claimed, claim_approved, invoiced, paid
    """), params).mappings().first()

    steps = [
        ("requested", "Requested", row["req_a"], row["req_c"]),
        ("approved", "Pre-Auth Approved", row["app_a"], row["app_c"]),
        ("claimed", "Claim Raised", row["cla_a"], row["cla_c"]),
        ("claim_approved", "Claim Approved", row["cap_a"], row["cap_c"]),
        ("invoiced", "Invoiced", row["inv_a"], row["inv_c"]),
        ("paid", "Settled", row["pay_a"], row["pay_c"]),
    ]
    return [
        FunnelStep(key=k, label=l, amount=float(a or 0), count=int(c or 0))
        for k, l, a, c in steps
    ]


# ─── Recent activity ──────────────────────────────────────────────────

def _recent_activity(db: Session, params: dict, limit: int = 5) -> list[ActivityItem]:
    rows = db.execute(text("""
        SELECT sh.id, sh.stage, sh.status, sh.approved_amount, sh.created_at, sh.remarks,
               h.id AS claim_case_id, h.uhid,
               pp.name AS provider_name,
               (SELECT pp2.patient_name
                  FROM pre_auth pa
                  JOIN pre_auth_patient pp2 ON pp2.form_data_id = pa.id
                 WHERE pa.claim_case_id = h.id AND pa.stage <> 'CLAIM'
                 ORDER BY pa.created_at DESC
                 LIMIT 1) AS patient_name
          FROM status_history sh
          JOIN hospitalization h ON h.id = sh.claim_case_id
          LEFT JOIN policy_provider_configs pp ON pp.id = h.policy_provider_id
         WHERE h.hospital_id = :hospital_id
           AND sh.created_at >= :since
           AND sh.created_at <  :until
         ORDER BY sh.created_at DESC
         LIMIT :limit
    """), {**params, "limit": limit}).mappings().all()
    return [
        ActivityItem(
            claim_case_id=r["claim_case_id"],
            uhid=r["uhid"],
            patient_name=r["patient_name"],
            provider_name=r["provider_name"],
            stage=r["stage"],
            status=r["status"],
            amount=float(r["approved_amount"]) if r["approved_amount"] is not None else None,
            remarks=r["remarks"],
            created_at=r["created_at"],
        ) for r in rows
    ]


# ─── Insurer performance ──────────────────────────────────────────────

def _insurers(db: Session, params: dict) -> list[InsurerStats]:
    """One row per provider mapped to this hospital, with rolled-up metrics."""
    rows = db.execute(text("""
        WITH cases AS (
            SELECT h.id, h.policy_provider_id
              FROM hospitalization h
             WHERE h.hospital_id = :hospital_id
               AND h.created_at >= :since
               AND h.created_at <  :until
               AND h.case_status <> 'CANCELLED'
        ),
        decisions AS (
            -- Each status_history row that's an approval or denial counts as
            -- one decision; we average by provider.
            SELECT c.policy_provider_id,
                   COUNT(*) FILTER (WHERE sh.status = ANY(:approved_statuses)) AS approved,
                   COUNT(*) FILTER (WHERE sh.status = ANY(:denied_statuses))   AS denied
              FROM cases c
              JOIN status_history sh ON sh.claim_case_id = c.id
             GROUP BY c.policy_provider_id
        ),
        tats AS (
            -- TAT = first RECEIVED reply minus first SENT email per case.
            -- Computed per case then averaged per provider.
            SELECT c.policy_provider_id,
                   AVG(EXTRACT(EPOCH FROM (r.received_at - s.sent_at))) AS avg_tat
              FROM cases c
              JOIN LATERAL (
                   SELECT MIN(created_at) AS sent_at
                     FROM claim_case_emails
                    WHERE claim_case_id = c.id AND direction = 'SENT'
              ) s ON TRUE
              JOIN LATERAL (
                   SELECT MIN(created_at) AS received_at
                     FROM claim_case_emails
                    WHERE claim_case_id = c.id AND direction = 'RECEIVED'
              ) r ON TRUE
             WHERE r.received_at IS NOT NULL AND s.sent_at IS NOT NULL
               AND r.received_at > s.sent_at
             GROUP BY c.policy_provider_id
        ),
        outstanding AS (
            SELECT h.policy_provider_id,
                   COALESCE(SUM(i.insurer_amount - COALESCE(p.paid, 0)), 0) AS amt
              FROM hospitalization h
              JOIN invoice i ON i.claim_case_id = h.id
              LEFT JOIN (
                   SELECT invoice_id, SUM(amount) AS paid
                     FROM invoice_payment GROUP BY invoice_id
              ) p ON p.invoice_id = i.id
             WHERE h.hospital_id = :hospital_id
               AND i.status <> 'PAID'
               AND h.created_at >= :since
               AND h.created_at <  :until
             GROUP BY h.policy_provider_id
        )
        SELECT pp.id AS provider_id, pp.name,
               COALESCE((SELECT COUNT(*) FROM cases WHERE policy_provider_id = pp.id), 0) AS cases,
               COALESCE(d.approved, 0) AS approved,
               COALESCE(d.denied, 0)   AS denied,
               t.avg_tat,
               COALESCE(o.amt, 0)      AS outstanding
          FROM policy_provider_configs pp
          JOIN hospital_provider_mappings hpm
            ON hpm.policy_provider_id = pp.id
           AND hpm.hospital_id = :hospital_id
          LEFT JOIN decisions d   ON d.policy_provider_id = pp.id
          LEFT JOIN tats t        ON t.policy_provider_id = pp.id
          LEFT JOIN outstanding o ON o.policy_provider_id = pp.id
         ORDER BY cases DESC, pp.name
    """), {
        **params,
        "approved_statuses": list(APPROVED_STATUSES),
        "denied_statuses": list(DENIED_STATUSES),
    }).mappings().all()

    out = []
    for r in rows:
        decisions = (r["approved"] or 0) + (r["denied"] or 0)
        out.append(InsurerStats(
            provider_id=r["provider_id"],
            name=r["name"],
            cases=r["cases"] or 0,
            approved=r["approved"] or 0,
            denied=r["denied"] or 0,
            avg_tat_seconds=float(r["avg_tat"]) if r["avg_tat"] is not None else None,
            outstanding_amount=float(r["outstanding"] or 0),
            approval_rate=(r["approved"] / decisions) if decisions else None,
            denial_rate=(r["denied"] / decisions) if decisions else None,
        ))
    return out


# ─── Status distribution ──────────────────────────────────────────────

def _status_distribution(db: Session, hospital_id: UUID) -> list[StatusBucket]:
    """Five buckets covering the open pipeline."""
    row = db.execute(text("""
        SELECT
            COUNT(*) FILTER (
                WHERE h.current_stage = 'PRE_AUTH' AND h.case_status = 'SUBMITTED'
            ) AS pre_auth_submitted,
            COUNT(*) FILTER (
                WHERE h.current_stage = 'PRE_AUTH'
                  AND h.approved_amount IS NOT NULL AND h.approved_amount > 0
                  AND NOT EXISTS (SELECT 1 FROM claims WHERE claim_case_id = h.id)
            ) AS pre_auth_approved,
            COUNT(*) FILTER (
                WHERE h.current_stage = 'CLAIM' AND h.case_status = 'CLAIM_SUBMITTED'
            ) AS claim_submitted,
            COUNT(*) FILTER (
                WHERE EXISTS (SELECT 1 FROM claims c WHERE c.claim_case_id = h.id
                                AND c.approved_amount IS NOT NULL AND c.approved_amount > 0)
                  AND NOT EXISTS (SELECT 1 FROM invoice WHERE claim_case_id = h.id)
            ) AS claim_approved_no_invoice,
            COUNT(*) FILTER (
                WHERE EXISTS (SELECT 1 FROM invoice i WHERE i.claim_case_id = h.id
                                AND i.status <> 'PAID')
            ) AS invoice_open
          FROM hospitalization h
         WHERE h.hospital_id = :hospital_id
           AND h.case_status <> 'CANCELLED'
    """), {"hospital_id": hospital_id}).mappings().first()

    return [
        StatusBucket(key="pre_auth_submitted", label="Pre-Auth Submitted",   count=row["pre_auth_submitted"] or 0),
        StatusBucket(key="pre_auth_approved",  label="Ready to Claim",       count=row["pre_auth_approved"] or 0),
        StatusBucket(key="claim_submitted",    label="Claim Submitted",      count=row["claim_submitted"] or 0),
        StatusBucket(key="claim_approved",     label="Ready to Invoice",     count=row["claim_approved_no_invoice"] or 0),
        StatusBucket(key="invoice_open",       label="Invoice Outstanding",  count=row["invoice_open"] or 0),
    ]


# ─── Volume trend ─────────────────────────────────────────────────────

def _volume_trend(db: Session, params: dict) -> list[VolumePoint]:
    """Submitted vs Settled per ISO week. The bucket series is generated
    inside the picked [since, until) range, so the chart always matches the
    selector."""
    rows = db.execute(text("""
        WITH series AS (
            SELECT generate_series(
                date_trunc('week', :since),
                date_trunc('week', :until),
                INTERVAL '1 week'
            )::date AS week_start
        ),
        submitted AS (
            SELECT date_trunc('week', sh.created_at)::date AS week_start,
                   COUNT(*) AS n
              FROM status_history sh
              JOIN hospitalization h ON h.id = sh.claim_case_id
             WHERE h.hospital_id = :hospital_id
               AND sh.status IN ('SUBMITTED', 'CLAIM_SUBMITTED')
               AND sh.created_at >= :since
               AND sh.created_at <  :until
             GROUP BY 1
        ),
        settled AS (
            -- Invoice marked PAID in week (uses updated_at since that's when
            -- the auto-derive flipped it).
            SELECT date_trunc('week', i.updated_at)::date AS week_start,
                   COUNT(*) AS n
              FROM invoice i
              JOIN hospitalization h ON h.id = i.claim_case_id
             WHERE h.hospital_id = :hospital_id
               AND i.status = 'PAID'
               AND i.updated_at >= :since
               AND i.updated_at <  :until
             GROUP BY 1
        )
        SELECT s.week_start,
               COALESCE(sub.n, 0) AS submitted,
               COALESCE(sett.n, 0) AS settled
          FROM series s
          LEFT JOIN submitted sub  ON sub.week_start  = s.week_start
          LEFT JOIN settled   sett ON sett.week_start = s.week_start
         ORDER BY s.week_start
    """), params).mappings().all()
    return [
        VolumePoint(
            week_start=r["week_start"],
            submitted=r["submitted"] or 0,
            settled=r["settled"] or 0,
        ) for r in rows
    ]


# ─── Top diagnoses ────────────────────────────────────────────────────

def _top_diagnoses(db: Session, params: dict, limit: int = 5) -> list[DiagnosisStat]:
    rows = db.execute(text("""
        SELECT pt.provisional_diagnosis AS diagnosis, COUNT(*) AS n
          FROM pre_auth pa
          JOIN hospitalization h ON h.id = pa.claim_case_id
          JOIN pre_auth_treatment pt ON pt.form_data_id = pa.id
         WHERE h.hospital_id = :hospital_id
           AND pa.created_at >= :since
           AND pa.created_at <  :until
           AND pa.stage <> 'CLAIM'
           AND pt.provisional_diagnosis IS NOT NULL
           AND TRIM(pt.provisional_diagnosis) <> ''
         GROUP BY pt.provisional_diagnosis
         ORDER BY n DESC
         LIMIT :limit
    """), {**params, "limit": limit}).mappings().all()
    return [DiagnosisStat(diagnosis=r["diagnosis"], count=r["n"]) for r in rows]


# ─── ADR resolution time ──────────────────────────────────────────────

def _adr_resolution_days(db: Session, hospital_id: UUID) -> float | None:
    row = db.execute(text("""
        SELECT AVG(EXTRACT(EPOCH FROM (q.resolved_at - q.created_at)) / 86400.0) AS avg_days
          FROM query_logs q
          JOIN hospitalization h ON h.id = q.claim_case_id
         WHERE h.hospital_id = :hospital_id
           AND q.query_type = 'ADR_NMI'
           AND q.resolved_at IS NOT NULL
    """), {"hospital_id": hospital_id}).mappings().first()
    val = row["avg_days"] if row else None
    return float(val) if val is not None else None


# ─── Cancellation reasons ─────────────────────────────────────────────

def _cancellation_reasons(db: Session, params: dict, limit: int = 5) -> list[CancellationReason]:
    rows = db.execute(text("""
        SELECT sh.remarks AS reason, COUNT(*) AS n
          FROM status_history sh
          JOIN hospitalization h ON h.id = sh.claim_case_id
         WHERE h.hospital_id = :hospital_id
           AND sh.status = 'CANCELLED'
           AND sh.created_at >= :since
           AND sh.created_at <  :until
           AND sh.remarks IS NOT NULL
           AND TRIM(sh.remarks) <> ''
         GROUP BY sh.remarks
         ORDER BY n DESC
         LIMIT :limit
    """), {**params, "limit": limit}).mappings().all()
    return [CancellationReason(reason=r["reason"], count=r["n"]) for r in rows]
