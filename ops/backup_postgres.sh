#!/usr/bin/env sh
set -eu

project_dir="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
backup_dir="${BACKUP_DIR:-$project_dir/backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${1:-$backup_dir/resto_postgres_$timestamp.dump}"

mkdir -p "$(dirname -- "$backup_file")"

cd "$project_dir"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_file"

printf 'Backup written to %s\n' "$backup_file"
