#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    printf 'Usage: %s <backup.dump>\n' "$0" >&2
    exit 2
fi

project_dir="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
backup_file="$1"

if [ ! -f "$backup_file" ]; then
    printf 'Backup file not found: %s\n' "$backup_file" >&2
    exit 2
fi

cd "$project_dir"
docker compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$backup_file"

printf 'Restore completed from %s\n' "$backup_file"
