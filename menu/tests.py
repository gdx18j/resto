from decimal import Decimal
from io import StringIO
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse

from orders.models import Restaurant, Table

from .models import (
    Allergen,
    Category,
    CategoryTranslation,
    Dish,
    DishAllergen,
    DishTranslation,
)
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
        self.assertContains(response, 'data-cart-restaurant-slug="second-caesar"')

    def test_qr_menu_exposes_table_token_to_cart(self):
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="5",
        )
        table_token = table.plain_qr_token

        response = self.client.get(reverse("menu:table_menu", args=[table_token]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'data-cart-restaurant-slug="{self.dish.restaurant.slug}"',
        )
        self.assertContains(response, f'data-cart-table-token="{table_token}"')

    @override_settings(
        RATE_LIMIT_RULES={
            "menu:table_menu": {
                "methods": ["GET"],
                "identity": "ip",
                "limits": [
                    {
                        "name": "test",
                        "limit": 1,
                        "window": 60,
                    }
                ],
            }
        }
    )
    def test_qr_menu_is_rate_limited(self):
        cache.clear()
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="6",
        )
        table_token = table.plain_qr_token

        first_response = self.client.get(reverse("menu:table_menu", args=[table_token]))
        second_response = self.client.get(reverse("menu:table_menu", args=[table_token]))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 429)
        self.assertEqual(second_response["Retry-After"], "60")

    def test_dish_detail_payload_separates_allergen_confidence(self):
        milk = Allergen.objects.create(name="Milk", code="milk-test")
        nuts = Allergen.objects.create(name="Nuts", code="nuts-test")
        soy = Allergen.objects.create(name="Soy", code="soy-test")
        DishAllergen.objects.create(
            dish=self.dish,
            allergen=milk,
            relation_type=DishAllergen.RelationType.CONTAINS,
            source=DishAllergen.Source.RECIPE,
            verification_status=DishAllergen.VerificationStatus.VERIFIED,
        )
        DishAllergen.objects.create(
            dish=self.dish,
            allergen=nuts,
            relation_type=DishAllergen.RelationType.CROSS_CONTAMINATION,
            source=DishAllergen.Source.MANUAL,
            verification_status=DishAllergen.VerificationStatus.VERIFIED,
        )
        DishAllergen.objects.create(
            dish=self.dish,
            allergen=soy,
            relation_type=DishAllergen.RelationType.CONTAINS,
            source=DishAllergen.Source.HEURISTIC,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )

        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        payload = response.context["dish_details"][f"dish-{self.dish.id}"]
        self.assertEqual(payload["allergen_groups"]["contains"][0]["ru"], "Milk")
        self.assertEqual(payload["allergen_groups"]["traces"][0]["ru"], "Nuts")
        self.assertEqual(payload["allergen_groups"]["unknown"][0]["ru"], "Soy")


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
