#!/bin/sh

set -eu

printf '%s\n' "Running Django system checks..."
python manage.py check

printf '%s\n' "Applying database migrations..."
python manage.py migrate --noinput

printf '%s\n' "Collecting static files..."
python manage.py collectstatic --noinput --clear

printf '%s\n' "Verifying that no migrations remain unapplied..."
python manage.py migrate --check

printf '%s\n' "Release tasks completed successfully."
