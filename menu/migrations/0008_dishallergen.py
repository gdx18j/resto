import django.db.models.deletion
from django.db import migrations, models


def migrate_existing_allergens(apps, schema_editor):
    Dish = apps.get_model("menu", "Dish")
    DishAllergen = apps.get_model("menu", "DishAllergen")

    for dish in Dish.objects.all().iterator():
        for dish_ingredient in dish.dish_ingredients.select_related("ingredient").all():
            for allergen in dish_ingredient.ingredient.allergens.all():
                DishAllergen.objects.update_or_create(
                    dish=dish,
                    allergen=allergen,
                    relation_type="contains",
                    defaults={
                        "source": "recipe",
                        "verification_status": "verified",
                        "notes": "Migrated from ingredient allergens.",
                    },
                )

        for allergen in dish.may_contain_allergens.all():
            DishAllergen.objects.update_or_create(
                dish=dish,
                allergen=allergen,
                relation_type="cross_contamination",
                defaults={
                    "source": "manual",
                    "verification_status": "verified",
                    "notes": "Migrated from dish may_contain_allergens.",
                },
            )


def reverse_migrate_existing_allergens(apps, schema_editor):
    DishAllergen = apps.get_model("menu", "DishAllergen")
    DishAllergen.objects.filter(
        notes__in=[
            "Migrated from ingredient allergens.",
            "Migrated from dish may_contain_allergens.",
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0007_allergentranslation_categorytranslation_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="DishAllergen",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "relation_type",
                    models.CharField(
                        choices=[
                            ("contains", "Содержит"),
                            ("may_contain", "Может содержать"),
                            ("cross_contamination", "Может содержать следы"),
                        ],
                        default="contains",
                        max_length=32,
                        verbose_name="Тип связи",
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("recipe", "Рецепт"),
                            ("manual", "Вручную"),
                            ("import", "Импорт"),
                            ("heuristic", "Эвристика"),
                        ],
                        default="manual",
                        max_length=20,
                        verbose_name="Источник",
                    ),
                ),
                (
                    "verification_status",
                    models.CharField(
                        choices=[
                            ("verified", "Подтверждено"),
                            ("suggested", "Предложено"),
                            ("rejected", "Отклонено"),
                        ],
                        db_index=True,
                        default="suggested",
                        max_length=20,
                        verbose_name="Статус проверки",
                    ),
                ),
                (
                    "notes",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="Примечание",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "allergen",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dish_links",
                        to="menu.allergen",
                        verbose_name="Аллерген",
                    ),
                ),
                (
                    "dish",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allergen_links",
                        to="menu.dish",
                        verbose_name="Блюдо",
                    ),
                ),
            ],
            options={
                "verbose_name": "Аллерген блюда",
                "verbose_name_plural": "Аллергены блюд",
                "ordering": ["dish__name", "allergen__name", "relation_type"],
            },
        ),
        migrations.AddConstraint(
            model_name="dishallergen",
            constraint=models.UniqueConstraint(
                fields=("dish", "allergen", "relation_type"),
                name="unique_dish_allergen_relation",
            ),
        ),
        migrations.AddIndex(
            model_name="dishallergen",
            index=models.Index(
                fields=["dish", "verification_status", "relation_type"],
                name="dish_allergen_status_type_idx",
            ),
        ),
        migrations.RunPython(
            migrate_existing_allergens,
            reverse_migrate_existing_allergens,
        ),
    ]
