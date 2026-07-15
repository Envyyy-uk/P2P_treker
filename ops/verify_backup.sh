#!/usr/bin/env bash
# Фаза 2.2, п.4: тестове відновлення бекапу на ОКРЕМІЙ БД + перевірка вмісту
# (кількість рядків по таблицях), а не тільки що файл бекапу існує.
#
# Usage: ./ops/verify_backup.sh <dump_file>
#
# Запускати періодично (напр. щотижня через cron) на середовищі, окремому
# від production — див. docs/phase-2.2/README.md.

set -euo pipefail

dump_file="${1:?usage: verify_backup.sh <dump_file>}"
[ -f "$dump_file" ] || { echo "Dump file not found: $dump_file" >&2; exit 1; }

verify_db="${VERIFY_DB:-arbitrage_restore_verify}"

cleanup() {
    dropdb --if-exists "$verify_db" 2>/dev/null || true
}
trap cleanup EXIT

echo "Restoring '$dump_file' into scratch database '$verify_db'..."
dropdb --if-exists "$verify_db"
createdb "$verify_db"
pg_restore --no-owner --dbname="$verify_db" "$dump_file"

echo
echo "Schema check:"
psql -d "$verify_db" -c "\dt"

echo
echo "Row counts:"
status=0
for table in quotes_1s spread_events quotes_10s quotes_1m quotes_5m; do
    count=$(psql -d "$verify_db" -tAc "SELECT count(*) FROM ${table}" 2>/dev/null) || {
        echo "  ${table}: MISSING (restore verification FAILED)"
        status=1
        continue
    }
    echo "  ${table}: ${count}"
done

if [ "$status" -ne 0 ]; then
    echo
    echo "Verification FAILED: one or more expected tables are missing after restore." >&2
    exit 1
fi

echo
echo "Verification OK: backup restores cleanly into '$verify_db' with all expected tables."
