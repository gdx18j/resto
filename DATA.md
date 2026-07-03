# Data, Schema, and Local Databases

The project schema is versioned by committed Django migrations. Runtime database
files are not source data.

## Source of truth

- Schema: committed migrations in each app.
- Menu seed: `data/caesar_and_company_menu_seed.json`.
- Base fixture: `data/fixtures/base_restaurant.json`.
- Runtime data: PostgreSQL volumes, local SQLite files, media volumes, backups.

Never package `db.sqlite3` as project state.

## Clean local SQLite bootstrap

```bash
python manage.py migrate
python manage.py seed_project_data
```

For a destructive menu refresh:

```bash
python manage.py seed_project_data --clear-menu
```

To import only the base fixture:

```bash
python manage.py loaddata data/fixtures/base_restaurant.json
```

The seed command refuses to run when migrations are unapplied.

## Docker release and import

The web entrypoint does not migrate or seed data. Apply schema and collect
versioned static files with the one-shot release service:

```bash
docker compose --profile release run --rm release
```

Seed data is always an explicit operator action:

```bash
docker compose exec web python manage.py seed_project_data
docker compose exec web python manage.py import_caesar_images
```

A restart of `web` therefore cannot unexpectedly alter restaurant data.

## Translations

Translations live in database tables. Categories and dishes use stable `code`
values, so renaming a display name does not detach translations.

CI should run:

```bash
python manage.py check_menu_translations --restaurant-slug caesar-company
python manage.py validate_translation_sources
```

## Backups

Backups belong outside Git and release ZIP files:

```bash
sh ops/backup_postgres.sh
sh ops/restore_postgres.sh backups/pre-release.dump
```

Move dumps only through an encrypted, access-controlled storage channel.
