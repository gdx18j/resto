from django.db import migrations


COMMON_ALLERGENS = [
    ("gluten", "Глютен"),
    ("milk", "Молоко"),
    ("egg", "Яйца"),
    ("peanut", "Арахис"),
    ("tree-nuts", "Орехи"),
    ("fish", "Рыба"),
    ("shellfish", "Моллюски и ракообразные"),
    ("soy", "Соя"),
    ("sesame", "Кунжут"),
    ("mustard", "Горчица"),
    ("celery", "Сельдерей"),
    ("lupin", "Люпин"),
    ("sulfites", "Сульфиты"),
    ("honey", "Мед"),
]


def seed_common_allergens(apps, schema_editor):
    Allergen = apps.get_model("menu", "Allergen")

    for code, name in COMMON_ALLERGENS:
        code_match = Allergen.objects.filter(code=code).first()
        name_match = Allergen.objects.filter(name=name).first()

        if code_match and name_match and code_match.pk != name_match.pk:
            continue

        allergen = code_match or name_match

        if allergen is None:
            Allergen.objects.create(
                code=code,
                name=name,
            )
        else:
            allergen.code = code
            allergen.name = name
            allergen.save(
                update_fields=[
                    "code",
                    "name",
                ]
            )


def remove_common_allergens(apps, schema_editor):
    Allergen = apps.get_model("menu", "Allergen")
    Allergen.objects.filter(
        code__in=[code for code, _name in COMMON_ALLERGENS],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            seed_common_allergens,
            remove_common_allergens,
        ),
    ]
