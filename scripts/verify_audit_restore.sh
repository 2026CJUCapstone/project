#!/bin/sh
# Run only inside the isolated audit PostgreSQL container, never production.
set -eu
test "${POSTGRES_DB:-}" = audit_stage
test "${POSTGRES_USER:-}" = audit_test
export PGHOST=/var/run/postgresql PGUSER=audit_test
target=audit_restore_t82h_verification
root=$(mktemp -d /tmp/audit-restore-XXXXXX)
createdb "$target"  # Refuses an existing target; never drops or cleans one.
sh /tmp/audit-backup.sh --database audit_stage --output "$root/stage.dump"
sh /tmp/audit-restore.sh --database "$target" --backup "$root/stage.dump"
for table in users problems submissions user_problem_scores contests contest_problems contest_participants contest_submissions code_projects execution_jobs; do
  query="SELECT md5(coalesce(jsonb_agg(to_jsonb(t) ORDER BY id)::text, '[]')) FROM $table t"
  original=$(psql -XAt -v ON_ERROR_STOP=1 -d audit_stage -c "$query")
  restored=$(psql -XAt -v ON_ERROR_STOP=1 -d "$target" -c "$query")
  test "$original" = "$restored"
done
if sh /tmp/audit-restore.sh --database "$target" --backup "$root/stage.dump"; then
  echo 'ERROR: restore accepted non-empty target' >&2
  exit 1
fi
echo 'PASS: isolated PostgreSQL restore, 10 table content digests, and non-empty target refusal'
echo "Retained test-only restore DB: $target; artifacts: $root"
