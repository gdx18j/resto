from django.db import migrations


INGREDIENT_ALLERGEN_RULES = [
    ("milk", ("молоко", "сыр", "сливоч", "крем", "латте", "капучино", "мокка", "шоколад", "пудинг", "чизкейк", "десерт hypatia", "цезарь", "соус цезарь", "пармезан")),
    ("gluten", ("глютен", "хлеб", "чиабатта", "мука", "бисквит", "печенье", "oreo", "кекс", "чизкейк", "lotus")),
    ("egg", ("яйц", "майонез", "цезарь", "соус цезарь", "бисквит", "кекс", "чизкейк")),
    ("mustard", ("горчиц", "майонез", "цезарь", "соус цезарь")),
    ("tree-nuts", ("орех", "песто")),
    ("soy", ("соя", "шоколад", "lotus", "десерт hypatia")),
    ("sulfites", ("сульфит", "бальзам", "вяленые томаты")),
    ("peanut", ("арахис",)),
    ("fish", ("рыба", "тунец", "лосось", "анчоус")),
    ("shellfish", ("кревет", "моллюск", "краб", "ракообраз")),
    ("sesame", ("кунжут", "тахини")),
    ("celery", ("сельдерей",)),
]


def normalize(value):
    return (value or "").strip().lower().replace("ё", "е")


def link_common_ingredient_allergens(apps, schema_editor):
    Allergen = apps.get_model("menu", "Allergen")
    Ingredient = apps.get_model("menu", "Ingredient")

    allergens_by_code = {
        allergen.code: allergen
        for allergen in Allergen.objects.all()
    }

    for ingredient in Ingredient.objects.all():
        normalized_name = normalize(ingredient.name)
        matched_allergens = [
            allergens_by_code[code]
            for code, keywords in INGREDIENT_ALLERGEN_RULES
            if code in allergens_by_code
            and any(keyword in normalized_name for keyword in keywords)
        ]

        if matched_allergens:
            ingredient.allergens.add(*matched_allergens)


def unlink_common_ingredient_allergens(apps, schema_editor):
    Allergen = apps.get_model("menu", "Allergen")
    Ingredient = apps.get_model("menu", "Ingredient")

    allergen_ids = list(
        Allergen.objects.filter(
            code__in=[code for code, _keywords in INGREDIENT_ALLERGEN_RULES],
        ).values_list("id", flat=True)
    )

    if allergen_ids:
        for ingredient in Ingredient.objects.all():
            ingredient.allergens.remove(*allergen_ids)


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0002_seed_common_allergens"),
    ]

    operations = [
        migrations.RunPython(
            link_common_ingredient_allergens,
            unlink_common_ingredient_allergens,
        ),
    ]
