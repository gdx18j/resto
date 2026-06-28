ALLERGEN_NAME_TO_CODE = {
    "молоко": "milk",
    "глютен": "gluten",
    "яйца": "egg",
    "горчица": "mustard",
    "орехи": "tree-nuts",
    "соя": "soy",
    "сульфиты": "sulfites",
    "арахис": "peanut",
    "рыба": "fish",
    "кунжут": "sesame",
    "сельдерей": "celery",
}


INGREDIENT_ALLERGEN_RULES = [
    (
        "milk",
        (
            "молоко",
            "сыр",
            "сливоч",
            "крем",
            "латте",
            "капучино",
            "мокка",
            "шоколад",
            "пудинг",
            "чизкейк",
            "десерт hypatia",
            "цезарь",
            "соус цезарь",
            "пармезан",
        ),
    ),
    (
        "gluten",
        (
            "глютен",
            "хлеб",
            "чиабатта",
            "мука",
            "бисквит",
            "печенье",
            "oreo",
            "кекс",
            "чизкейк",
            "lotus",
        ),
    ),
    (
        "egg",
        (
            "яйц",
            "майонез",
            "цезарь",
            "соус цезарь",
            "бисквит",
            "кекс",
            "чизкейк",
        ),
    ),
    (
        "mustard",
        (
            "горчиц",
            "майонез",
            "цезарь",
            "соус цезарь",
        ),
    ),
    (
        "tree-nuts",
        (
            "орех",
            "песто",
        ),
    ),
    (
        "soy",
        (
            "соя",
            "шоколад",
            "lotus",
            "десерт hypatia",
        ),
    ),
    (
        "sulfites",
        (
            "сульфит",
            "бальзам",
            "вяленые томаты",
        ),
    ),
    (
        "peanut",
        (
            "арахис",
        ),
    ),
    (
        "fish",
        (
            "рыба",
            "тунец",
            "лосось",
            "анчоус",
        ),
    ),
    (
        "shellfish",
        (
            "кревет",
            "моллюск",
            "краб",
            "ракообраз",
        ),
    ),
    (
        "sesame",
        (
            "кунжут",
            "тахини",
        ),
    ),
    (
        "celery",
        (
            "сельдерей",
        ),
    ),
]


def normalize_allergen_text(value):
    return (value or "").strip().lower().replace("ё", "е")


def get_allergen_codes_for_ingredient(ingredient_name):
    normalized_name = normalize_allergen_text(ingredient_name)

    return {
        code
        for code, keywords in INGREDIENT_ALLERGEN_RULES
        if any(keyword in normalized_name for keyword in keywords)
    }
