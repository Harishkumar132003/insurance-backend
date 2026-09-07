#!/usr/bin/env bash
# Verify THIS release's schema changes are present. Exit 1 on any mismatch.
# Usage: ./check_changes.sh <container> <db_user> [db_name]
set -uo pipefail
CTR="${1:?container}"; USR="${2:?db user}"; DB="${3:-oasys}"
q() { docker exec "$CTR" psql -U "$USR" -d "$DB" -t -A -c "$1"; }
fail=0
chk() { # label expected actual
  if [ "$2" = "$3" ]; then printf '  OK   %-42s %s\n' "$1" "$3"
  else printf '  FAIL %-42s expected=%s got=%s\n' "$1" "$2" "$3"; fail=1; fi
}

echo "== alembic head =="
chk "alembic_version" "f4a8c1e7b309" "$(q "SELECT version_num FROM alembic_version;")"

echo "== new columns =="
for spec in "pre_auth_stay:cost_items:jsonb" \
            "pre_auth_stay:room_rent_total:numeric" \
            "pre_auth_stay:icu_charges_total:numeric" \
            "part_d_letters:bd_items:jsonb"; do
  t=${spec%%:*}; rest=${spec#*:}; c=${rest%%:*}; want=${rest#*:}
  got=$(q "SELECT data_type FROM information_schema.columns
            WHERE table_schema='public' AND table_name='$t' AND column_name='$c';")
  chk "$t.$c" "$want" "${got:-MISSING}"
done

echo "== JSONB shape (data, not DDL) =="
tot=$(q "SELECT count(*) FROM hospital_provider_mappings;")
wdx=$(q "SELECT count(*) FROM hospital_provider_mappings WHERE room_charges ? 'diagnoses';")
printf '  INFO %-42s %s of %s MOU rows carry the diagnoses key\n' "room_charges.diagnoses" "$wdx" "$tot"
echo "       (0 is fine on a fresh server - it is written on the next MOU save)"

echo
[ $fail -eq 0 ] && echo "RESULT: schema matches this release" || echo "RESULT: MISMATCH - see FAIL lines above"
exit $fail
