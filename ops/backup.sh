#!/usr/bin/env bash
# Фаза 2.2, п.1–2: pg_dump бекап, окремо від основного сервера БД.
#
# Використовує стандартні libpq env vars (PGHOST, PGPORT, PGUSER, PGPASSWORD,
# PGDATABASE) — не app-специфічний DATABASE__DSN (той asyncpg-формату).
# BACKUP_DIR має вказувати на сховище, ФІЗИЧНО ВІДОКРЕМЛЕНЕ від сервера БД
# (інший диск/регіон/S3-сумісний бакет через rclone/s3fs) — локальний шлях
# тут лише для розробки/демонстрації.
#
# Usage: PGDATABASE=arbitrage BACKUP_DIR=/mnt/backups ./ops/backup.sh

set -euo pipefail

: "${PGDATABASE:?PGDATABASE is required}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
dump_file="${BACKUP_DIR}/${PGDATABASE}_${timestamp}.dump"

# --format=custom: компресія + сумісність з pg_restore (потрібно для
# вибіркового/пріоритетного відновлення, див. restore.sh).
pg_dump --format=custom --file="$dump_file" "$PGDATABASE"

size_bytes=$(stat -c%s "$dump_file" 2>/dev/null || stat -f%z "$dump_file")
echo "Backup written: $dump_file (${size_bytes} bytes)"

# Retention самих файлів бекапу (окремо від retention рядків у БД, Фаза 2.1).
find "$BACKUP_DIR" -maxdepth 1 -name "${PGDATABASE}_*.dump" -mtime "+${RETENTION_DAYS}" -print -delete
