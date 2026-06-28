from django.db import migrations


def adjust_hypatia_allergens(apps, schema_editor):
    Allergen = apps.get_model("menu", "Allergen")
    Ingredient = apps.get_model("menu", "Ingredient")

    ingredient = Ingredient.objects.filter(
        name__iexact="Десерт Hypatia",
    ).first()

    if ingredient is None:
        return

    milk = Allergen.objects.filter(code="milk").first()
    soy = Allergen.objects.filter(code="soy").first()
    gluten = Allergen.objects.filter(code="gluten").first()

    if gluten is not None:
        ingredient.allergens.remove(gluten)

    ingredient.allergens.add(
        *[
            allergen
            for allergen in (milk, soy)
            if allergen is not None
        ]
    )


def reverse_adjust_hypatia_allergens(apps, schema_editor):
    Allergen = apps.get_model("menu", "Allergen")
    Ingredient = apps.get_model("menu", "Ingredient")

    ingredient = Ingredient.objects.filter(
        name__iexact="Десерт Hypatia",
    ).first()

    if ingredient is None:
        return

    milk = Allergen.objects.filter(code="milk").first()
    gluten = Allergen.objects.filter(code="gluten").first()

    if milk is not None:
        ingredient.allergens.remove(milk)

    if gluten is not None:
        ingredient.allergens.add(gluten)


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0003_link_common_ingredient_allergens"),
    ]

    operations = [
        migrations.RunPython(
            adjust_hypatia_allergens,
            reverse_adjust_hypatia_allergens,
        ),
    ]
