"""Hospital-admin dashboard.

One endpoint, one DB round-trip per widget. Every query is a single-pass
aggregation pushed to Postgres — the controller assembles the typed response
without doing any per-row work in Python. This keeps the endpoint <100ms even
for tens of thousands of cases as long as the existing indexes are in place
(hospitalization.hospital_id, status_history.claim_case_id,
claim.claim_case_id, settlement_item.claim_case_id, pre_auth_patient.form_data_id).
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
        status_distribution=_status_distribution(db, params),
        volume_trend=_volume_trend(db, params),
        top_diagnoses=_top_diagnoses(db, params),
        adr_resolution_days=_adr_resolution_days(db, params),
        cancellation_reasons=_cancellation_reasons(db, params),
    )


# ─── KPI strip ────────────────────────────────────────────────────────

def _kpis(db: Session, params: dict) -> DashboardKPIs:
    """All four KPIs are scoped to the active date range — they only consider
    cases whose `hospitalization.created_at` lies in [since, until). The
    "cancelled" KPI instead dates the cancellation *event*, matching
    `_cancellation_reasons`, so the card and that panel always agree."""
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

    # Outstanding receivables — approved claim money the insurer has not settled
    # yet. This is a BALANCE, not a flow: "what we are owed right now", so it is
    # deliberately NOT limited to the selected date range. It used to filter on
    # h.created_at, which hid every older unpaid case — the money you chase
    # hardest — and made this card disagree with the identically-named
    # super-admin KPI, which was always a live snapshot.
    # Settlement remittance is the source of truth for what was actually paid;
    # the old invoice record was self-reported. Clamped at 0 so an
    # over-settlement on one case cannot mask a genuine shortfall on another.
    receivables = db.execute(text("""
        WITH per_case AS (
            SELECT h.id,
                   SUM(cl.approved_amount) AS approved,
                   COALESCE((
                       SELECT SUM(si.settled_amount)
                         FROM settlement_item si
                        WHERE si.claim_case_id = h.id
                   ), 0) AS settled
              FROM hospitalization h
              JOIN claims cl ON cl.claim_case_id = h.id
             WHERE h.hospital_id = :hospital_id
               AND h.case_status <> 'CANCELLED'
               AND cl.approved_amount IS NOT NULL AND cl.approved_amount > 0
             GROUP BY h.id
        )
        SELECT COUNT(*) AS case_count,
               COALESCE(SUM(approved - settled), 0) AS outstanding
          FROM per_case
         WHERE approved > settled
    """), {"hospital_id": params["hospital_id"]}).mappings().first()

    # Cancelled in period — dated by the cancellation event, not by when the
    # case was created, so an older case cancelled this week still counts.
    # `total` is the denominator for the share shown under the card and
    # deliberately includes cancelled cases.
    cancelled = db.execute(text("""
        SELECT
            (SELECT COUNT(DISTINCT sh.claim_case_id)
               FROM status_history sh
               JOIN hospitalization h ON h.id = sh.claim_case_id
              WHERE h.hospital_id = :hospital_id
                AND sh.status = 'CANCELLED'
                AND sh.created_at >= :since
                AND sh.created_at <  :until) AS cancelled,
            (SELECT COUNT(*)
               FROM hospitalization h
              WHERE h.hospital_id = :hospital_id
                AND h.created_at >= :since
                AND h.created_at <  :until) AS total
    """), params).mappings().first()

    return DashboardKPIs(
        action_needed_count=row["action_needed"] or 0,
        awaiting_insurer_count=row["awaiting_count"] or 0,
        awaiting_insurer_avg_wait_seconds=(
            float(row["awaiting_avg_seconds"]) if row["awaiting_avg_seconds"] is not None else None
        ),
        outstanding_receivables_amount=float(receivables["outstanding"] or 0),
        outstanding_receivables_count=receivables["case_count"] or 0,
        cancelled_count=cancelled["cancelled"] or 0,
        total_cases_in_period=cancelled["total"] or 0,
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
            -- Latest PRE_AUTH form per case, summed. DISTINCT ON is what makes
            -- that true: the plain join added every PRE_AUTH form a case had,
            -- so a second one would silently inflate the requested total.
            SELECT COUNT(*) AS cnt, COALESCE(SUM(total_cost), 0) AS amt
              FROM (
                SELECT DISTINCT ON (pa.claim_case_id)
                       pa.claim_case_id, s.total_cost
                  FROM cases c
                  JOIN pre_auth pa ON pa.claim_case_id = c.id AND pa.stage = 'PRE_AUTH'
                  JOIN pre_auth_stay s ON s.form_data_id = pa.id
                 ORDER BY pa.claim_case_id, pa.created_at DESC, pa.id DESC
              ) latest_form
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
        settled AS (
            -- Real money received, from the insurer's remittance advice.
            SELECT COUNT(DISTINCT si.claim_case_id) AS cnt,
                   COALESCE(SUM(si.settled_amount), 0) AS amt
              FROM cases c
              JOIN settlement_item si ON si.claim_case_id = c.id
        )
        SELECT requested.cnt       AS req_c, requested.amt       AS req_a,
               approved.cnt        AS app_c, approved.amt        AS app_a,
               claimed.cnt         AS cla_c, claimed.amt         AS cla_a,
               claim_approved.cnt  AS cap_c, claim_approved.amt  AS cap_a,
               settled.cnt         AS set_c, settled.amt         AS set_a
          FROM requested, approved, claimed, claim_approved, settled
    """), params).mappings().first()

    # "Invoiced" is gone: it was never a stage in the insurer's world, only an
    # internal record the hospital typed in after the fact.
    steps = [
        ("requested", "Requested", row["req_a"], row["req_c"]),
        ("approved", "Pre-Auth Approved", row["app_a"], row["app_c"]),
        ("claimed", "Claim Raised", row["cla_a"], row["cla_c"]),
        ("claim_approved", "Claim Approved", row["cap_a"], row["cap_c"]),
        ("settled", "Settled", row["set_a"], row["set_c"]),
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
        latest_decision AS (
            -- One row per case: its most recent approve/deny outcome. Counting
            -- raw status_history rows instead made `approved` count decision
            -- EVENTS -- a case decided at pre-auth, enhancement and claim
            -- contributed 3 -- so `approved` could exceed `cases` and sat
            -- nonsensically beside it.
            SELECT DISTINCT ON (sh.claim_case_id)
                   c.policy_provider_id, sh.claim_case_id, sh.status
              FROM cases c
              JOIN status_history sh ON sh.claim_case_id = c.id
             WHERE sh.status = ANY(:approved_statuses)
                OR sh.status = ANY(:denied_statuses)
             ORDER BY sh.claim_case_id, sh.created_at DESC
        ),
        decisions AS (
            SELECT policy_provider_id,
                   COUNT(*) FILTER (WHERE status = ANY(:approved_statuses)) AS approved,
                   COUNT(*) FILTER (WHERE status = ANY(:denied_statuses))   AS denied
              FROM latest_decision
             GROUP BY policy_provider_id
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
            -- Approved claim money this provider has not settled yet. Same
            -- definition as the receivables KPI, grouped by provider.
            SELECT policy_provider_id, COALESCE(SUM(approved - settled), 0) AS amt
              FROM (
                SELECT h.policy_provider_id, h.id,
                       SUM(cl.approved_amount) AS approved,
                       COALESCE((
                           SELECT SUM(si.settled_amount)
                             FROM settlement_item si
                            WHERE si.claim_case_id = h.id
                       ), 0) AS settled
                  FROM hospitalization h
                  JOIN claims cl ON cl.claim_case_id = h.id
                 WHERE h.hospital_id = :hospital_id
                   AND h.created_at >= :since
                   AND h.created_at <  :until
                   AND h.case_status <> 'CANCELLED'
                   AND cl.approved_amount IS NOT NULL AND cl.approved_amount > 0
                 GROUP BY h.policy_provider_id, h.id
              ) per_case
             WHERE approved > settled
             GROUP BY policy_provider_id
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

def _status_distribution(db: Session, params: dict) -> list[StatusBucket]:
    """Five buckets covering the open pipeline, scoped to the active date range.

    Each case lands in AT MOST ONE bucket. The old version used five
    independent COUNT(*) FILTER predicates, which double-counted any case that
    satisfied two of them (e.g. still SUBMITTED but already carrying an
    approved amount), so the buckets did not sum to the case count.

    A single CASE assigns one bucket per case, in this precedence:
    anything awaiting an insurer decision is reported as awaiting, because
    that is the state the hospital acts on; only then do we fall through to
    "approved, nothing sent yet". DRAFT cases are deliberately excluded --
    nothing has been submitted, so they are not in the pipeline yet.
    """
    row = db.execute(text("""
        WITH bucketed AS (
            SELECT CASE
                WHEN h.current_stage = 'CLAIM' AND h.case_status = 'CLAIM_SUBMITTED'
                    THEN 'claim_submitted'
                WHEN EXISTS (SELECT 1 FROM settlement_item si WHERE si.claim_case_id = h.id)
                     AND (SELECT COALESCE(SUM(si.settled_amount), 0) FROM settlement_item si
                           WHERE si.claim_case_id = h.id)
                         < (SELECT COALESCE(SUM(c.approved_amount), 0) FROM claims c
                             WHERE c.claim_case_id = h.id)
                    THEN 'partially_settled'
                WHEN EXISTS (SELECT 1 FROM claims c WHERE c.claim_case_id = h.id
                               AND c.approved_amount IS NOT NULL AND c.approved_amount > 0)
                     AND NOT EXISTS (SELECT 1 FROM settlement_item WHERE claim_case_id = h.id)
                    THEN 'awaiting_settlement'
                WHEN h.current_stage = 'PRE_AUTH'
                     AND h.case_status = ANY(:awaiting_statuses)
                    THEN 'pre_auth_submitted'
                WHEN h.current_stage = 'PRE_AUTH'
                     AND h.approved_amount IS NOT NULL AND h.approved_amount > 0
                     AND NOT EXISTS (SELECT 1 FROM claims WHERE claim_case_id = h.id)
                    THEN 'pre_auth_approved'
                ELSE NULL
            END AS bucket
              FROM hospitalization h
             WHERE h.hospital_id = :hospital_id
               AND h.case_status <> 'CANCELLED'
               AND h.created_at >= :since
               AND h.created_at <  :until
        )
        SELECT
            COUNT(*) FILTER (WHERE bucket = 'pre_auth_submitted')  AS pre_auth_submitted,
            COUNT(*) FILTER (WHERE bucket = 'pre_auth_approved')   AS pre_auth_approved,
            COUNT(*) FILTER (WHERE bucket = 'claim_submitted')     AS claim_submitted,
            COUNT(*) FILTER (WHERE bucket = 'awaiting_settlement') AS awaiting_settlement,
            COUNT(*) FILTER (WHERE bucket = 'partially_settled')   AS partially_settled
          FROM bucketed
    """), {
        **params,
        "awaiting_statuses": list(AWAITING_INSURER_STATUSES),
    }).mappings().first()

    return [
        StatusBucket(key="pre_auth_submitted", label="Pre-Auth Submitted",   count=row["pre_auth_submitted"] or 0),
        StatusBucket(key="pre_auth_approved",  label="Ready to Claim",       count=row["pre_auth_approved"] or 0),
        StatusBucket(key="claim_submitted",    label="Claim Submitted",      count=row["claim_submitted"] or 0),
        StatusBucket(key="awaiting_settlement", label="Awaiting Settlement", count=row["awaiting_settlement"] or 0),
        StatusBucket(key="partially_settled",   label="Partially Settled",   count=row["partially_settled"] or 0),
    ]


# ─── Volume trend ─────────────────────────────────────────────────────

def _volume_trend(db: Session, params: dict) -> list[VolumePoint]:
    """Claims Submitted vs Settled per ISO week. The bucket series is generated
    inside the picked [since, until) range, so the chart always matches the
    selector.

    Tracks CLAIM submissions only. It used to also count pre-auth submissions,
    which meant one case contributed twice over its life (once at pre-auth,
    again when the claim was raised) and the bar could not be read as a claim
    count.

    The filter is on `stage`, not on a 'CLAIM_SUBMITTED' status: no such status
    is ever written to status_history. A claim submission is stage='CLAIM' with
    status='SUBMITTED' -- the old `status IN ('SUBMITTED','CLAIM_SUBMITTED')`
    matched claim rows only through the generic 'SUBMITTED' arm, and the
    'CLAIM_SUBMITTED' literal was dead. CLAIM_ADR_SUBMITTED is excluded: it is a
    document response inside the claim stage, not a claim being raised.
    """
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
               AND h.case_status <> 'CANCELLED'   -- every other panel excludes these
               AND sh.stage = 'CLAIM'
               AND sh.status = 'SUBMITTED'
               AND sh.created_at >= :since
               AND sh.created_at <  :until
             GROUP BY 1
        ),
        settled AS (
            -- Cases settled in week, by the date the INSURER paid (the batch's
            -- settlement_date), not when someone uploaded the remittance file.
            -- settlement_date lives on the batch: settlement_item does not carry
            -- it on every deployed schema, so always reach it through the join.
            SELECT date_trunc('week', sb.settlement_date)::date AS week_start,
                   COUNT(DISTINCT si.claim_case_id) AS n
              FROM settlement_item si
              JOIN settlement_batch sb ON sb.id = si.batch_id
              JOIN hospitalization h ON h.id = si.claim_case_id
             WHERE h.hospital_id = :hospital_id
               AND sb.settlement_date IS NOT NULL
               AND sb.settlement_date >= :since
               AND sb.settlement_date <  :until
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

def _adr_resolution_days(db: Session, params: dict) -> float | None:
    """Average ADR turnaround for queries RAISED inside the active range.

    Previously unscoped, so the figure shown beside a 30-day header could be
    an all-time average drawn entirely from outside the window.
    """
    row = db.execute(text("""
        SELECT AVG(EXTRACT(EPOCH FROM (q.resolved_at - q.created_at)) / 86400.0) AS avg_days
          FROM query_logs q
          JOIN hospitalization h ON h.id = q.claim_case_id
         WHERE h.hospital_id = :hospital_id
           AND q.query_type = 'ADR_NMI'
           AND q.resolved_at IS NOT NULL
           AND q.created_at >= :since
           AND q.created_at <  :until
    """), params).mappings().first()
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
