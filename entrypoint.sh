#!/bin/sh
set -e

echo "Waiting for PostgreSQL at $DB_HOST:$DB_PORT..."
while ! nc -z "$DB_HOST" "$DB_PORT" 2>/dev/null; do
    sleep 0.5
done
echo "PostgreSQL ready."

# Migrations et collectstatic uniquement pour le service web (pas Celery)
if [ "$1" = "gunicorn" ] || echo "$1" | grep -q "runserver"; then
    echo "Running migrations..."
    python manage.py migrate --noinput

    echo "Collecting static files..."
    python manage.py collectstatic --noinput
fi

exec "$@"
