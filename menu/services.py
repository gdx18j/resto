from accounts.models import UserAllergy


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

    return list(
        UserAllergy.objects.filter(
            user=user,
            status=UserAllergy.Status.CONFIRMED,
        )
        .select_related("allergen")
        .order_by("allergen__name")
    )


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
            dish_allergens[allergen.id] = allergen

        for ingredient in ingredients:
            ingredient_names.append(ingredient.name)

            for allergen in ingredient.allergens.all():
                dish_allergens[allergen.id] = allergen

        dish.display_allergens = sorted(
            dish_allergens.values(),
            key=lambda allergen: allergen.name.lower(),
        )
        dish.search_name = dish.name
        dish.search_ingredients = ", ".join(ingredient_names)
        dish.search_text = " ".join(
            value
            for value in [
                dish.name,
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
