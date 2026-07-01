from django.shortcuts import get_object_or_404, render

from tables.models import Table

from .models import Category, Dish
from .services import (
    add_allergy_conflicts_to_dishes,
    get_confirmed_user_allergens,
)
from .translations import localized_category_html


def dish_list(request, qr_token=None):
    if qr_token:
        # Открыто по QR стола — запоминаем стол в сессии
        table = get_object_or_404(Table, qr_token=qr_token, is_active=True)
        request.session["table_id"] = table.id
        request.session["table_number"] = table.number
    else:
        # Обычный переход на главную (логотип, прямой URL) — сбрасываем стол
        request.session.pop("table_id", None)
        request.session.pop("table_number", None)

    current_table_number = request.session.get("table_number")

    dishes = (
        Dish.objects.filter(
            is_active=True,
            is_available=True,
        )
        .select_related("category")
        .prefetch_related(
            "ingredients__allergens",
            "dish_ingredients__ingredient",
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
            "title_html": localized_category_html(category.name),
            "dishes": dishes_by_category[category.id],
        }
        for category in categories
    ]

    if uncategorized_dishes:
        menu_sections.append(
            {
                "anchor": "other",
                "title": "Другое",
                "title_html": localized_category_html("Другое"),
                "dishes": uncategorized_dishes,
            }
        )

    context = {
        "dishes": dishes,
        "menu_sections": menu_sections,
        "user_allergens": get_confirmed_user_allergens(request.user),
        "current_table_number": current_table_number,
    }

    return render(
        request,
        "menu/dish_list.html",
        context,
    )