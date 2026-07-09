import json
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
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

from .models import (
    AllergenTranslation,
    CategoryTranslation,
    Dish,
    DishAllergen,
    DishIngredient,
    DishTranslation,
    SeasonalDishFeature,
)
from .services import (
    add_allergy_conflicts_to_dishes,
    build_dish_detail_payload,
    build_menu_search_index,
    get_confirmed_user_allergens,
)
from .table_context import (
    build_cart_storage_scope,
    build_catalog_url,
    forget_table_context,
    remember_table_context,
)
from .translations import LANGUAGES, localized_category_html, localized_text_html


SEASONAL_DEFAULT_LABELS = {
    "ru": "Сезонная история",
    "en": "Seasonal story",
    "tr": "Mevsim hikayesi",
}
SEASONAL_DEFAULT_CTA = {
    "ru": "Открыть блюдо",
    "en": "Open dish",
    "tr": "Yemeği aç",
}


def _localized_feature_html(feature, field_prefix, fallback_values):
    return localized_text_html(
        {
            language: (
                getattr(feature, f"{field_prefix}_{language}", "").strip()
                or fallback_values.get(language, "")
            )
            for language in LANGUAGES
        }
    )


def _image_url(image_field):
    if not image_field:
        return ""

    try:
        return image_field.url
    except ValueError:
        return ""


def _seasonal_feature_queryset(restaurant):
    now = timezone.now()
    return (
        SeasonalDishFeature.objects.filter(
            restaurant=restaurant,
            is_active=True,
            dish__restaurant=restaurant,
            dish__is_active=True,
            dish__is_available=True,
        )
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .select_related("dish")
        .order_by("sort_order", "id")
    )


def _prepare_seasonal_features(restaurant, dishes):
    prepared_dishes = {dish.id: dish for dish in dishes}
    features = []

    for feature in _seasonal_feature_queryset(restaurant):
        dish = prepared_dishes.get(feature.dish_id)

        if dish is None:
            continue

        feature.dish = dish
        feature.label_html = _localized_feature_html(
            feature,
            "label",
            SEASONAL_DEFAULT_LABELS,
        )
        feature.title_html = _localized_feature_html(
            feature,
            "title",
            dish.name_translations,
        )
        feature.description_html = _localized_feature_html(
            feature,
            "description",
            dish.description_translations,
        )
        feature.has_description = any(
            getattr(feature, f"description_{language}", "").strip()
            or dish.description_translations.get(language, "").strip()
            for language in LANGUAGES
        )
        feature.cta_html = _localized_feature_html(
            feature,
            "cta",
            SEASONAL_DEFAULT_CTA,
        )
        feature.image_url = (
            _image_url(feature.image)
            or getattr(dish, "image_url", "")
            or _image_url(dish.image)
        )
        feature.placeholder = (dish.name or "C")[:1]
        features.append(feature)

    return features


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
            Prefetch(
                "translations",
                queryset=DishTranslation.objects.order_by("language"),
            ),
            Prefetch(
                "category__translations",
                queryset=CategoryTranslation.objects.order_by("language"),
            ),
            Prefetch(
                "dish_ingredients",
                queryset=(
                    DishIngredient.objects
                    .select_related("ingredient")
                    .order_by("id")
                ),
            ),
            Prefetch(
                "allergen_links",
                queryset=(
                    DishAllergen.objects
                    .select_related("allergen")
                    .prefetch_related(
                        Prefetch(
                            "allergen__translations",
                            queryset=(
                                AllergenTranslation.objects
                                .order_by("language")
                            ),
                        )
                    )
                    .order_by("id")
                ),
            ),
        )
    )


def _set_private_table_headers(response):
    response["Cache-Control"] = "no-store, private"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _catalog_url(restaurant=None, *, table_context_error=""):
    return build_catalog_url(
        restaurant,
        table_context_error=table_context_error,
    )


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
        remember_table_context(request, cart_table_context)
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
        # A plain catalog visit is an explicit switch back to non-table browsing.
        # QR/table ordering is preserved across account/history pages through
        # the remembered context, but the clean menu URL itself must not
        # silently inherit an old table from the same browser session.
        forget_table_context(request)
        clear_table_context = True
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

    user_allergens = get_confirmed_user_allergens(request.user)
    dishes = add_allergy_conflicts_to_dishes(
        dishes=dishes,
        user=request.user,
        user_allergen_ids={
            record.allergen_id
            for record in user_allergens
        },
    )

    categories_by_id = {}
    for dish in dishes:
        if dish.category_id is not None:
            categories_by_id.setdefault(dish.category_id, dish.category)

    categories = list(categories_by_id.values())
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

    seasonal_features = _prepare_seasonal_features(restaurant, dishes)

    context = {
        "menu_page": True,
        "dishes": dishes,
        "menu_sections": menu_sections,
        "seasonal_features": seasonal_features,
        "restaurant": restaurant,
        "cart_restaurant": restaurant,
        "cart_table_context": cart_table_context,
        "cart_order_source": cart_order_source,
        "cart_storage_scope": cart_storage_scope,
        "ordering_enabled": ordering_enabled,
        "cart_disabled": not ordering_enabled,
        "ordering_context": ordering_context,
        "user_allergens": user_allergens,
        "current_table_number": current_table_number,
        "table_context_activation_url": table_context_activation_url,
        "table_context_clean_url": _catalog_url(restaurant),
        "table_context_ttl_seconds": get_table_context_ttl_seconds(),
        "menu_home_url": table_context_activation_url or _catalog_url(restaurant),
        "clear_table_context": clear_table_context,
        "menu_search_index_json": json.dumps(
            build_menu_search_index(dishes),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
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
