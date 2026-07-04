from accounts.models import UserAllergy

from .models import DishAllergen
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
            "allergen_groups": dish.display_allergen_groups,
            "allergen_data_status": dish.allergen_data_status,
            "allergen_data_complete": dish.allergen_data_complete,
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
        .prefetch_related("allergen__translations")
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


def build_menu_search_index(dishes):
    """
    Возвращает компактный поисковый индекс для клиентского меню.

    Формат строки намеренно позиционный, чтобы не повторять имена JSON-полей
    для каждого блюда:

    [dish_id, name_ru, name_en, name_tr, ingredients, extra_text]

    ``extra_text`` содержит описания и проверенные аллергены. Полный текст,
    использовавшийся старым DOM-индексом, восстанавливается в браузере как
    ``names + extra_text + ingredients`` без потери поисковых данных.
    """

    return [
        [
            dish.id,
            dish.name_translations["ru"],
            dish.name_translations["en"],
            dish.name_translations["tr"],
            dish.search_ingredients,
            dish.search_extra,
        ]
        for dish in dishes
    ]


def _contains_any(value, words):
    return any(word in value for word in words)


def _new_allergen_group():
    return {
        "contains": {},
        "traces": {},
        "unknown": {},
    }


def _allergen_group_for_relation(relation_type):
    if relation_type == DishAllergen.RelationType.CONTAINS:
        return "contains"

    if relation_type in {
        DishAllergen.RelationType.MAY_CONTAIN,
        DishAllergen.RelationType.CROSS_CONTAMINATION,
    }:
        return "traces"

    return "unknown"


def _add_grouped_allergen(groups, allergen, group):
    allergen.localized_name_html = localized_allergen_html(allergen)
    groups[group][allergen.id] = allergen


def _dish_allergen_groups(dish):
    groups = _new_allergen_group()
    selected_links = {}
    status_priority = {
        DishAllergen.VerificationStatus.VERIFIED: 2,
        DishAllergen.VerificationStatus.SUGGESTED: 1,
    }
    relation_priority = {
        DishAllergen.RelationType.CONTAINS: 3,
        DishAllergen.RelationType.CROSS_CONTAMINATION: 2,
        DishAllergen.RelationType.MAY_CONTAIN: 1,
    }

    for link in dish.allergen_links.all():
        if link.verification_status == DishAllergen.VerificationStatus.REJECTED:
            continue

        candidate_priority = (
            status_priority.get(link.verification_status, 0),
            relation_priority.get(link.relation_type, 0),
        )
        current = selected_links.get(link.allergen_id)

        if current is None or candidate_priority > current[0]:
            selected_links[link.allergen_id] = (candidate_priority, link)

    for _priority, link in selected_links.values():
        group = _allergen_group_for_relation(link.relation_type)

        if (
            link.verification_status
            != DishAllergen.VerificationStatus.VERIFIED
            or link.reviewed_recipe_revision != dish.recipe_revision
        ):
            group = "unknown"

        _add_grouped_allergen(groups, link.allergen, group)

    return groups


def _flatten_grouped_allergens(groups):
    flattened = {}

    for group in ("contains", "traces", "unknown"):
        flattened.update(groups[group])

    return sorted(
        flattened.values(),
        key=lambda allergen: allergen.name.lower(),
    )


def _localized_allergen_group_values(groups):
    return {
        group: [
            localized_allergen_values(allergen)
            for allergen in sorted(
                allergens.values(),
                key=lambda value: value.name.lower(),
            )
        ]
        for group, allergens in groups.items()
        if allergens
    }


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


def add_allergy_conflicts_to_dishes(
    dishes,
    user,
    *,
    user_allergen_ids=None,
):
    """
    Проверяет каждое блюдо и добавляет ему временные атрибуты:

    dish.display_allergens — список аллергенов блюда;
    dish.display_ingredients — короткий список ингредиентов для карточки;
    dish.search_* — данные для клиентского поиска;
    dish.conflicting_allergens — список найденных аллергенов пользователя;
    dish.has_allergy_conflict — есть ли конфликт.
    """

    dishes = list(dishes)
    if user_allergen_ids is None:
        user_allergen_ids = get_confirmed_user_allergen_ids(user)
    else:
        user_allergen_ids = set(user_allergen_ids)

    for dish in dishes:
        allergen_groups = _dish_allergen_groups(dish)
        dish_ingredients = list(dish.dish_ingredients.all())
        ingredients = [
            dish_ingredient.ingredient
            for dish_ingredient in dish_ingredients
            if dish_ingredient.ingredient is not None
        ]
        ingredient_names = []
        display_ingredient_names = []

        for dish_ingredient in dish_ingredients:
            ingredient = dish_ingredient.ingredient

            if ingredient and ingredient.is_active:
                display_ingredient_names.append(ingredient.name)

        for ingredient in ingredients:
            ingredient_names.append(ingredient.name)

        dish.display_allergens = _flatten_grouped_allergens(allergen_groups)
        dish.display_allergen_groups = _localized_allergen_group_values(
            allergen_groups
        )
        dish.allergen_data_status = dish.public_allergen_data_status
        dish.allergen_data_complete = dish.is_allergen_review_complete
        verified_allergens = _flatten_grouped_allergens(
            {
                "contains": allergen_groups["contains"],
                "traces": allergen_groups["traces"],
                "unknown": {},
            }
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
                for allergen in verified_allergens
            )
            for language in LANGUAGES
        }
        dish.search_ingredients = ", ".join(ingredient_names)
        dish.search_extra = _localized_search_blob(
            dish.description_translations,
            allergen_search_values,
        )
        dish.conflicting_allergens = _flatten_grouped_allergens(
            {
                "contains": {
                    allergen_id: allergen
                    for allergen_id, allergen
                    in allergen_groups["contains"].items()
                    if allergen_id in user_allergen_ids
                },
                "traces": {
                    allergen_id: allergen
                    for allergen_id, allergen
                    in allergen_groups["traces"].items()
                    if allergen_id in user_allergen_ids
                },
                "unknown": {},
            }
        )
        dish.has_allergy_conflict = bool(dish.conflicting_allergens)

    return dishes
