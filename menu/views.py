from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import Category, Dish
from .services import (
    add_allergy_conflicts_to_dishes,
    build_dish_detail_payload,
    get_confirmed_user_allergens,
)
from .translations import localized_category_html


@ensure_csrf_cookie
def dish_list(request):
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
        "dish_details": build_dish_detail_payload(dishes),
        "menu_sections": menu_sections,
        "user_allergens": get_confirmed_user_allergens(request.user),
    }

    return render(
        request,
        "menu/dish_list.html",
        context,
    )


@staff_member_required
@require_POST
def hide_dish(request, dish_id):
    dish = get_object_or_404(Dish, id=dish_id)

    if dish.is_active:
        dish.is_active = False
        dish.save(update_fields=["is_active"])

    return JsonResponse(
        {
            "ok": True,
            "dish_id": dish.id,
            "message": "Блюдо убрано из меню.",
        }
    )
