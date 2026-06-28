from django.db import migrations


def link_caesar_sauce_allergens(apps, schema_editor):
    Allergen = apps.get_model("menu", "Allergen")
    Ingredient = apps.get_model("menu", "Ingredient")

    ingredient = Ingredient.objects.filter(
        name__icontains="Цезарь",
    ).first()

    if ingredient is None:
        return

    allergens = Allergen.objects.filter(
        code__in=[
            "egg",
            "milk",
            "mustard",
        ],
    )

    ingredient.allergens.add(*allergens)


def unlink_caesar_sauce_allergens(apps, schema_editor):
    Allergen = apps.get_model("menu", "Allergen")
    Ingredient = apps.get_model("menu", "Ingredient")

    ingredient = Ingredient.objects.filter(
        name__icontains="Цезарь",
    ).first()

    if ingredient is None:
        return

    allergens = Allergen.objects.filter(
        code__in=[
            "egg",
            "milk",
            "mustard",
        ],
    )

    ingredient.allergens.remove(*allergens)


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0004_adjust_hypatia_allergens"),
    ]

    operations = [
        migrations.RunPython(
            link_caesar_sauce_allergens,
            unlink_caesar_sauce_allergens,
        ),
    ]
