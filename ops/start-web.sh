#!/bin/sh

set -eu

DJANGO_ENV_NORMALIZED=$(printf '%s' "${DJANGO_ENV:-development}" | tr '[:upper:]' '[:lower:]')
DJANGO_DEBUG_NORMALIZED=$(printf '%s' "${DJANGO_DEBUG:-False}" | tr '[:upper:]' '[:lower:]')

if [ "$DJANGO_ENV_NORMALIZED" = "development" ] || [ "$DJANGO_DEBUG_NORMALIZED" = "true" ]; then
    # Local Docker runs should use a single Django process. Gunicorn workers are
    # useful for production but make localhost cold starts and first UI actions
    # noticeably heavier on small machines.
    exec python manage.py runserver 0.0.0.0:8000 --noreload
fi

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile -
