from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie

from orders.models import Restaurant, Table

from .models import Category, Dish
from .services import (
    add_allergy_conflicts_to_dishes,
    build_dish_detail_payload,
    get_confirmed_user_allergens,
)
from .translations import localized_category_html


def get_menu_restaurant(request):
    slug = request.GET.get("restaurant") or request.GET.get("restaurant_slug")

    if slug:
        restaurant = Restaurant.objects.filter(
            slug=str(slug).strip(),
            is_active=True,
        ).first()

        if restaurant:
            return restaurant

    restaurant = Restaurant.objects.filter(is_active=True).order_by("id").first()

    if restaurant:
        return restaurant

    return Restaurant.objects.create(
        slug="caesar-company",
        name="Caesar & Company",
    )


@ensure_csrf_cookie
def dish_list(request, qr_token=None):
    current_table_number = None

    if qr_token:
        table = get_object_or_404(
            Table.objects.select_related("restaurant"),
            qr_token=qr_token,
            is_active=True,
            restaurant__is_active=True,
        )
        request.session["table_id"] = table.id
        request.session["table_number"] = table.number
        restaurant = table.restaurant
        current_table_number = table.number
    else:
        request.session.pop("table_id", None)
        request.session.pop("table_number", None)
        restaurant = get_menu_restaurant(request)

    dishes = (
        Dish.objects.filter(
            restaurant=restaurant,
            is_active=True,
            is_available=True,
        )
        .select_related("category")
        .prefetch_related(
            "translations",
            "category__translations",
            "ingredients__allergens",
            "ingredients__allergens__translations",
            "dish_ingredients__ingredient",
            "may_contain_allergens",
            "may_contain_allergens__translations",
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
    categories = Category.objects.filter(
        restaurant=restaurant,
        id__in=category_ids,
    ).order_by("name")
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
            "title_html": localized_category_html(category),
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
        "restaurant": restaurant,
        "user_allergens": get_confirmed_user_allergens(request.user),
        "current_table_number": current_table_number,
    }

    return render(
        request,
        "menu/dish_list.html",
        context,
    )
