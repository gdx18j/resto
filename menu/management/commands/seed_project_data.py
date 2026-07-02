from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

from menu.codes import build_stable_code
from menu.models import (
    Allergen,
    AllergenTranslation,
    Category,
    CategoryTranslation,
    Dish,
    DishTranslation,
)
from menu.translation_seed import (
    ALLERGEN_TRANSLATIONS,
    CATEGORY_TRANSLATIONS,
    DISH_TRANSLATIONS,
)
from orders.models import Restaurant, Table


DEFAULT_RESTAURANT_SLUG = "caesar-company"
DEFAULT_TABLE_NUMBERS = "1,2,3,4,5,6,7,8"


class Command(BaseCommand):
    help = "Seed deterministic project data after migrations have been applied."

    def add_arguments(self, parser):
        parser.add_argument(
            "--menu-json",
            default=str(settings.BASE_DIR / "data" / "caesar_and_company_menu_seed.json"),
            help="Path to the versioned menu seed JSON.",
        )
        parser.add_argument(
            "--restaurant-slug",
            default=DEFAULT_RESTAURANT_SLUG,
            help="Restaurant slug used by menu and table seed data.",
        )
        parser.add_argument(
            "--tables",
            default=DEFAULT_TABLE_NUMBERS,
            help="Comma-separated table numbers to create or update.",
        )
        parser.add_argument(
            "--clear-menu",
            action="store_true",
            help="Delete existing menu rows for the restaurant before importing.",
        )
        parser.add_argument(
            "--skip-menu",
            action="store_true",
            help="Create base restaurant/table data without importing menu dishes.",
        )
        parser.add_argument(
            "--skip-tables",
            action="store_true",
            help="Import menu data without creating default restaurant tables.",
        )
        parser.add_argument(
            "--skip-allergens",
            action="store_true",
            help="Do not import suggested allergens from the menu seed JSON.",
        )
        parser.add_argument(
            "--skip-translations",
            action="store_true",
            help="Do not import versioned translation seed data.",
        )

    def _assert_migrations_applied(self):
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())

        if plan:
            raise CommandError(
                "Database has unapplied migrations. Run `python manage.py migrate` "
                "before seeding data."
            )

    def _table_numbers(self, value):
        numbers = []

        for raw_number in str(value or "").split(","):
            number = raw_number.strip()

            if number and number not in numbers:
                numbers.append(number)

        return numbers

    def _seed_tables(self, restaurant, table_numbers):
        created = 0
        updated = 0

        for number in table_numbers:
            _table, was_created = Table.objects.update_or_create(
                restaurant=restaurant,
                number=number,
                defaults={
                    "title": f"Table {number}",
                    "seats": 2,
                    "is_active": True,
                },
            )

            if was_created:
                created += 1
            else:
                updated += 1

        return created, updated

    def _seed_category_translations(self, restaurant):
        updated = 0

        for source_name, translations in CATEGORY_TRANSLATIONS.items():
            code = build_stable_code(source_name, prefix="category")
            category = Category.objects.filter(
                restaurant=restaurant,
                code=code,
            ).first()

            if not category:
                continue

            for language, name in translations.items():
                CategoryTranslation.objects.update_or_create(
                    category=category,
                    language=language,
                    defaults={"name": name},
                )
                updated += 1

        return updated

    def _seed_dish_translations(self, restaurant):
        updated = 0

        for source_name, translations in DISH_TRANSLATIONS.items():
            code = build_stable_code(source_name, prefix="dish")
            dish = Dish.objects.filter(
                restaurant=restaurant,
                code=code,
            ).first()

            if not dish:
                continue

            names = translations.get("name", {})
            descriptions = translations.get("description", {})
            languages = set(names) | set(descriptions)

            for language in languages:
                DishTranslation.objects.update_or_create(
                    dish=dish,
                    language=language,
                    defaults={
                        "name": names.get(language) or dish.name,
                        "description": descriptions.get(language) or dish.description,
                    },
                )
                updated += 1

        return updated

    def _seed_allergen_translations(self):
        updated = 0

        for code, translations in ALLERGEN_TRANSLATIONS.items():
            allergen = Allergen.objects.filter(code=code).first()

            if not allergen:
                continue

            for language, name in translations.items():
                AllergenTranslation.objects.update_or_create(
                    allergen=allergen,
                    language=language,
                    defaults={"name": name},
                )
                updated += 1

        return updated

    def _seed_translations(self, restaurant):
        category_count = self._seed_category_translations(restaurant)
        dish_count = self._seed_dish_translations(restaurant)
        allergen_count = self._seed_allergen_translations()

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded translations: "
                f"categories={category_count}, dishes={dish_count}, allergens={allergen_count}"
            )
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self._assert_migrations_applied()

        restaurant, _created = Restaurant.objects.update_or_create(
            slug=options["restaurant_slug"] or DEFAULT_RESTAURANT_SLUG,
            defaults={
                "name": "Caesar & Company",
                "is_active": True,
            },
        )

        if not options["skip_tables"]:
            created_tables, updated_tables = self._seed_tables(
                restaurant,
                self._table_numbers(options["tables"]),
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seeded tables: created={created_tables}, updated={updated_tables}"
                )
            )

        if not options["skip_menu"]:
            menu_json = Path(options["menu_json"])

            if not menu_json.exists():
                raise CommandError(f"Menu seed JSON not found: {menu_json}")

            call_command(
                "import_caesar_menu",
                str(menu_json),
                clear=options["clear_menu"],
                with_allergens=not options["skip_allergens"],
                restaurant_slug=restaurant.slug,
            )

        if not options["skip_translations"]:
            self._seed_translations(restaurant)

        self.stdout.write(self.style.SUCCESS("Project seed data is ready."))
