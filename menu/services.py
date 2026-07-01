from accounts.models import UserAllergy

from .translations import (
    LANGUAGES,
    localized_allergen_html,
    localized_allergen_values,
    localized_dish_html,
    localized_dish_values,
)


def _decimal_display(value):
    if value is None:
        return None

    return f"{value:g}"


def _dish_image_url(dish):
    if not dish.image:
        return ""

    try:
        return dish.image.url
    except ValueError:
        return ""


def build_dish_detail_payload(dishes):
    details = {}

    for dish in dishes:
        details[f"dish-{dish.id}"] = {
            "id": dish.id,
            "cart_id": f"dish-{dish.id}",
            "title_id": f"dish-detail-title-{dish.id}",
            "name": dish.name,
            "names": dish.name_translations,
            "descriptions": dish.description_translations,
            "has_description": dish.has_description,
            "image_url": _dish_image_url(dish),
            "placeholder": dish.name[:1],
            "price": _decimal_display(dish.price),
            "serving_weight_g": dish.serving_weight_g,
            "preparation_time_minutes": dish.preparation_time_minutes,
            "calories_kcal_per_serving": dish.calories_kcal_per_serving,
            "nutrition": {
                "proteins_g": _decimal_display(dish.nutrition.get("proteins_g")),
                "fats_g": _decimal_display(dish.nutrition.get("fats_g")),
                "carbohydrates_g": _decimal_display(dish.nutrition.get("carbohydrates_g")),
                "is_estimated": dish.nutrition.get("is_estimated", False),
            },
            "ingredients": dish.display_ingredients,
            "has_more_ingredients": dish.has_more_ingredients,
            "allergens": [
                localized_allergen_values(allergen)
                for allergen in dish.display_allergens
            ],
        }

    return details


def get_confirmed_user_allergen_ids(user):
    """
    Возвращает ID подтверждённых аллергенов пользователя.

    Для неавторизованного пользователя возвращает пустое множество.
    """

    if not user.is_authenticated:
        return set()

    return set(
        UserAllergy.objects.filter(
            user=user,
            status=UserAllergy.Status.CONFIRMED,
        ).values_list(
            "allergen_id",
            flat=True,
        )
    )


def get_confirmed_user_allergens(user):
    """
    Возвращает подтверждённые аллергены пользователя для отображения в меню.
    """

    if not user.is_authenticated:
        return []

    records = list(
        UserAllergy.objects.filter(
            user=user,
            status=UserAllergy.Status.CONFIRMED,
        )
        .select_related("allergen")
        .order_by("allergen__name")
    )

    for record in records:
        record.allergen.localized_name_html = localized_allergen_html(
            record.allergen
        )

    return records


def _localized_search_blob(*translation_sets):
    values = []

    for translations in translation_sets:
        for language in LANGUAGES:
            value = translations.get(language, "")

            if value:
                values.append(value)

    return " ".join(values)


def _contains_any(value, words):
    return any(word in value for word in words)


def _estimated_nutrition_for_dish(dish, ingredient_names):
    category = (dish.category.name if dish.category else "").lower()
    name = dish.name.lower()
    text = " ".join([category, name, " ".join(ingredient_names).lower()])

    if _contains_any(text, ["напит", "кофе", "coffee", "americano", "limonata", "лимонад", "latte", "матча", "matcha", "чай"]):
        if _contains_any(text, ["americano", "эспрессо", "espresso", "фильтр"]):
            return {
                "serving_weight_g": 250,
                "calories": 5,
                "proteins_g": 0,
                "fats_g": 0,
                "carbohydrates_g": 1,
            }

        if _contains_any(text, ["latte", "латте", "matcha", "матча", "молоко"]):
            return {
                "serving_weight_g": 330,
                "calories": 180,
                "proteins_g": 7,
                "fats_g": 6,
                "carbohydrates_g": 24,
            }

        return {
            "serving_weight_g": 330,
            "calories": 135,
            "proteins_g": 0,
            "fats_g": 0,
            "carbohydrates_g": 32,
        }

    if _contains_any(category, ["десерт"]):
        return {
            "serving_weight_g": 145,
            "calories": 390,
            "proteins_g": 6,
            "fats_g": 21,
            "carbohydrates_g": 46,
        }

    if _contains_any(text, ["салат", "salata"]):
        return {
            "serving_weight_g": 360,
            "calories": 430,
            "proteins_g": 27,
            "fats_g": 25,
            "carbohydrates_g": 22,
        }

    if _contains_any(category, ["тост"]):
        return {
            "serving_weight_g": 220,
            "calories": 420,
            "proteins_g": 18,
            "fats_g": 20,
            "carbohydrates_g": 42,
        }

    if _contains_any(category, ["сэндвич"]):
        return {
            "serving_weight_g": 320,
            "calories": 560,
            "proteins_g": 26,
            "fats_g": 24,
            "carbohydrates_g": 60,
        }

    if _contains_any(category, ["акционные", "меню"]):
        return {
            "serving_weight_g": 520,
            "calories": 720,
            "proteins_g": 32,
            "fats_g": 30,
            "carbohydrates_g": 82,
        }

    return {
        "serving_weight_g": 300,
        "calories": 460,
        "proteins_g": 18,
        "fats_g": 20,
        "carbohydrates_g": 48,
    }


def _nutrition_for_dish(dish, ingredient_names):
    estimated = _estimated_nutrition_for_dish(dish, ingredient_names)
    values = {
        "serving_weight_g": dish.serving_weight_g or estimated["serving_weight_g"],
        "calories": dish.calories_kcal_per_serving or estimated["calories"],
        "proteins_g": (
            dish.proteins_g_per_serving
            if dish.proteins_g_per_serving is not None
            else estimated["proteins_g"]
        ),
        "fats_g": (
            dish.fats_g_per_serving
            if dish.fats_g_per_serving is not None
            else estimated["fats_g"]
        ),
        "carbohydrates_g": (
            dish.carbohydrates_g_per_serving
            if dish.carbohydrates_g_per_serving is not None
            else estimated["carbohydrates_g"]
        ),
    }
    values["is_estimated"] = any(
        value is None
        for value in [
            dish.serving_weight_g,
            dish.calories_kcal_per_serving,
            dish.proteins_g_per_serving,
            dish.fats_g_per_serving,
            dish.carbohydrates_g_per_serving,
        ]
    )
    return values


def add_allergy_conflicts_to_dishes(dishes, user):
    """
    Проверяет каждое блюдо и добавляет ему временные атрибуты:

    dish.display_allergens — список аллергенов блюда;
    dish.display_ingredients — короткий список ингредиентов для карточки;
    dish.search_* — данные для клиентского поиска;
    dish.conflicting_allergens — список найденных аллергенов пользователя;
    dish.has_allergy_conflict — есть ли конфликт.
    """

    dishes = list(dishes)
    user_allergen_ids = get_confirmed_user_allergen_ids(user)

    for dish in dishes:
        dish_allergens = {}
        ingredients = list(dish.ingredients.all())
        ingredient_names = []
        display_ingredient_names = []

        for dish_ingredient in dish.dish_ingredients.all():
            ingredient = dish_ingredient.ingredient

            if ingredient and ingredient.is_active:
                display_ingredient_names.append(ingredient.name)

        for allergen in dish.may_contain_allergens.all():
            allergen.localized_name_html = localized_allergen_html(allergen)
            dish_allergens[allergen.id] = allergen

        for ingredient in ingredients:
            ingredient_names.append(ingredient.name)

            for allergen in ingredient.allergens.all():
                allergen.localized_name_html = localized_allergen_html(allergen)
                dish_allergens[allergen.id] = allergen

        dish.display_allergens = sorted(
            dish_allergens.values(),
            key=lambda allergen: allergen.name.lower(),
        )
        if not display_ingredient_names:
            display_ingredient_names = ingredient_names

        dish.display_ingredients = display_ingredient_names[:8]
        dish.has_more_ingredients = len(display_ingredient_names) > 8
        dish.nutrition = _nutrition_for_dish(dish, ingredient_names)
        dish.has_nutrition_details = bool(dish.nutrition)
        dish.localized_name_html = localized_dish_html(dish, "name")
        dish.localized_description_html = localized_dish_html(
            dish,
            "description",
        )
        dish.name_translations = localized_dish_values(dish, "name")
        dish.description_translations = localized_dish_values(
            dish,
            "description",
        )
        dish.has_description = any(
            value.strip()
            for value in dish.description_translations.values()
        )
        allergen_search_values = {
            language: " ".join(
                localized_allergen_values(allergen)[language]
                for allergen in dish.display_allergens
            )
            for language in LANGUAGES
        }
        dish.search_name = _localized_search_blob(dish.name_translations)
        dish.search_ingredients = ", ".join(ingredient_names)
        dish.search_text = " ".join(
            value
            for value in [
                _localized_search_blob(
                    dish.name_translations,
                    dish.description_translations,
                    allergen_search_values,
                ),
                " ".join(ingredient_names),
            ]
            if value
        )
        dish.conflicting_allergens = [
            allergen
            for allergen_id, allergen in dish_allergens.items()
            if allergen_id in user_allergen_ids
        ]
        dish.has_allergy_conflict = bool(dish.conflicting_allergens)

    return dishes
