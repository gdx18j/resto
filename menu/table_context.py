from urllib.parse import urlencode

from django.urls import reverse
from django.utils.crypto import salted_hmac

from orders.services import (
    CartValidationError,
    get_table_context_ttl_seconds,
    get_table_for_ordering_context,
    resolve_ordering_context,
)

TABLE_CONTEXT_SESSION_KEY = "cc_table_context:v1"


def build_cart_storage_scope(*, restaurant, table):
    context_value = f"{restaurant.pk}:{table.pk}:{table.qr_token_version}"
    return salted_hmac(
        "menu.cart-storage-scope",
        context_value,
        algorithm="sha256",
    ).hexdigest()[:24]


def build_catalog_url(restaurant=None, *, table_context_error=""):
    query = {}

    if restaurant is not None and restaurant.slug:
        query["restaurant"] = restaurant.slug

    if table_context_error:
        query["table_context_error"] = table_context_error

    url = reverse("menu:dish_list")
    return f"{url}?{urlencode(query)}" if query else url


def remember_table_context(request, table_context):
    table_context = str(table_context or "").strip()

    if not table_context:
        return

    request.session[TABLE_CONTEXT_SESSION_KEY] = table_context
    request.session.modified = True


def forget_table_context(request):
    if TABLE_CONTEXT_SESSION_KEY in request.session:
        request.session.pop(TABLE_CONTEXT_SESSION_KEY, None)
        request.session.modified = True


def resolve_remembered_table_context(request):
    table_context = str(request.session.get(TABLE_CONTEXT_SESSION_KEY) or "").strip()

    if not table_context:
        return None

    try:
        ordering_context = resolve_ordering_context({"table_context": table_context})
        table = get_table_for_ordering_context(ordering_context)
    except CartValidationError:
        forget_table_context(request)
        return None

    return ordering_context, table


def table_context_template_values(ordering_context, table):
    activation_url = reverse(
        "menu:table_context_menu",
        args=[ordering_context.table_context],
    )
    restaurant = table.restaurant

    return {
        "cart_restaurant": restaurant,
        "cart_table_context": ordering_context.table_context or "",
        "cart_order_source": "qr",
        "cart_storage_scope": build_cart_storage_scope(
            restaurant=restaurant,
            table=table,
        ),
        "current_table_number": table.number,
        "table_context_activation_url": activation_url,
        "table_context_clean_url": build_catalog_url(restaurant),
        "table_context_ttl_seconds": get_table_context_ttl_seconds(),
        "menu_home_url": activation_url,
    }
