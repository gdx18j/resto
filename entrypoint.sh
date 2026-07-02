#!/bin/bash

set -e

echo "Waiting for PostgreSQL..."

if [ "${DJANGO_ENV:-development}" = "production" ]; then
    : "${DJANGO_SECRET_KEY:?DJANGO_SECRET_KEY is required}"
    : "${DJANGO_DEBUG:?DJANGO_DEBUG is required}"
    : "${DJANGO_ALLOWED_HOSTS:?DJANGO_ALLOWED_HOSTS is required}"
    : "${DB_HOST:?DB_HOST is required}"
    : "${DB_PORT:?DB_PORT is required}"
    : "${DB_USER:?DB_USER is required}"
    : "${DB_NAME:?DB_NAME is required}"
    : "${DB_PASSWORD:?DB_PASSWORD is required}"
fi

DB_HOST=${DB_HOST:-db}
DB_PORT=${DB_PORT:-5432}
DB_USER=${DB_USER:-resto_user}
DB_NAME=${DB_NAME:-resto_db}

MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    RETRY_COUNT=$((RETRY_COUNT + 1))

    if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" 2>/dev/null; then
        echo "PostgreSQL is ready."
        break
    fi

    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        echo "Could not connect to PostgreSQL after $MAX_RETRIES attempts."
        echo "Host: $DB_HOST:$DB_PORT"
        echo "Database: $DB_NAME"
        echo "User: $DB_USER"
        exit 1
    fi

    echo "Connection attempt $RETRY_COUNT/$MAX_RETRIES..."
    sleep 1
done

echo "Applying database migrations..."
python manage.py migrate --noinput

if [ "${IMPORT_SEED_DATA_ON_STARTUP:-False}" = "True" ]; then
    echo "Importing project seed data..."
    python manage.py seed_project_data
fi

if [ "${IMPORT_SEED_IMAGES_ON_STARTUP:-False}" = "True" ]; then
    echo "Importing seed menu images..."
    python manage.py import_caesar_images
fi

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Starting Django..."
exec "$@"
