from urllib.parse import urlencode

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET

from orders.models import Restaurant
from orders.services import (
    CartValidationError,
    OrderingContext,
    get_table_context_ttl_seconds,
    get_table_for_ordering_context,
    resolve_ordering_context,
)

from .models import Category, Dish
from .services import (
    add_allergy_conflicts_to_dishes,
    build_dish_detail_payload,
    get_confirmed_user_allergens,
)
from .translations import localized_category_html


def build_cart_storage_scope(*, restaurant, table):
    context_value = f"{restaurant.pk}:{table.pk}:{table.qr_token_version}"
    return salted_hmac(
        "menu.cart-storage-scope",
        context_value,
        algorithm="sha256",
    ).hexdigest()[:24]


def get_menu_restaurant(request):
    slug = request.GET.get("restaurant") or request.GET.get("restaurant_slug")

    if slug:
        restaurant = Restaurant.objects.filter(
            slug=str(slug).strip(),
            is_active=True,
        ).first()

        if restaurant is None:
            raise Http404("Ресторан не найден.")

        return restaurant

    restaurant = Restaurant.objects.filter(is_active=True).order_by("id").first()

    if restaurant is None:
        raise Http404("В системе не настроен активный ресторан.")

    return restaurant


def _menu_dish_queryset(restaurant):
    return (
        Dish.objects.filter(
            restaurant=restaurant,
            is_active=True,
            is_available=True,
        )
        .select_related("category")
        .prefetch_related(
            "translations",
            "category__translations",
            "dish_ingredients__ingredient",
            "allergen_links__allergen",
            "allergen_links__allergen__translations",
        )
    )


def _set_private_table_headers(response):
    response["Cache-Control"] = "no-store, private"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _catalog_url(restaurant=None, *, table_context_error=""):
    query = {}

    if restaurant is not None and restaurant.slug:
        query["restaurant"] = restaurant.slug

    if table_context_error:
        query["table_context_error"] = table_context_error

    url = reverse("menu:dish_list")
    return f"{url}?{urlencode(query)}" if query else url


@require_GET
def table_menu_entry(request, qr_token):
    try:
        ordering_context = resolve_ordering_context({"table_token": qr_token})
    except CartValidationError as error:
        if error.status == 404:
            raise Http404(error.message)

        return _set_private_table_headers(
            HttpResponse(error.message, status=error.status)
        )

    response = redirect(
        "menu:table_context_menu",
        table_context=ordering_context.table_context,
    )
    return _set_private_table_headers(response)


@ensure_csrf_cookie
def dish_list(request, table_context=None):
    current_table_number = None
    cart_table_context = ""
    cart_order_source = ""
    cart_storage_scope = ""
    table_context_activation_url = ""
    ordering_enabled = False
    clear_table_context = bool(request.GET.get("table_context_error"))

    if table_context:
        try:
            ordering_context = resolve_ordering_context(
                {"table_context": table_context}
            )
            table = get_table_for_ordering_context(ordering_context)
        except CartValidationError as error:
            return _set_private_table_headers(
                redirect(
                    _catalog_url(table_context_error=error.code)
                )
            )

        restaurant = table.restaurant
        current_table_number = table.number
        cart_table_context = ordering_context.table_context or ""
        cart_order_source = "qr"
        cart_storage_scope = build_cart_storage_scope(
            restaurant=restaurant,
            table=table,
        )
        table_context_activation_url = reverse(
            "menu:table_context_menu",
            args=[cart_table_context],
        )
        ordering_enabled = True
    else:
        restaurant = get_menu_restaurant(request)
        ordering_context = OrderingContext(
            restaurant_id=restaurant.id,
            table_id=None,
            source="menu",
        )

    dishes = _menu_dish_queryset(restaurant).order_by(
        "category__name",
        "name",
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
    categories = (
        Category.objects.filter(
            restaurant=restaurant,
            id__in=category_ids,
        )
        .prefetch_related("translations")
        .order_by("name")
    )
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
        "menu_sections": menu_sections,
        "restaurant": restaurant,
        "cart_restaurant": restaurant,
        "cart_table_context": cart_table_context,
        "cart_order_source": cart_order_source,
        "cart_storage_scope": cart_storage_scope,
        "ordering_enabled": ordering_enabled,
        "cart_disabled": not ordering_enabled,
        "ordering_context": ordering_context,
        "user_allergens": get_confirmed_user_allergens(request.user),
        "current_table_number": current_table_number,
        "table_context_activation_url": table_context_activation_url,
        "table_context_clean_url": _catalog_url(restaurant),
        "table_context_ttl_seconds": get_table_context_ttl_seconds(),
        "menu_home_url": table_context_activation_url or _catalog_url(restaurant),
        "clear_table_context": clear_table_context,
    }

    response = render(
        request,
        "menu/dish_list.html",
        context,
    )

    if ordering_enabled:
        _set_private_table_headers(response)

    return response

@require_GET
def dish_detail(request, restaurant_slug, dish_id):
    restaurant = get_object_or_404(
        Restaurant,
        slug=restaurant_slug,
        is_active=True,
    )
    dish = get_object_or_404(
        _menu_dish_queryset(restaurant),
        pk=dish_id,
    )
    prepared_dish = add_allergy_conflicts_to_dishes(
        dishes=[dish],
        user=request.user,
    )[0]
    payload = build_dish_detail_payload([prepared_dish])[
        f"dish-{prepared_dish.id}"
    ]
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    return response

