# Data, Schema, and Local Databases

The project schema is versioned by Django migrations in each app's
`migrations/` directory. Runtime database files are not source data.

## Source of Truth

- Schema: committed Django migrations.
- Menu seed data: `data/caesar_and_company_menu_seed.json`.
- Base fixture: `data/fixtures/base_restaurant.json`.
- Runtime data: PostgreSQL volumes, local `db.sqlite3`, and backup dumps.

Do not treat `db.sqlite3` as part of the project state. It is ignored by Git and
Docker packaging because it can easily lag behind the current migrations.

## Clean Local Bootstrap

For a clean SQLite development database:

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

The seed command refuses to run when migrations are unapplied. Run
`python manage.py migrate --check` in CI or before packaging to detect a stale
database state.

## Translations

Menu translations are stored in database tables, not in runtime Python
dictionaries. Categories and dishes have stable `code` values; renaming `name`
in the admin does not change the code or detach translations.

Edit translations from the Django admin in the category, dish, or allergen
inline forms. Each object can have only one translation per language.

CI should run:

```bash
python manage.py check_menu_translations --restaurant-slug caesar-company
python manage.py validate_translation_sources
```

`check_menu_translations` fails when an active category, active dish, or allergen
is missing a required translation. `validate_translation_sources` parses Python
and JSON seed files in a duplicate-aware mode, so repeated literal keys cannot be
silently overwritten.

## Production Import

The Docker entrypoint always runs migrations. To import menu seed data during a
controlled deployment, set:

```env
IMPORT_SEED_DATA_ON_STARTUP=True
```

This imports `data/caesar_and_company_menu_seed.json` with allergen suggestions.
Keep this disabled unless you intentionally want startup to upsert seed data.

## Backups

Backups belong outside Git and release ZIPs. Use the PostgreSQL scripts:

```bash
sh ops/backup_postgres.sh
sh ops/restore_postgres.sh backups/pre-release.dump
```

The `backups/` directory ignores dump files by default. If you need to share a
backup, move it through a secure storage channel, not through the source tree.
