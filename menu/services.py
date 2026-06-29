from accounts.models import UserAllergy

from .translations import (
    LANGUAGES,
    localized_allergen_html,
    localized_allergen_values,
    localized_dish_html,
    localized_dish_values,
)


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


def add_allergy_conflicts_to_dishes(dishes, user):
    """
    Проверяет каждое блюдо и добавляет ему временные атрибуты:

    dish.display_allergens — список аллергенов блюда;
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
