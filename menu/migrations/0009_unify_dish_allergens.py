from django.db import migrations, models
from django.db.models import Count


STATUS_PRIORITY = {
    "verified": 3,
    "suggested": 2,
    "rejected": 1,
}

RELATION_PRIORITY = {
    "contains": 3,
    "cross_contamination": 2,
    "may_contain": 1,
}

SOURCE_PRIORITY = {
    "manual": 4,
    "recipe": 3,
    "import": 2,
    "heuristic": 1,
}


def _link_priority(link):
    return (
        STATUS_PRIORITY.get(link.verification_status, 0),
        RELATION_PRIORITY.get(link.relation_type, 0),
        SOURCE_PRIORITY.get(link.source, 0),
        link.updated_at,
        link.pk,
    )


def migrate_legacy_allergens(apps, schema_editor):
    Dish = apps.get_model("menu", "Dish")
    DishAllergen = apps.get_model("menu", "DishAllergen")

    for dish in Dish.objects.all().iterator():
        for dish_ingredient in dish.dish_ingredients.select_related(
            "ingredient"
        ).iterator():
            for allergen in dish_ingredient.ingredient.allergens.all():
                DishAllergen.objects.get_or_create(
                    dish_id=dish.pk,
                    allergen_id=allergen.pk,
                    relation_type="contains",
                    defaults={
                        "source": "recipe",
                        "verification_status": "verified",
                        "notes": "Migrated from ingredient allergen reference.",
                    },
                )

        for allergen in dish.may_contain_allergens.all():
            DishAllergen.objects.get_or_create(
                dish_id=dish.pk,
                allergen_id=allergen.pk,
                relation_type="cross_contamination",
                defaults={
                    "source": "manual",
                    "verification_status": "verified",
                    "notes": "Migrated from legacy dish trace allergens.",
                },
            )

    duplicate_groups = (
        DishAllergen.objects.values("dish_id", "allergen_id")
        .annotate(link_count=Count("id"))
        .filter(link_count__gt=1)
    )

    for group in duplicate_groups.iterator():
        links = list(
            DishAllergen.objects.filter(
                dish_id=group["dish_id"],
                allergen_id=group["allergen_id"],
            )
        )
        winner = max(links, key=_link_priority)
        DishAllergen.objects.filter(
            dish_id=group["dish_id"],
            allergen_id=group["allergen_id"],
        ).exclude(pk=winner.pk).delete()


def restore_legacy_trace_allergens(apps, schema_editor):
    DishAllergen = apps.get_model("menu", "DishAllergen")
    Dish = apps.get_model("menu", "Dish")

    through_model = Dish.may_contain_allergens.through
    rows = []

    for link in DishAllergen.objects.filter(
        relation_type__in=["may_contain", "cross_contamination"],
    ).exclude(verification_status="rejected").iterator():
        rows.append(
            through_model(
                dish_id=link.dish_id,
                allergen_id=link.allergen_id,
            )
        )

    through_model.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("menu", "0008_dishallergen"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="dishallergen",
            name="unique_dish_allergen_relation",
        ),
        migrations.RunPython(
            migrate_legacy_allergens,
            restore_legacy_trace_allergens,
        ),
        migrations.AddConstraint(
            model_name="dishallergen",
            constraint=models.UniqueConstraint(
                fields=("dish", "allergen"),
                name="unique_dish_allergen",
            ),
        ),
        migrations.RemoveField(
            model_name="dish",
            name="may_contain_allergens",
        ),
        migrations.AlterField(
            model_name="ingredient",
            name="allergens",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Используются только как справочник для формирования "
                    "предложений. Публичная информация о блюде берётся из "
                    "связей DishAllergen."
                ),
                related_name="ingredients",
                to="menu.allergen",
                verbose_name="Справочные аллергены ингредиента",
            ),
        ),
    ]
