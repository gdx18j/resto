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


def add_allergy_conflicts_to_dishes(dishes, user):
    """
    Проверяет каждое блюдо и добавляет ему временные атрибуты:

    dish.conflicting_allergens — список найденных аллергенов;
    dish.has_allergy_conflict — есть ли конфликт.
    """

    dishes = list(dishes)

    user_allergen_ids = get_confirmed_user_allergen_ids(user)

    for dish in dishes:
        dish_allergens = {}

        # Возможные следы аллергенов, указанные у самого блюда.
        for allergen in dish.may_contain_allergens.all():
            dish_allergens[allergen.id] = allergen

        # Аллергены, полученные через ингредиенты.
        for ingredient in dish.ingredients.all():
            for allergen in ingredient.allergens.all():
                dish_allergens[allergen.id] = allergen

        dish.conflicting_allergens = [
            allergen
            for allergen_id, allergen in dish_allergens.items()
            if allergen_id in user_allergen_ids
        ]

        dish.has_allergy_conflict = bool(
            dish.conflicting_allergens
        )

    return dishes