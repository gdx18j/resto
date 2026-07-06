#!/bin/sh

set -eu

is_true() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|on|ON) return 0 ;;
        *) return 1 ;;
    esac
}

if [ "${DJANGO_ENV:-development}" = "production" ]; then
    : "${DJANGO_SECRET_KEY:?DJANGO_SECRET_KEY is required}"
    : "${TABLE_QR_TOKEN_ENCRYPTION_KEY:?TABLE_QR_TOKEN_ENCRYPTION_KEY is required}"
    : "${DJANGO_DEBUG:?DJANGO_DEBUG is required}"
    : "${DJANGO_ALLOWED_HOSTS:?DJANGO_ALLOWED_HOSTS is required}"
    : "${DB_HOST:?DB_HOST is required}"
    : "${DB_PORT:?DB_PORT is required}"
    : "${DB_USER:?DB_USER is required}"
    : "${DB_NAME:?DB_NAME is required}"
    : "${DB_PASSWORD:?DB_PASSWORD is required}"
fi

if is_true "${WAIT_FOR_DATABASE:-True}"; then
    DB_HOST=${DB_HOST:-db}
    DB_PORT=${DB_PORT:-5432}
    DB_USER=${DB_USER:-resto_user}
    DB_NAME=${DB_NAME:-resto_db}
    MAX_RETRIES=${DATABASE_WAIT_MAX_RETRIES:-30}
    RETRY_DELAY=${DATABASE_WAIT_RETRY_SECONDS:-1}
    RETRY_COUNT=0

    echo "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."

    while [ "$RETRY_COUNT" -lt "$MAX_RETRIES" ]; do
        RETRY_COUNT=$((RETRY_COUNT + 1))

        if pg_isready \
            -h "$DB_HOST" \
            -p "$DB_PORT" \
            -U "$DB_USER" \
            -d "$DB_NAME" \
            >/dev/null 2>&1; then
            echo "PostgreSQL is ready."
            break
        fi

        if [ "$RETRY_COUNT" -ge "$MAX_RETRIES" ]; then
            echo "Could not connect to PostgreSQL after ${MAX_RETRIES} attempts." >&2
            echo "Host: ${DB_HOST}:${DB_PORT}" >&2
            echo "Database: ${DB_NAME}" >&2
            echo "User: ${DB_USER}" >&2
            exit 1
        fi

        echo "Connection attempt ${RETRY_COUNT}/${MAX_RETRIES}..."
        sleep "$RETRY_DELAY"
    done
fi

exec "$@"
