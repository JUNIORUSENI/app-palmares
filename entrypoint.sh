#!/bin/sh
set -e

# Fixer les permissions des volumes Docker (créés par root)
chown -R appuser:appgroup /app/media /app/logs /app/staticfiles 2>/dev/null || true

echo "Waiting for PostgreSQL at $DB_HOST:$DB_PORT..."
while ! nc -z "$DB_HOST" "$DB_PORT" 2>/dev/null; do
    sleep 0.5
done
echo "PostgreSQL ready."

# Migrations et collectstatic uniquement pour le service web (pas Celery)
if [ "$1" = "gunicorn" ] || echo "$1" | grep -q "runserver"; then
    echo "Running migrations..."
    if ! gosu appuser python manage.py migrate --noinput; then
        echo "ERROR: Migrations failed! Aborting startup."
        exit 1
    fi

    echo "Collecting static files..."
    gosu appuser python manage.py collectstatic --noinput
fi

# Basculer sur appuser pour exécuter la commande principale
exec gosu appuser "$@"
