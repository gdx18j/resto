#!/bin/sh

set -eu

printf '%s\n' "Applying database migrations..."
python manage.py migrate --noinput

printf '%s\n' "Loading base restaurant fixture..."
python manage.py loaddata data/fixtures/base_restaurant.json

printf '%s\n' "Seeding menu data..."
python manage.py seed_project_data

printf '%s\n' "Render seed completed successfully."
