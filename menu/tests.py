from decimal import Decimal
from io import StringIO
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from orders.models import Restaurant

from .models import Category, CategoryTranslation, Dish, DishTranslation
from .translations import localized_dish_string


class MenuRenderingTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Меню")
        self.dish = Dish.objects.create(
            category=category,
            name="Americano",
            price=Decimal("150.00"),
            is_active=True,
            is_available=True,
        )
    def test_menu_uses_single_detail_payload_instead_of_per_dish_templates(self):
        Dish.objects.create(
            category=self.dish.category,
            name="Latte",
            price=Decimal("220.00"),
            is_active=True,
            is_available=True,
        )

        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertNotIn("dish-detail-template-", html)
        self.assertEqual(html.count('id="dish-detail-data"'), 1)
        self.assertEqual(html.count("data-dish-modal hidden"), 1)

    def test_menu_is_scoped_to_selected_restaurant(self):
        second_restaurant = Restaurant.objects.create(
            name="Second Caesar",
            slug="second-caesar",
        )
        second_category = Category.objects.create(
            restaurant=second_restaurant,
            name="Меню",
        )
        second_dish = Dish.objects.create(
            restaurant=second_restaurant,
            category=second_category,
            name="Only second restaurant",
            price=Decimal("300.00"),
            is_active=True,
            is_available=True,
        )

        response = self.client.get(
            reverse("menu:dish_list"),
            {"restaurant": second_restaurant.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="dish-{second_dish.id}"')
        self.assertNotContains(response, f'id="dish-{self.dish.id}"')


class MenuTranslationTests(TestCase):
    def test_dish_translation_survives_source_name_rename(self):
        category = Category.objects.create(name="Menu")
        dish = Dish.objects.create(
            category=category,
            name="Original name",
            description="Original description",
            price=Decimal("100.00"),
            is_active=True,
            is_available=True,
        )
        DishTranslation.objects.create(
            dish=dish,
            language="en",
            name="Translated name",
            description="Translated description",
        )
        original_code = dish.code

        dish.name = "Renamed in admin"
        dish.save(update_fields=["name"])
        dish.refresh_from_db()

        self.assertEqual(dish.code, original_code)
        self.assertEqual(localized_dish_string(dish, "name", language="en"), "Translated name")

    def test_translation_language_is_unique_per_object(self):
        category = Category.objects.create(name="Menu")
        CategoryTranslation.objects.create(
            category=category,
            language="en",
            name="Menu",
        )

        with self.assertRaises(IntegrityError):
            CategoryTranslation.objects.create(
                category=category,
                language="en",
                name="Duplicate",
            )

    def test_check_menu_translations_reports_missing_rows(self):
        category = Category.objects.create(name="Menu")
        Dish.objects.create(
            category=category,
            name="Americano",
            description="Coffee",
            price=Decimal("150.00"),
            is_active=True,
            is_available=True,
        )

        with self.assertRaises(CommandError):
            call_command(
                "check_menu_translations",
                "--skip-allergens",
                stderr=StringIO(),
            )

    def test_validate_translation_sources_detects_duplicate_python_keys(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "bad_translations.py"
            source_path.write_text(
                'TRANSLATIONS = {"dish": {"en": "First", "en": "Second"}}\n',
                encoding="utf-8",
            )

            with self.assertRaises(CommandError):
                call_command(
                    "validate_translation_sources",
                    str(source_path),
                    stderr=StringIO(),
                )
