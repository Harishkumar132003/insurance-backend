#!/usr/bin/env bash
# Dump a normalised schema fingerprint. Run on BOTH machines, then diff.
# Usage: ./schema_fingerprint.sh <container> <db_user> [db_name]
set -euo pipefail
CTR="${1:?container name, e.g. local-postgres or oasys-postgres}"
USR="${2:?db user}"
DB="${3:-oasys}"

echo "### alembic_version"
docker exec "$CTR" psql -U "$USR" -d "$DB" -t -A \
  -c "SELECT version_num FROM alembic_version ORDER BY 1;"

echo "### columns"
docker exec "$CTR" psql -U "$USR" -d "$DB" -t -A -F'|' -c "
SELECT table_name, column_name, data_type,
       coalesce(character_maximum_length::text, numeric_precision||','||numeric_scale, ''),
       is_nullable
  FROM information_schema.columns
 WHERE table_schema='public'
 ORDER BY table_name, column_name;"

echo "### indexes"
docker exec "$CTR" psql -U "$USR" -d "$DB" -t -A -c "
SELECT tablename||' :: '||indexdef FROM pg_indexes
 WHERE schemaname='public' ORDER BY 1;"

echo "### fkeys"
docker exec "$CTR" psql -U "$USR" -d "$DB" -t -A -c "
SELECT conrelid::regclass||' :: '||conname||' :: '||pg_get_constraintdef(oid)
  FROM pg_constraint WHERE contype='f'
   AND connamespace='public'::regnamespace ORDER BY 1;"
