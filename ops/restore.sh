#!/usr/bin/env bash
# Фаза 2.2, п.5: відновлення з бекапу. spread_events має вищий пріоритет
# відновлення, ніж сирі quotes_1s / downsample-таблиці — з --priority
# спочатку відновлюється схема + spread_events (доступні для запитів
# найшвидше), і лише потім решта даних.
#
# Usage:
#   ./ops/restore.sh <dump_file> [target_db] [--priority]
#
# Стандартні libpq env vars (PGHOST/PGPORT/PGUSER/PGPASSWORD) визначають
# сервер; target_db (аргумент або $PGDATABASE) — куди відновлювати.

set -euo pipefail

dump_file="${1:?usage: restore.sh <dump_file> [target_db] [--priority]}"
shift
target_db="${PGDATABASE:-}"
priority=false

for arg in "$@"; do
    case "$arg" in
        --priority) priority=true ;;
        *) target_db="$arg" ;;
    esac
done

: "${target_db:?target_db required (arg or PGDATABASE env var)}"
[ -f "$dump_file" ] || { echo "Dump file not found: $dump_file" >&2; exit 1; }

if $priority; then
    echo "Priority restore into '$target_db': schema -> spread_events -> решта"
    pg_restore --clean --if-exists --no-owner --schema-only --dbname="$target_db" "$dump_file"
    pg_restore --no-owner --data-only --dbname="$target_db" -t spread_events "$dump_file"
    echo "spread_events restored and queryable; restoring remaining tables..."
    # pg_restore has no --exclude-table-data; filter the TOC list instead
    # (standard approach) to restore all data-section entries except the
    # one we already loaded above.
    toc_file="$(mktemp)"
    trap 'rm -f "$toc_file"' EXIT
    pg_restore -l "$dump_file" | grep -v "TABLE DATA public spread_events " > "$toc_file"
    pg_restore --no-owner --data-only --dbname="$target_db" --use-list="$toc_file" "$dump_file"
else
    echo "Full restore into '$target_db'"
    pg_restore --clean --if-exists --no-owner --dbname="$target_db" "$dump_file"
fi

echo "Restore complete: $dump_file -> $target_db"
