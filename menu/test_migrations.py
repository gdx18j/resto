from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class DishAllergenSourceMigrationTests(TransactionTestCase):
    migrate_from = [("menu", "0008_dishallergen")]
    migrate_to = [("menu", "0009_unify_dish_allergens")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        Restaurant = old_apps.get_model("orders", "Restaurant")
        Category = old_apps.get_model("menu", "Category")
        Dish = old_apps.get_model("menu", "Dish")
        Ingredient = old_apps.get_model("menu", "Ingredient")
        DishIngredient = old_apps.get_model("menu", "DishIngredient")
        Allergen = old_apps.get_model("menu", "Allergen")
        DishAllergen = old_apps.get_model("menu", "DishAllergen")

        restaurant = Restaurant.objects.create(
            name="Migration restaurant",
            slug="migration-restaurant",
        )
        category = Category.objects.create(
            restaurant=restaurant,
            name="Migration category",
            code="migration-category",
        )
        dish = Dish.objects.create(
            restaurant=restaurant,
            category=category,
            name="Migration dish",
            code="migration-dish",
            price="100.00",
        )

        ingredient_allergen = Allergen.objects.create(
            name="Ingredient allergen",
            code="ingredient-allergen",
        )
        trace_allergen = Allergen.objects.create(
            name="Trace allergen",
            code="trace-allergen",
        )
        duplicate_allergen = Allergen.objects.create(
            name="Duplicate allergen",
            code="duplicate-allergen",
        )
        ingredient = Ingredient.objects.create(name="Migration ingredient")
        ingredient.allergens.add(ingredient_allergen)
        DishIngredient.objects.create(dish=dish, ingredient=ingredient)
        dish.may_contain_allergens.add(trace_allergen)

        DishAllergen.objects.create(
            dish=dish,
            allergen=duplicate_allergen,
            relation_type="contains",
            source="heuristic",
            verification_status="suggested",
        )
        DishAllergen.objects.create(
            dish=dish,
            allergen=duplicate_allergen,
            relation_type="cross_contamination",
            source="manual",
            verification_status="verified",
        )

        self.dish_id = dish.pk
        self.ingredient_allergen_id = ingredient_allergen.pk
        self.trace_allergen_id = trace_allergen.pk
        self.duplicate_allergen_id = duplicate_allergen.pk

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_legacy_sources_are_migrated_and_duplicate_claims_are_consolidated(self):
        DishAllergen = self.apps.get_model("menu", "DishAllergen")
        Dish = self.apps.get_model("menu", "Dish")

        ingredient_link = DishAllergen.objects.get(
            dish_id=self.dish_id,
            allergen_id=self.ingredient_allergen_id,
        )
        self.assertEqual(ingredient_link.relation_type, "contains")
        self.assertEqual(ingredient_link.verification_status, "verified")

        trace_link = DishAllergen.objects.get(
            dish_id=self.dish_id,
            allergen_id=self.trace_allergen_id,
        )
        self.assertEqual(trace_link.relation_type, "cross_contamination")
        self.assertEqual(trace_link.verification_status, "verified")

        duplicate_links = DishAllergen.objects.filter(
            dish_id=self.dish_id,
            allergen_id=self.duplicate_allergen_id,
        )
        self.assertEqual(duplicate_links.count(), 1)
        duplicate_link = duplicate_links.get()
        self.assertEqual(duplicate_link.relation_type, "cross_contamination")
        self.assertEqual(duplicate_link.verification_status, "verified")

        self.assertNotIn(
            "may_contain_allergens",
            {field.name for field in Dish._meta.get_fields()},
        )


class DishAllergenReviewWorkflowMigrationTests(TransactionTestCase):
    migrate_from = [("menu", "0009_unify_dish_allergens")]
    migrate_to = [("menu", "0010_allergen_review_workflow")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        Restaurant = old_apps.get_model("orders", "Restaurant")
        Category = old_apps.get_model("menu", "Category")
        Dish = old_apps.get_model("menu", "Dish")
        Allergen = old_apps.get_model("menu", "Allergen")
        DishAllergen = old_apps.get_model("menu", "DishAllergen")

        restaurant = Restaurant.objects.create(
            name="Review migration restaurant",
            slug="review-migration-restaurant",
        )
        category = Category.objects.create(
            restaurant=restaurant,
            name="Review migration category",
            code="review-migration-category",
        )
        needs_review_dish = Dish.objects.create(
            restaurant=restaurant,
            category=category,
            name="Needs review dish",
            code="needs-review-dish",
            price="100.00",
        )
        partial_dish = Dish.objects.create(
            restaurant=restaurant,
            category=category,
            name="Partial review dish",
            code="partial-review-dish",
            price="120.00",
        )
        verified = Allergen.objects.create(
            name="Verified migration allergen",
            code="verified-migration-allergen",
        )
        suggested = Allergen.objects.create(
            name="Suggested migration allergen",
            code="suggested-migration-allergen",
        )
        rejected = Allergen.objects.create(
            name="Rejected migration allergen",
            code="rejected-migration-allergen",
        )

        DishAllergen.objects.create(
            dish=needs_review_dish,
            allergen=verified,
            relation_type="contains",
            source="manual",
            verification_status="verified",
        )
        DishAllergen.objects.create(
            dish=needs_review_dish,
            allergen=suggested,
            relation_type="contains",
            source="heuristic",
            verification_status="suggested",
        )
        DishAllergen.objects.create(
            dish=partial_dish,
            allergen=rejected,
            relation_type="may_contain",
            source="manual",
            verification_status="rejected",
        )

        self.needs_review_dish_id = needs_review_dish.pk
        self.partial_dish_id = partial_dish.pk
        self.verified_allergen_id = verified.pk
        self.suggested_allergen_id = suggested.pk
        self.rejected_allergen_id = rejected.pk

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_decisions_are_backfilled_for_recipe_revision_one(self):
        Dish = self.apps.get_model("menu", "Dish")
        DishAllergen = self.apps.get_model("menu", "DishAllergen")

        needs_review_dish = Dish.objects.get(pk=self.needs_review_dish_id)
        partial_dish = Dish.objects.get(pk=self.partial_dish_id)
        verified_link = DishAllergen.objects.get(
            dish_id=self.needs_review_dish_id,
            allergen_id=self.verified_allergen_id,
        )
        suggested_link = DishAllergen.objects.get(
            dish_id=self.needs_review_dish_id,
            allergen_id=self.suggested_allergen_id,
        )
        rejected_link = DishAllergen.objects.get(
            dish_id=self.partial_dish_id,
            allergen_id=self.rejected_allergen_id,
        )

        self.assertEqual(needs_review_dish.recipe_revision, 1)
        self.assertEqual(needs_review_dish.allergen_review_status, "needs_review")
        self.assertEqual(partial_dish.allergen_review_status, "partial")
        self.assertEqual(verified_link.reviewed_recipe_revision, 1)
        self.assertIsNotNone(verified_link.reviewed_at)
        self.assertEqual(rejected_link.reviewed_recipe_revision, 1)
        self.assertIsNotNone(rejected_link.reviewed_at)
        self.assertIsNone(suggested_link.reviewed_recipe_revision)
        self.assertIsNone(suggested_link.reviewed_at)
