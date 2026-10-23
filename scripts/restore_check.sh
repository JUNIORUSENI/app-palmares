#!/usr/bin/env bash
# Teste la DERNIÈRE sauvegarde en la restaurant dans une base temporaire, puis la supprime.
# Une sauvegarde qu'on n'a jamais restaurée n'est pas une sauvegarde : à lancer après la mise en
# place du cron puis régulièrement (par exemple une fois par mois).
# La base de production n'est jamais modifiée. Mêmes variables que backup_db.sh.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/root/backups/palmares}"
DB_USER="${DB_USER:-palmares_user}"
DB_CONTAINER="${DB_CONTAINER:-$(docker ps --filter "ancestor=postgres:16-alpine" --format '{{.Names}}' | grep -i 'db' | head -1 || true)}"
TMP_DB="restore_check"

if [ -z "$DB_CONTAINER" ]; then
    echo "ERREUR : conteneur PostgreSQL introuvable (définissez DB_CONTAINER)." >&2
    exit 1
fi

latest="$(ls -1t "$BACKUP_DIR"/palmares_*.sql.gz 2>/dev/null | head -1 || true)"
if [ -z "$latest" ]; then
    echo "ERREUR : aucune sauvegarde dans $BACKUP_DIR." >&2
    exit 1
fi
echo "Sauvegarde testée : $latest ($(date -r "$latest" '+%d/%m/%Y %H:%M'))"

psql_tmp() { docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$TMP_DB" -v ON_ERROR_STOP=1 -tA "$@"; }
cleanup() { docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -q -c "DROP DATABASE IF EXISTS $TMP_DB" >/dev/null; }
trap cleanup EXIT

docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -q -c "DROP DATABASE IF EXISTS $TMP_DB" -c "CREATE DATABASE $TMP_DB" >/dev/null
gunzip -c "$latest" | docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$TMP_DB" -v ON_ERROR_STOP=1 -q >/dev/null

students="$(psql_tmp -c 'SELECT count(*) FROM academics_student')"
grades="$(psql_tmp -c 'SELECT count(*) FROM academics_graderecord')"
users="$(psql_tmp -c 'SELECT count(*) FROM accounts_user')"
echo "Restauration réussie : $students élèves, $grades résultats, $users utilisateurs."
if [ "$users" -eq 0 ]; then
    echo "ATTENTION : aucun utilisateur dans la sauvegarde." >&2
    exit 1
fi
