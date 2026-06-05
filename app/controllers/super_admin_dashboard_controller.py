"""Super-admin (platform-wide) dashboard.

Same shape and performance contract as the hospital-admin dashboard
(`dashboard_controller`), but with the `hospital_id` scope removed: every
widget rolls up across *all* hospitals and payers, with GROUP BY rollups for
the hospital leaderboard and per-provider performance. Each query is a
single-pass aggregation pushed to Postgres.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status as http_status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.controllers.dashboard_controller import (
    ACTION_NEEDED_STATUSES,
    APPROVED_STATUSES,
    AWAITING_INSURER_STATUSES,
    DENIED_STATUSES,
    _coerce_bound,
    _resolve_window,
)
from app.models.user import User
from app.schemas.dashboard import (
    ActivityItem,
    AdoptionStats,
    DashboardPeriod,
    FunnelStep,
    HospitalStats,
    ProviderStats,
    StatusBucket,
    SuperAdminDashboard,
    SuperAdminKPIs,
    VolumePoint,
)

# Cap the leaderboard/provider tables so a huge tenant base can't bloat the
# payload. Ordered by volume, so the busiest entities always make the cut.
HOSPITAL_LIMIT = 50
PROVIDER_LIMIT = 50


def get_super_admin_dashboard(
    db: Session,
    current_user: User,
    period: DashboardPeriod = "30d",
    start: str | None = None,
    end: str | None = None,
) -> SuperAdminDashboard:
    if current_user.role != "SUPER_ADMIN":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only super admins can view the platform dashboard",
        )

    since, until = _resolve_window(period, _coerce_bound(start), _coerce_bound(end))
    params = {"since": since, "until": until}

    return SuperAdminDashboard(
        period=period,
        period_start=since,
        period_end=until,
        generated_at=datetime.now(timezone.utc),
        kpis=_kpis(db, params),
        adoption=_adoption(db, params),
        funnel=_funnel(db, params),
        hospitals=_hospitals(db, params),
        providers=_providers(db, params),
        status_distribution=_status_distribution(db),
        volume_trend=_volume_trend(db, params),
        recent_activity=_recent_activity(db, params),
    )


# ─── KPI strip ────────────────────────────────────────────────────────

def _kpis(db: Session, params: dict) -> SuperAdminKPIs:
    row = db.execute(text("""
        WITH cases AS (
            SELECT h.id, h.status
              FROM hospitalization h
             WHERE h.status <> 'CANCELLED'
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
            (SELECT count(*) FROM cases) AS total_cases,
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

    # Approval activity in window — events whose status_history.created_at
    # falls in the range (an old case can still be decided this week).
    decisions = db.execute(text("""
        SELECT COUNT(DISTINCT sh.claim_case_id)
                 FILTER (WHERE sh.status = ANY(:approved_statuses)) AS approved_cases,
               COALESCE(SUM(sh.approved_amount)
                 FILTER (WHERE sh.status = ANY(:approved_statuses)), 0) AS approved_amount,
               COUNT(*) FILTER (WHERE sh.status = ANY(:approved_statuses)) AS approved,
               COUNT(*) FILTER (WHERE sh.status = ANY(:denied_statuses))   AS denied
          FROM status_history sh
         WHERE sh.created_at >= :since
           AND sh.created_at <  :until
    """), {
        **params,
        "approved_statuses": list(APPROVED_STATUSES),
        "denied_statuses": list(DENIED_STATUSES),
    }).mappings().first()

    # Outstanding receivables — current snapshot across the whole platform
    # (every unpaid invoice), independent of the date window.
    receivables = db.execute(text("""
        SELECT COUNT(i.id) AS invoice_count,
               COALESCE(SUM(i.insurer_amount - COALESCE(p.paid, 0)), 0) AS outstanding
          FROM invoice i
          LEFT JOIN (
            SELECT invoice_id, SUM(amount) AS paid
              FROM invoice_payment GROUP BY invoice_id
          ) p ON p.invoice_id = i.id
         WHERE i.status <> 'PAID'
    """)).mappings().first()

    decided = (decisions["approved"] or 0) + (decisions["denied"] or 0)
    return SuperAdminKPIs(
        total_cases=row["total_cases"] or 0,
        action_needed_count=row["action_needed"] or 0,
        awaiting_insurer_count=row["awaiting_count"] or 0,
        awaiting_insurer_avg_wait_seconds=(
            float(row["awaiting_avg_seconds"]) if row["awaiting_avg_seconds"] is not None else None
        ),
        approved_cases=decisions["approved_cases"] or 0,
        approved_amount=float(decisions["approved_amount"] or 0),
        approval_rate=(decisions["approved"] / decided) if decided else None,
        outstanding_receivables_amount=float(receivables["outstanding"] or 0),
        outstanding_receivables_count=receivables["invoice_count"] or 0,
    )


# ─── Adoption / reach ─────────────────────────────────────────────────

def _adoption(db: Session, params: dict) -> AdoptionStats:
    totals = db.execute(text("""
        SELECT
            (SELECT count(*) FROM hospitals) AS hospitals_total,
            (SELECT count(DISTINCT hospital_id) FROM hospitalization
              WHERE status <> 'CANCELLED' AND hospital_id IS NOT NULL) AS hospitals_active,
            (SELECT count(*) FROM policy_provider_configs) AS providers_total,
            (SELECT count(*) FROM policy_provider_configs WHERE is_onboarded) AS providers_onboarded,
            (SELECT count(*) FROM hospital_provider_mappings WHERE is_active) AS active_mappings,
            (SELECT count(*) FROM users) AS users_total
    """)).mappings().first()

    roles = db.execute(text("""
        SELECT role, count(*) AS n FROM users GROUP BY role
    """)).mappings().all()

    # Onboarded vs external case split over the window.
    split = db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE pp.is_onboarded) AS onboarded,
            COUNT(*) FILTER (WHERE NOT pp.is_onboarded) AS external
          FROM hospitalization h
          JOIN policy_provider_configs pp ON pp.id = h.policy_provider_id
         WHERE h.status <> 'CANCELLED'
           AND h.created_at >= :since
           AND h.created_at <  :until
    """), params).mappings().first()

    onboarded = split["onboarded"] or 0
    external = split["external"] or 0
    total = onboarded + external
    providers_total = totals["providers_total"] or 0
    providers_onboarded = totals["providers_onboarded"] or 0
    return AdoptionStats(
        hospitals_total=totals["hospitals_total"] or 0,
        hospitals_active=totals["hospitals_active"] or 0,
        providers_total=providers_total,
        providers_onboarded=providers_onboarded,
        providers_external=providers_total - providers_onboarded,
        active_mappings=totals["active_mappings"] or 0,
        users_total=totals["users_total"] or 0,
        users_by_role={r["role"]: r["n"] for r in roles},
        onboarded_case_count=onboarded,
        external_case_count=external,
        onboarded_case_share=(onboarded / total) if total else None,
    )


# ─── Money funnel ─────────────────────────────────────────────────────

def _funnel(db: Session, params: dict) -> list[FunnelStep]:
    """Identical to the hospital funnel, minus the hospital scope — the cohort
    is every (non-cancelled) case born in the window, platform-wide."""
    row = db.execute(text("""
        WITH cases AS (
            SELECT id FROM hospitalization
             WHERE created_at >= :since
               AND created_at <  :until
               AND status <> 'CANCELLED'
        ),
        requested AS (
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


# ─── Hospital leaderboard ─────────────────────────────────────────────

def _hospitals(db: Session, params: dict) -> list[HospitalStats]:
    """One row per hospital with cases in the window. TAT and decision rates
    come from the same per-case email / status_history logic the insurer card
    uses, rolled up by hospital instead of provider."""
    rows = db.execute(text("""
        WITH cases AS (
            SELECT h.id, h.hospital_id
              FROM hospitalization h
             WHERE h.hospital_id IS NOT NULL
               AND h.status <> 'CANCELLED'
               AND h.created_at >= :since
               AND h.created_at <  :until
        ),
        decisions AS (
            SELECT c.hospital_id,
                   COUNT(*) FILTER (WHERE sh.status = ANY(:approved_statuses)) AS approved,
                   COUNT(*) FILTER (WHERE sh.status = ANY(:denied_statuses))   AS denied
              FROM cases c
              JOIN status_history sh ON sh.claim_case_id = c.id
             GROUP BY c.hospital_id
        ),
        tats AS (
            SELECT c.hospital_id,
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
             GROUP BY c.hospital_id
        ),
        outstanding AS (
            SELECT h.hospital_id,
                   COALESCE(SUM(i.insurer_amount - COALESCE(p.paid, 0)), 0) AS amt
              FROM hospitalization h
              JOIN invoice i ON i.claim_case_id = h.id
              LEFT JOIN (
                   SELECT invoice_id, SUM(amount) AS paid
                     FROM invoice_payment GROUP BY invoice_id
              ) p ON p.invoice_id = i.id
             WHERE i.status <> 'PAID'
             GROUP BY h.hospital_id
        ),
        counts AS (
            SELECT hospital_id, COUNT(*) AS cases FROM cases GROUP BY hospital_id
        )
        SELECT hsp.id AS hospital_id, hsp.name,
               COALESCE(cn.cases, 0)   AS cases,
               COALESCE(d.approved, 0) AS approved,
               COALESCE(d.denied, 0)   AS denied,
               t.avg_tat,
               COALESCE(o.amt, 0)      AS outstanding
          FROM hospitals hsp
          JOIN counts cn          ON cn.hospital_id = hsp.id
          LEFT JOIN decisions d   ON d.hospital_id = hsp.id
          LEFT JOIN tats t        ON t.hospital_id = hsp.id
          LEFT JOIN outstanding o ON o.hospital_id = hsp.id
         ORDER BY cases DESC, hsp.name
         LIMIT :limit
    """), {
        **params,
        "approved_statuses": list(APPROVED_STATUSES),
        "denied_statuses": list(DENIED_STATUSES),
        "limit": HOSPITAL_LIMIT,
    }).mappings().all()

    out = []
    for r in rows:
        decided = (r["approved"] or 0) + (r["denied"] or 0)
        out.append(HospitalStats(
            hospital_id=r["hospital_id"],
            name=r["name"],
            cases=r["cases"] or 0,
            approved=r["approved"] or 0,
            denied=r["denied"] or 0,
            approval_rate=(r["approved"] / decided) if decided else None,
            avg_tat_seconds=float(r["avg_tat"]) if r["avg_tat"] is not None else None,
            outstanding_amount=float(r["outstanding"] or 0),
        ))
    return out


# ─── Provider performance (platform-wide) ─────────────────────────────

def _providers(db: Session, params: dict) -> list[ProviderStats]:
    rows = db.execute(text("""
        WITH cases AS (
            SELECT h.id, h.policy_provider_id
              FROM hospitalization h
             WHERE h.status <> 'CANCELLED'
               AND h.created_at >= :since
               AND h.created_at <  :until
        ),
        decisions AS (
            SELECT c.policy_provider_id,
                   COUNT(*) FILTER (WHERE sh.status = ANY(:approved_statuses)) AS approved,
                   COUNT(*) FILTER (WHERE sh.status = ANY(:denied_statuses))   AS denied
              FROM cases c
              JOIN status_history sh ON sh.claim_case_id = c.id
             GROUP BY c.policy_provider_id
        ),
        tats AS (
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
             WHERE i.status <> 'PAID'
             GROUP BY h.policy_provider_id
        ),
        counts AS (
            SELECT policy_provider_id, COUNT(*) AS cases
              FROM cases GROUP BY policy_provider_id
        )
        SELECT pp.id AS provider_id, pp.name, pp.is_onboarded,
               COALESCE(cn.cases, 0)   AS cases,
               COALESCE(d.approved, 0) AS approved,
               COALESCE(d.denied, 0)   AS denied,
               t.avg_tat,
               COALESCE(o.amt, 0)      AS outstanding
          FROM policy_provider_configs pp
          JOIN counts cn          ON cn.policy_provider_id = pp.id
          LEFT JOIN decisions d   ON d.policy_provider_id = pp.id
          LEFT JOIN tats t        ON t.policy_provider_id = pp.id
          LEFT JOIN outstanding o ON o.policy_provider_id = pp.id
         ORDER BY cases DESC, pp.name
         LIMIT :limit
    """), {
        **params,
        "approved_statuses": list(APPROVED_STATUSES),
        "denied_statuses": list(DENIED_STATUSES),
        "limit": PROVIDER_LIMIT,
    }).mappings().all()

    out = []
    for r in rows:
        decided = (r["approved"] or 0) + (r["denied"] or 0)
        out.append(ProviderStats(
            provider_id=r["provider_id"],
            name=r["name"],
            is_onboarded=bool(r["is_onboarded"]),
            cases=r["cases"] or 0,
            approved=r["approved"] or 0,
            denied=r["denied"] or 0,
            approval_rate=(r["approved"] / decided) if decided else None,
            avg_tat_seconds=float(r["avg_tat"]) if r["avg_tat"] is not None else None,
            outstanding_amount=float(r["outstanding"] or 0),
        ))
    return out


# ─── Open pipeline (point-in-time) ────────────────────────────────────

def _status_distribution(db: Session) -> list[StatusBucket]:
    row = db.execute(text("""
        SELECT
            COUNT(*) FILTER (
                WHERE h.current_stage = 'PRE_AUTH' AND h.status = 'SUBMITTED'
            ) AS pre_auth_submitted,
            COUNT(*) FILTER (
                WHERE h.current_stage = 'PRE_AUTH'
                  AND h.approved_amount IS NOT NULL AND h.approved_amount > 0
                  AND NOT EXISTS (SELECT 1 FROM claims WHERE claim_case_id = h.id)
            ) AS pre_auth_approved,
            COUNT(*) FILTER (
                WHERE h.current_stage = 'CLAIM' AND h.status = 'CLAIM_SUBMITTED'
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
         WHERE h.status <> 'CANCELLED'
    """)).mappings().first()

    return [
        StatusBucket(key="pre_auth_submitted", label="Pre-Auth Submitted",   count=row["pre_auth_submitted"] or 0),
        StatusBucket(key="pre_auth_approved",  label="Ready to Claim",       count=row["pre_auth_approved"] or 0),
        StatusBucket(key="claim_submitted",    label="Claim Submitted",      count=row["claim_submitted"] or 0),
        StatusBucket(key="claim_approved",     label="Ready to Invoice",     count=row["claim_approved_no_invoice"] or 0),
        StatusBucket(key="invoice_open",       label="Invoice Outstanding",  count=row["invoice_open"] or 0),
    ]


# ─── Volume trend ─────────────────────────────────────────────────────

def _volume_trend(db: Session, params: dict) -> list[VolumePoint]:
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
             WHERE sh.status IN ('SUBMITTED', 'CLAIM_SUBMITTED')
               AND sh.created_at >= :since
               AND sh.created_at <  :until
             GROUP BY 1
        ),
        settled AS (
            SELECT date_trunc('week', i.updated_at)::date AS week_start,
                   COUNT(*) AS n
              FROM invoice i
             WHERE i.status = 'PAID'
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


# ─── Recent activity (cross-hospital) ─────────────────────────────────

def _recent_activity(db: Session, params: dict, limit: int = 20) -> list[ActivityItem]:
    rows = db.execute(text("""
        SELECT sh.id, sh.stage, sh.status, sh.approved_amount, sh.created_at, sh.remarks,
               h.id AS claim_case_id, h.uhid,
               hsp.name AS hospital_name,
               pp.name AS provider_name,
               (SELECT pp2.patient_name
                  FROM pre_auth pa
                  JOIN pre_auth_patient pp2 ON pp2.form_data_id = pa.id
                 WHERE pa.claim_case_id = h.id AND pa.stage <> 'CLAIM'
                 ORDER BY pa.created_at DESC
                 LIMIT 1) AS patient_name
          FROM status_history sh
          JOIN hospitalization h ON h.id = sh.claim_case_id
          LEFT JOIN hospitals hsp ON hsp.id = h.hospital_id
          LEFT JOIN policy_provider_configs pp ON pp.id = h.policy_provider_id
         WHERE sh.created_at >= :since
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
            hospital_name=r["hospital_name"],
            stage=r["stage"],
            status=r["status"],
            amount=float(r["approved_amount"]) if r["approved_amount"] is not None else None,
            remarks=r["remarks"],
            created_at=r["created_at"],
        ) for r in rows
    ]
