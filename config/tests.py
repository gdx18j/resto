import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


class CleanMigrationSeedTests(SimpleTestCase):
    def test_clean_sqlite_database_migrates_and_seeds(self):
        base_dir = Path(__file__).resolve().parent.parent

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "clean.sqlite3"
            env = os.environ.copy()

            for name in (
                "DB_HOST",
                "DB_NAME",
                "DB_USER",
                "DB_PASSWORD",
                "DB_PORT",
                "REDIS_URL",
            ):
                env.pop(name, None)

            env.update(
                {
                    "DJANGO_ENV": "development",
                    "SQLITE_DATABASE_PATH": str(db_path),
                    "RATE_LIMIT_ENABLED": "False",
                    "PYTHONIOENCODING": "utf-8",
                }
            )

            migrate = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "migrate",
                    "--noinput",
                    "--verbosity",
                    "0",
                ],
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(
                migrate.returncode,
                0,
                msg=migrate.stdout + migrate.stderr,
            )

            fixture = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "loaddata",
                    "data/fixtures/base_restaurant.json",
                    "--verbosity",
                    "0",
                ],
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(
                fixture.returncode,
                0,
                msg=fixture.stdout + fixture.stderr,
            )

            seed = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "seed_project_data",
                    "--verbosity",
                    "0",
                ],
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(seed.returncode, 0, msg=seed.stdout + seed.stderr)

            translations = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "check_menu_translations",
                    "--restaurant-slug",
                    "caesar-company",
                ],
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(
                translations.returncode,
                0,
                msg=translations.stdout + translations.stderr,
            )

            connection = sqlite3.connect(db_path)
            cursor = connection.cursor()
            applied_migrations = set(
                cursor.execute(
                    "select app, name from django_migrations where app in ('menu', 'orders')"
                ).fetchall()
            )
            tables = {
                row[0]
                for row in cursor.execute(
                    "select name from sqlite_master where type = 'table'"
                ).fetchall()
            }
            table_count = cursor.execute("select count(*) from orders_table").fetchone()[0]
            dish_count = cursor.execute("select count(*) from menu_dish").fetchone()[0]
            connection.close()

        self.assertIn(("menu", "0006_alter_category_options_and_more"), applied_migrations)
        self.assertIn(("orders", "0004_table_qr_token"), applied_migrations)
        self.assertIn(("orders", "0005_table_qr_token_security"), applied_migrations)
        self.assertIn("orders_order", tables)
        self.assertIn("orders_table", tables)
        self.assertGreaterEqual(table_count, 1)
        self.assertGreater(dish_count, 0)
