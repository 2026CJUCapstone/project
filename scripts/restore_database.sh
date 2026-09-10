#!/usr/bin/env sh
set -eu

umask 077

usage() {
  echo "Usage: PGSERVICE=name $0 --database EMPTY_DATABASE --backup FILE" >&2
  exit 2
}

database=""
backup=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --database) [ "$#" -ge 2 ] || usage; database=$2; shift 2 ;;
    --backup) [ "$#" -ge 2 ] || usage; backup=$2; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[ -n "$database" ] && [ -n "$backup" ] || usage
case "$database" in
  *[!A-Za-z0-9_-]*) echo "--database must be a simple database name" >&2; exit 2 ;;
esac
if [ -z "${PGSERVICE:-}" ] && { [ -z "${PGHOST:-}" ] || [ -z "${PGUSER:-}" ]; }; then
  echo "Set PGSERVICE, or both PGHOST and PGUSER, explicitly" >&2
  exit 2
fi

[ -f "$backup" ] && [ ! -L "$backup" ] || { echo "Backup must be a regular, non-symlink file" >&2; exit 2; }
backup_dir=$(dirname -- "$backup")
backup_dir=$(CDPATH= cd -- "$backup_dir" && pwd -P)
backup_name=$(basename -- "$backup")
case "$backup_name" in ""|.|..|*'
'*) echo "Invalid backup filename" >&2; exit 2 ;; esac
backup="$backup_dir/$backup_name"
[ -f "$backup.sha256" ] && [ ! -L "$backup.sha256" ] || { echo "Missing regular checksum file: $backup.sha256" >&2; exit 2; }
expected_checksum=""
ignored_checksum_text=""
IFS=' ' read -r expected_checksum ignored_checksum_text < "$backup.sha256" || true
case "$expected_checksum" in
  *[!0-9a-fA-F]*|'') echo "Invalid checksum file" >&2; exit 2 ;;
esac
[ "${#expected_checksum}" -eq 64 ] || { echo "Invalid checksum file" >&2; exit 2; }
# Hash stdin so GNU checksum filename escaping (e.g. a carriage return in a
# parent directory) cannot prefix the digest with a backslash.
actual_checksum=$(sha256sum < "$backup")
actual_checksum=${actual_checksum%% *}
[ "$actual_checksum" = "$expected_checksum" ] || {
  echo "Backup checksum verification failed" >&2
  exit 1
}

object_count=$(psql --dbname="$database" --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
  --command="SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_toast';")
case "$object_count" in
  ''|*[!0-9]*) echo "Could not verify that the target database is empty" >&2; exit 1 ;;
  0) ;;
  *) echo "Refusing to restore into a non-empty database" >&2; exit 1 ;;
esac

pg_restore --exit-on-error --single-transaction --dbname="$database" "$backup"
echo "Restore completed into explicitly selected database: $database"
