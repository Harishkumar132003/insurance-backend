-- One-shot data fix for `public.preauth_status_tracking` on `aiagent`.
--
-- Goal:
--   Rewrite `turn_around_time` so any day component is folded into total hours.
--   Example: `2 days 00:20:02` becomes `48:20:02`.
--
-- Scope:
--   Updates ONLY `public.preauth_status_tracking.turn_around_time`.
--   Does NOT update `turn_around_time_text` or any other column/table.
--
-- Usage:
--   psql "postgresql://admin:admin123@localhost:5432/aiagent" \
--     -v ON_ERROR_STOP=1 \
--     -f scripts/preauth_turnaround_hours_only.sql

BEGIN;

UPDATE public.preauth_status_tracking
SET turn_around_time = make_interval(secs => EXTRACT(EPOCH FROM turn_around_time))
WHERE turn_around_time IS NOT NULL
  AND EXTRACT(DAY FROM turn_around_time) <> 0;

COMMIT;
