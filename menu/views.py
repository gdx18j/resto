from django.shortcuts import render

from .models import Category, Dish
from .services import (
    add_allergy_conflicts_to_dishes,
    get_confirmed_user_allergens,
)


def dish_list(request):
    dishes = (
        Dish.objects.filter(
            is_active=True,
            is_available=True,
        )
        .select_related("category")
        .prefetch_related(
            "ingredients__allergens",
            "may_contain_allergens",
        )
        .order_by("category__name", "name")
    )

    dishes = add_allergy_conflicts_to_dishes(
        dishes=dishes,
        user=request.user,
    )

    category_ids = {
        dish.category_id
        for dish in dishes
        if dish.category_id is not None
    }
    categories = Category.objects.filter(id__in=category_ids).order_by("name")
    dishes_by_category = {
        category.id: []
        for category in categories
    }
    uncategorized_dishes = []

    for dish in dishes:
        if dish.category_id in dishes_by_category:
            dishes_by_category[dish.category_id].append(dish)
        else:
            uncategorized_dishes.append(dish)

    menu_sections = [
        {
            "anchor": f"category-{category.id}",
            "title": category.name,
            "dishes": dishes_by_category[category.id],
        }
        for category in categories
    ]

    if uncategorized_dishes:
        menu_sections.append(
            {
                "anchor": "other",
                "title": "Другое",
                "dishes": uncategorized_dishes,
            }
        )

    context = {
        "dishes": dishes,
        "menu_sections": menu_sections,
        "user_allergens": get_confirmed_user_allergens(request.user),
    }

    return render(
        request,
        "menu/dish_list.html",
        context,
    )
