#!/usr/bin/env bash
# Sauvegarde PostgreSQL VÉRIFIÉE. À lancer depuis cron sur le VPS (voir DEPLOY.md, étape 8.3).
#
# Contrairement à un simple « pg_dump | gzip > fichier », ce script échoue (code de sortie ≠ 0)
# si le conteneur est introuvable, si le dump est vide, tronqué ou corrompu : une sauvegarde
# vide ne passe jamais pour une sauvegarde réussie.
#
# Variables (toutes facultatives) :
#   DB_CONTAINER         nom du conteneur PostgreSQL (détecté automatiquement sinon)
#   DB_USER, DB_NAME     par défaut palmares_user / palmares_db
#   BACKUP_DIR           par défaut /root/backups/palmares
#   KEEP                 nombre de sauvegardes conservées (30)
#   BACKUP_RSYNC_TARGET  copie hors du serveur, ex. utilisateur@autre-machine:/sauvegardes/palmares/
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/root/backups/palmares}"
DB_USER="${DB_USER:-palmares_user}"
DB_NAME="${DB_NAME:-palmares_db}"
KEEP="${KEEP:-30}"
DB_CONTAINER="${DB_CONTAINER:-$(docker ps --filter "ancestor=postgres:16-alpine" --format '{{.Names}}' | grep -i 'db' | head -1 || true)}"

if [ -z "$DB_CONTAINER" ]; then
    echo "ERREUR : conteneur PostgreSQL introuvable (définissez DB_CONTAINER)." >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d_%H%M%S)"
partial="$BACKUP_DIR/.palmares_${stamp}.sql.gz.part"
final="$BACKUP_DIR/palmares_${stamp}.sql.gz"
trap 'rm -f "$partial"' EXIT

docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" --no-owner "$DB_NAME" | gzip > "$partial"

gzip -t "$partial" || { echo "ERREUR : archive corrompue." >&2; exit 1; }
size="$(stat -c %s "$partial")"
if [ "$size" -lt 2048 ]; then
    echo "ERREUR : sauvegarde suspecte ($size octets)." >&2
    exit 1
fi
if ! gunzip -c "$partial" | tail -n 5 | grep -q "PostgreSQL database dump complete"; then
    echo "ERREUR : le dump est incomplet (marqueur de fin absent)." >&2
    exit 1
fi

mv "$partial" "$final"

# Rotation : on garde les KEEP plus récentes
ls -1t "$BACKUP_DIR"/palmares_*.sql.gz | tail -n +"$((KEEP + 1))" | xargs -r rm --

# Copie hors serveur (facultatif) : protège contre la perte du VPS lui-même
if [ -n "${BACKUP_RSYNC_TARGET:-}" ]; then
    rsync -a "$final" "$BACKUP_RSYNC_TARGET"
fi

echo "OK : $final ($size octets)"
