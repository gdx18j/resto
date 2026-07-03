import json
from decimal import Decimal
from io import StringIO
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserAllergy
from orders.models import Restaurant, Table

from .allergen_review import (
    complete_dish_allergen_review,
    review_dish_allergen_link,
)
from .models import (
    Allergen,
    Category,
    CategoryTranslation,
    Dish,
    DishAllergen,
    DishAllergenReviewEvent,
    DishIngredient,
    DishTranslation,
    Ingredient,
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
    def test_menu_loads_dish_details_on_demand(self):
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
        self.assertNotIn('id="dish-detail-data"', html)
        self.assertEqual(html.count("data-detail-url="), 2)
        self.assertEqual(html.count("data-dish-modal hidden"), 1)

    def test_dish_cards_use_a_real_button_instead_of_button_role_on_article(self):
        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertNotIn('role="button"', html)
        self.assertNotIn('tabindex="0"', html)
        self.assertContains(response, 'class="dish-card__open"')
        self.assertContains(response, "data-dish-open")

    def test_card_images_reserve_space_and_lazy_load_after_first_image(self):
        Dish.objects.create(
            category=self.dish.category,
            name="Latte",
            price=Decimal("220.00"),
            image="dishes/test/latte.jpg",
            is_active=True,
            is_available=True,
        )
        self.dish.image = "dishes/test/americano.jpg"
        self.dish.save(update_fields=["image", "updated_at"])

        response = self.client.get(reverse("menu:dish_list"))

        self.assertContains(response, 'width="640"')
        self.assertContains(response, 'height="480"')
        self.assertContains(response, 'decoding="async"')
        self.assertContains(response, 'loading="eager"')
        self.assertContains(response, 'loading="lazy"')

    def test_language_cookie_sets_server_document_language_and_accessible_labels(self):
        self.client.cookies["cc_language"] = "en"

        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="en" data-language="en">')
        self.assertContains(response, 'id="lang-en" checked')
        self.assertContains(response, 'aria-label="Search menu"')
        self.assertContains(response, 'aria-label="Clear search"')
        self.assertContains(response, "static/js/ui-preferences.js")

    def test_base_template_has_no_inline_script_or_inline_event_handler(self):
        response = self.client.get(reverse("menu:dish_list"))
        html = response.content.decode("utf-8")

        self.assertNotIn("<script>", html)
        self.assertNotIn(" onclick=", html)
        self.assertNotIn(" onchange=", html)
        self.assertIn('class="skip-link"', html)

    def test_regular_menu_is_catalog_only(self):
        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-ordering-enabled="0"')
        self.assertContains(response, 'class="dish-price-label"')
        self.assertNotContains(response, "data-add-btn")
        self.assertNotContains(response, "static/js/cart.js")
        self.assertContains(response, "Чтобы заказать на стол")

    def test_unknown_restaurant_slug_returns_404(self):
        response = self.client.get(
            reverse("menu:dish_list"),
            {"restaurant": "unknown-restaurant"},
        )

        self.assertEqual(response.status_code, 404)

    def test_menu_does_not_create_restaurant_during_get(self):
        Restaurant.objects.update(is_active=False)
        restaurant_count = Restaurant.objects.count()

        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Restaurant.objects.count(), restaurant_count)

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

    def test_qr_entry_redirects_to_limited_table_context(self):
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="5",
        )
        table_token = table.plain_qr_token

        entry_response = self.client.get(
            reverse("menu:table_menu", args=[table_token])
        )

        self.assertEqual(entry_response.status_code, 302)
        self.assertNotIn(table_token, entry_response.url)
        self.assertIn("/table/", entry_response.url)
        self.assertEqual(entry_response["Cache-Control"], "no-store, private")
        self.assertEqual(entry_response["Referrer-Policy"], "no-referrer")

        response = self.client.get(entry_response.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'data-cart-restaurant-slug="{self.dish.restaurant.slug}"',
        )
        table_context = response.context["cart_table_context"]
        self.assertTrue(table_context)
        self.assertNotIn(table_token, table_context)
        self.assertContains(
            response,
            f'data-cart-table-context="{table_context}"',
        )
        self.assertNotContains(response, "data-cart-table-token")
        self.assertContains(response, 'data-cart-order-source="qr"')
        storage_scope = response.context["cart_storage_scope"]
        self.assertEqual(len(storage_scope), 24)
        self.assertNotIn(table_token, storage_scope)
        self.assertContains(
            response,
            f'data-cart-storage-scope="{storage_scope}"',
        )
        self.assertContains(response, 'data-ordering-enabled="1"')
        self.assertContains(response, "data-add-btn")
        self.assertContains(response, "static/js/cart.js")
        self.assertContains(response, "static/js/table-context.js")
        self.assertContains(response, 'data-table-context-ttl-seconds="43200"')
        self.assertContains(response, "Стол 5")
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertNotIn("table_token", self.client.session)
        self.assertNotIn("table_id", self.client.session)

    def test_qr_rotation_changes_context_and_cart_storage_scope(self):
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="7",
        )
        first_token = table.plain_qr_token
        first_entry = self.client.get(
            reverse("menu:table_menu", args=[first_token])
        )
        first_response = self.client.get(first_entry.url)
        first_scope = first_response.context["cart_storage_scope"]
        first_context = first_response.context["cart_table_context"]

        second_token = table.rotate_qr_token(reason="Test rotation")
        second_entry = self.client.get(
            reverse("menu:table_menu", args=[second_token])
        )
        second_response = self.client.get(second_entry.url)
        second_scope = second_response.context["cart_storage_scope"]
        second_context = second_response.context["cart_table_context"]

        self.assertEqual(first_entry.status_code, 302)
        self.assertEqual(second_entry.status_code, 302)
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertNotEqual(first_scope, second_scope)
        self.assertNotEqual(first_context, second_context)
        self.assertNotIn(first_token, first_context)
        self.assertNotIn(second_token, second_context)

        revoked_context_response = self.client.get(first_entry.url)
        self.assertEqual(revoked_context_response.status_code, 302)
        self.assertIn(
            "table_context_error=table_context_revoked",
            revoked_context_response.url,
        )

    def test_invalid_table_context_returns_to_catalog_and_clears_client_context(self):
        response = self.client.get(
            reverse("menu:table_context_menu", args=["invalid-context"])
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("table_context_error=invalid_table_context", response.url)

        catalog_response = self.client.get(response.url)
        self.assertEqual(catalog_response.status_code, 200)
        self.assertTrue(catalog_response.context["clear_table_context"])
        self.assertContains(catalog_response, 'data-table-context-clear="1"')

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

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 429)
        self.assertEqual(second_response["Retry-After"], "60")

    def test_ingredient_reference_allergens_are_not_published_directly(self):
        allergen = Allergen.objects.create(
            name="Reference milk",
            code="reference-milk",
        )
        ingredient = Ingredient.objects.create(name="Reference cream")
        ingredient.allergens.add(allergen)
        DishIngredient.objects.create(
            dish=self.dish,
            ingredient=ingredient,
        )

        response = self.client.get(
            reverse(
                "menu:dish_detail",
                kwargs={
                    "restaurant_slug": self.dish.restaurant.slug,
                    "dish_id": self.dish.id,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["allergen_groups"]["unknown"][0]["ru"],
            "Reference milk",
        )
        self.assertFalse(self.dish.get_verified_allergens().exists())
        self.assertFalse(self.dish.conflicts_with_allergens([allergen.id]))

    def test_only_verified_dish_allergen_conflicts_with_user_profile(self):
        allergen = Allergen.objects.create(
            name="Suggested soy",
            code="suggested-soy-conflict",
        )
        link = DishAllergen.objects.create(
            dish=self.dish,
            allergen=allergen,
            relation_type=DishAllergen.RelationType.CONTAINS,
            source=DishAllergen.Source.HEURISTIC,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )

        self.assertFalse(self.dish.conflicts_with_allergens([allergen.id]))

        review_dish_allergen_link(
            link.pk,
            decision=DishAllergen.VerificationStatus.VERIFIED,
            actor=None,
        )

        self.assertTrue(self.dish.conflicts_with_allergens([allergen.id]))

    def test_one_dish_cannot_have_multiple_relations_for_same_allergen(self):
        allergen = Allergen.objects.create(
            name="Unique allergen",
            code="unique-dish-allergen",
        )
        link = DishAllergen.objects.create(
            dish=self.dish,
            allergen=allergen,
            relation_type=DishAllergen.RelationType.CONTAINS,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )
        review_dish_allergen_link(
            link.pk,
            decision=DishAllergen.VerificationStatus.VERIFIED,
            actor=None,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            DishAllergen.objects.create(
                dish=self.dish,
                allergen=allergen,
                relation_type=DishAllergen.RelationType.CROSS_CONTAMINATION,
                verification_status=DishAllergen.VerificationStatus.SUGGESTED,
            )

    def test_safe_mark_requires_selected_user_allergies(self):
        user = get_user_model().objects.create_user(
            email="no-allergies@example.com",
            password="strong-pass-123",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "В подтверждённых данных совпадений не найдено",
        )

    def test_safe_mark_describes_only_verified_allergen_data(self):
        user = get_user_model().objects.create_user(
            email="verified-wording@example.com",
            password="strong-pass-123",
        )
        allergen = Allergen.objects.create(
            name="Profile allergen",
            code="profile-allergen-safe-mark",
        )
        UserAllergy.objects.create(
            user=user,
            allergen=allergen,
            status=UserAllergy.Status.CONFIRMED,
        )
        self.client.force_login(user)
        complete_dish_allergen_review(
            self.dish.pk,
            actor=None,
            notes="No known allergens for the current recipe.",
        )

        response = self.client.get(reverse("menu:dish_list"))

        self.assertContains(
            response,
            "В подтверждённых данных совпадений не найдено",
        )
        self.assertNotContains(response, "Без совпадений с вашими аллергиями")

    def test_dish_detail_payload_separates_allergen_confidence(self):
        milk = Allergen.objects.create(name="Milk", code="milk-test")
        nuts = Allergen.objects.create(name="Nuts", code="nuts-test")
        soy = Allergen.objects.create(name="Soy", code="soy-test")
        milk_link = DishAllergen.objects.create(
            dish=self.dish,
            allergen=milk,
            relation_type=DishAllergen.RelationType.CONTAINS,
            source=DishAllergen.Source.RECIPE,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )
        nuts_link = DishAllergen.objects.create(
            dish=self.dish,
            allergen=nuts,
            relation_type=DishAllergen.RelationType.CROSS_CONTAMINATION,
            source=DishAllergen.Source.MANUAL,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )
        review_dish_allergen_link(
            milk_link.pk,
            decision=DishAllergen.VerificationStatus.VERIFIED,
            actor=None,
        )
        review_dish_allergen_link(
            nuts_link.pk,
            decision=DishAllergen.VerificationStatus.VERIFIED,
            actor=None,
        )
        DishAllergen.objects.create(
            dish=self.dish,
            allergen=soy,
            relation_type=DishAllergen.RelationType.CONTAINS,
            source=DishAllergen.Source.HEURISTIC,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )

        response = self.client.get(
            reverse(
                "menu:dish_detail",
                kwargs={
                    "restaurant_slug": self.dish.restaurant.slug,
                    "dish_id": self.dish.id,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["allergen_groups"]["contains"][0]["ru"], "Milk")
        self.assertEqual(payload["allergen_groups"]["traces"][0]["ru"], "Nuts")
        self.assertEqual(payload["allergen_groups"]["unknown"][0]["ru"], "Soy")


    def test_dish_detail_endpoint_is_scoped_to_restaurant_and_availability(self):
        second_restaurant = Restaurant.objects.create(
            name="Second restaurant",
            slug="second-restaurant-detail",
        )

        valid_url = reverse(
            "menu:dish_detail",
            kwargs={
                "restaurant_slug": self.dish.restaurant.slug,
                "dish_id": self.dish.id,
            },
        )
        wrong_restaurant_url = reverse(
            "menu:dish_detail",
            kwargs={
                "restaurant_slug": second_restaurant.slug,
                "dish_id": self.dish.id,
            },
        )

        valid_response = self.client.get(valid_url)
        self.assertEqual(valid_response.status_code, 200)
        self.assertEqual(valid_response.json()["cart_id"], f"dish-{self.dish.id}")
        self.assertEqual(valid_response["Cache-Control"], "private, no-store")

        self.assertEqual(self.client.get(wrong_restaurant_url).status_code, 404)

        self.dish.is_available = False
        self.dish.save(update_fields=["is_available", "updated_at"])
        self.assertEqual(self.client.get(valid_url).status_code, 404)

    def test_category_translations_do_not_create_a_query_per_section(self):
        for index in range(5):
            category = Category.objects.create(
                restaurant=self.dish.restaurant,
                name=f"Category {index}",
            )
            CategoryTranslation.objects.create(
                category=category,
                language="en",
                name=f"Translated {index}",
            )
            Dish.objects.create(
                restaurant=self.dish.restaurant,
                category=category,
                name=f"Dish {index}",
                price=Decimal("100.00"),
                is_active=True,
                is_available=True,
            )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 22)


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


class MenuImportAllergenTests(TestCase):
    def test_import_creates_one_suggestion_and_preserves_verified_review(self):
        payload = {
            "dishes": [
                {
                    "category": "Import category",
                    "name": "Import milk dish",
                    "description_ru": "Test dish",
                    "price_current_try": "100.00",
                    "ingredients_text_ru": "Молоко",
                    "suggested_allergens": ["молоко"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "menu.json"
            source_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            call_command(
                "import_caesar_menu",
                str(source_path),
                "--with-allergens",
                stdout=StringIO(),
            )

            dish = Dish.objects.get(name="Import milk dish")
            links = dish.allergen_links.all()
            self.assertEqual(links.count(), 1)
            link = links.get()
            self.assertEqual(
                link.relation_type,
                DishAllergen.RelationType.CONTAINS,
            )
            self.assertEqual(
                link.verification_status,
                DishAllergen.VerificationStatus.SUGGESTED,
            )

            link.relation_type = DishAllergen.RelationType.CROSS_CONTAMINATION
            link.source = DishAllergen.Source.MANUAL
            link.notes = "Reviewed by restaurant staff."
            link.save(update_fields=["relation_type", "source", "notes", "updated_at"])
            review_dish_allergen_link(
                link.pk,
                decision=DishAllergen.VerificationStatus.VERIFIED,
                actor=None,
            )

            call_command(
                "import_caesar_menu",
                str(source_path),
                "--with-allergens",
                stdout=StringIO(),
            )

        link.refresh_from_db()
        self.assertEqual(dish.allergen_links.count(), 1)
        self.assertEqual(
            link.relation_type,
            DishAllergen.RelationType.CROSS_CONTAMINATION,
        )
        self.assertEqual(link.source, DishAllergen.Source.MANUAL)
        self.assertEqual(
            link.verification_status,
            DishAllergen.VerificationStatus.VERIFIED,
        )
        self.assertEqual(link.notes, "Reviewed by restaurant staff.")


class AllergenReviewWorkflowTests(TestCase):
    def setUp(self):
        self.reviewer = get_user_model().objects.create_user(
            email="allergen-reviewer@example.com",
            password="strong-pass-123",
            is_staff=True,
        )
        self.category = Category.objects.create(name="Review category")
        self.dish = Dish.objects.create(
            category=self.category,
            name="Review dish",
            price=Decimal("250.00"),
            is_active=True,
            is_available=True,
        )
        self.allergen = Allergen.objects.create(
            name="Review milk",
            code="review-milk",
        )

    def _create_reviewed_link(self):
        link = DishAllergen.objects.create(
            dish=self.dish,
            allergen=self.allergen,
            relation_type=DishAllergen.RelationType.CONTAINS,
            source=DishAllergen.Source.MANUAL,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )
        return review_dish_allergen_link(
            link.pk,
            decision=DishAllergen.VerificationStatus.VERIFIED,
            actor=self.reviewer,
            notes="Checked against the current recipe.",
        )

    def test_review_decision_records_actor_revision_and_event(self):
        link = self._create_reviewed_link()

        self.assertEqual(link.reviewed_by, self.reviewer)
        self.assertEqual(
            link.reviewed_recipe_revision,
            self.dish.recipe_revision,
        )
        self.assertIsNotNone(link.reviewed_at)
        event = DishAllergenReviewEvent.objects.get(
            dish=self.dish,
            allergen=self.allergen,
            action=DishAllergenReviewEvent.Action.VERIFIED,
        )
        self.assertEqual(event.actor, self.reviewer)
        self.assertEqual(event.recipe_revision, self.dish.recipe_revision)

    def test_complete_review_requires_all_suggestions_to_be_resolved(self):
        DishAllergen.objects.create(
            dish=self.dish,
            allergen=self.allergen,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )

        with self.assertRaises(ValidationError):
            complete_dish_allergen_review(
                self.dish.pk,
                actor=self.reviewer,
            )

    def test_review_can_explicitly_confirm_no_known_allergens(self):
        complete_dish_allergen_review(
            self.dish.pk,
            actor=self.reviewer,
            notes="Recipe checked; no declared allergens.",
        )
        self.dish.refresh_from_db()

        self.assertTrue(self.dish.is_allergen_review_complete)
        self.assertEqual(
            self.dish.allergen_reviewed_revision,
            self.dish.recipe_revision,
        )
        self.assertEqual(self.dish.allergen_reviewed_by, self.reviewer)

    def test_recipe_change_invalidates_previous_review(self):
        ingredient = Ingredient.objects.create(name="Review ingredient")
        dish_ingredient = DishIngredient.objects.create(
            dish=self.dish,
            ingredient=ingredient,
            notes="Initial recipe",
        )
        self.dish.refresh_from_db()
        link = self._create_reviewed_link()
        complete_dish_allergen_review(
            self.dish.pk,
            actor=self.reviewer,
        )
        self.dish.refresh_from_db()
        reviewed_revision = self.dish.recipe_revision

        dish_ingredient.notes = "Changed recipe"
        dish_ingredient.save(update_fields=["notes"])

        self.dish.refresh_from_db()
        link.refresh_from_db()
        self.assertEqual(self.dish.recipe_revision, reviewed_revision + 1)
        self.assertEqual(
            self.dish.allergen_review_status,
            Dish.AllergenReviewStatus.NEEDS_REVIEW,
        )
        self.assertFalse(self.dish.is_allergen_review_complete)
        self.assertEqual(
            link.verification_status,
            DishAllergen.VerificationStatus.SUGGESTED,
        )
        self.assertIsNone(link.reviewed_recipe_revision)
        self.assertFalse(
            self.dish.conflicts_with_allergens([self.allergen.pk])
        )
        self.assertTrue(
            DishAllergenReviewEvent.objects.filter(
                dish=self.dish,
                action=DishAllergenReviewEvent.Action.INVALIDATED,
                recipe_revision=self.dish.recipe_revision,
            ).exists()
        )

    def test_reference_allergen_change_creates_suggestion(self):
        ingredient = Ingredient.objects.create(name="Reference ingredient")
        DishIngredient.objects.create(
            dish=self.dish,
            ingredient=ingredient,
        )
        self.dish.refresh_from_db()
        previous_revision = self.dish.recipe_revision

        ingredient.allergens.add(self.allergen)

        self.dish.refresh_from_db()
        link = DishAllergen.objects.get(
            dish=self.dish,
            allergen=self.allergen,
        )
        self.assertEqual(self.dish.recipe_revision, previous_revision + 1)
        self.assertEqual(
            link.verification_status,
            DishAllergen.VerificationStatus.SUGGESTED,
        )
        self.assertEqual(link.source, DishAllergen.Source.RECIPE)

    def test_review_event_cannot_be_modified_or_deleted(self):
        self._create_reviewed_link()
        event = DishAllergenReviewEvent.objects.get(
            action=DishAllergenReviewEvent.Action.VERIFIED
        )
        event.notes = "Changed"

        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_database_rejects_complete_review_for_wrong_recipe_revision(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Dish.objects.filter(pk=self.dish.pk).update(
                allergen_review_status=Dish.AllergenReviewStatus.COMPLETE,
                allergen_reviewed_revision=self.dish.recipe_revision + 1,
                allergen_reviewed_at=timezone.now(),
            )
