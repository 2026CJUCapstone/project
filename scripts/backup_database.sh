#!/usr/bin/env sh
set -eu

umask 077

usage() {
  echo "Usage: PGSERVICE=name $0 --database NAME --output FILE" >&2
  exit 2
}

database=""
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --database) [ "$#" -ge 2 ] || usage; database=$2; shift 2 ;;
    --output) [ "$#" -ge 2 ] || usage; output=$2; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[ -n "$database" ] && [ -n "$output" ] || usage
case "$database" in
  *[!A-Za-z0-9_-]*) echo "--database must be a simple database name" >&2; exit 2 ;;
esac
if [ -z "${PGSERVICE:-}" ] && { [ -z "${PGHOST:-}" ] || [ -z "${PGUSER:-}" ]; }; then
  echo "Set PGSERVICE, or both PGHOST and PGUSER, explicitly" >&2
  exit 2
fi

output_dir=$(dirname -- "$output")
[ -d "$output_dir" ] || { echo "Output directory does not exist" >&2; exit 2; }
[ ! -L "$output" ] || { echo "Refusing symlink output" >&2; exit 2; }
[ ! -e "$output" ] || { echo "Refusing to overwrite existing backup" >&2; exit 2; }
[ ! -e "$output.sha256" ] || { echo "Refusing to overwrite existing checksum" >&2; exit 2; }

output_dir=$(CDPATH= cd -- "$output_dir" && pwd -P)
output_name=$(basename -- "$output")
case "$output_name" in ""|.|..|*'
'*) echo "Invalid output filename" >&2; exit 2 ;; esac
output="$output_dir/$output_name"
temp_dir=$(mktemp -d "$output_dir/.backup.XXXXXX")
partial="$temp_dir/backup.dump"
partial_checksum="$temp_dir/backup.dump.sha256"
published_backup=0
published_checksum=0
committed=0
cleanup() {
  if [ "$committed" -eq 0 ]; then
    if [ "$published_checksum" -eq 1 ] && [ -e "$output.sha256" ] && [ "$output.sha256" -ef "$partial_checksum" ]; then
      rm -f -- "$output.sha256"
    fi
    if [ "$published_backup" -eq 1 ] && [ -e "$output" ] && [ "$output" -ef "$partial" ]; then
      rm -f -- "$output"
    fi
  fi
  rm -f -- "$partial" "$partial_checksum"
  rmdir -- "$temp_dir" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

pg_dump --format=custom --file="$partial" --dbname="$database"
chmod 600 "$partial"
checksum=$(sha256sum < "$partial")
checksum=${checksum%% *}
printf '%s  %s\n' "$checksum" "$output_name" > "$partial_checksum"
ln -- "$partial" "$output" || { echo "Refusing to overwrite existing backup" >&2; exit 2; }
published_backup=1
ln -- "$partial_checksum" "$output.sha256" || { echo "Refusing to overwrite existing checksum" >&2; exit 2; }
published_checksum=1
committed=1
cleanup
trap - EXIT HUP INT TERM
echo "Backup created: $output"
echo "Checksum created: $output.sha256"
