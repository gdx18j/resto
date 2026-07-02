from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from orders.models import Restaurant
from orders.services import CartValidationError, OrderingContext, get_table_for_qr_token

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
    cart_table_token = None

    if qr_token:
        try:
            table = get_table_for_qr_token(qr_token)
        except CartValidationError as error:
            if error.status == 404:
                raise Http404(error.message)

            return HttpResponse(error.message, status=error.status)

        request.session["table_id"] = table.id
        request.session["table_number"] = table.number
        request.session["table_token"] = qr_token
        request.session["restaurant_id"] = table.restaurant_id
        restaurant = table.restaurant
        current_table_number = table.number
        cart_table_token = qr_token
        ordering_context = OrderingContext(
            restaurant_id=restaurant.id,
            table_id=table.id,
            table_token=qr_token,
            source="qr",
        )
    else:
        request.session.pop("table_id", None)
        request.session.pop("table_number", None)
        request.session.pop("table_token", None)
        request.session.pop("restaurant_id", None)
        restaurant = get_menu_restaurant(request)
        ordering_context = OrderingContext(
            restaurant_id=restaurant.id,
            table_id=None,
            table_token=None,
            source="menu",
        )

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
            "allergen_links__allergen",
            "allergen_links__allergen__translations",
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
        "cart_restaurant": restaurant,
        "cart_table_token": cart_table_token,
        "ordering_context": ordering_context,
        "user_allergens": get_confirmed_user_allergens(request.user),
        "current_table_number": current_table_number,
    }

    return render(
        request,
        "menu/dish_list.html",
        context,
    )
