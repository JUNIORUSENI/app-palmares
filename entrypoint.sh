#!/bin/sh

echo "Waiting for PostgreSQL..."
while ! nc -z $DB_HOST $DB_PORT 2>/dev/null; do
    sleep 0.1
done
echo "PostgreSQL ready."

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
