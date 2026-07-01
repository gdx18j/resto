import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .models import Order
from .presentation import decorate_order, decorate_orders
from .services import (
    CartValidationError,
    create_order_from_payload,
    quote_cart,
)


def _json_payload(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise CartValidationError("Некорректный JSON.", code="invalid_json")


def _language(request):
    value = request.GET.get("language") or request.headers.get("X-Language") or "ru"
    return value if value in {"ru", "en", "tr"} else "ru"


def _error_response(error, status=400):
    return JsonResponse(
        {
            "ok": False,
            "error": error.message,
            "code": error.code,
        },
        status=status,
    )


def _order_visible_to_request(order, request):
    if request.user.is_authenticated and order.user_id == request.user.id:
        return True

    return bool(order.session_key and order.session_key == request.session.session_key)


@require_POST
def quote(request):
    try:
        payload = _json_payload(request)
        data = quote_cart(payload, language=_language(request))
    except CartValidationError as error:
        return _error_response(error)

    return JsonResponse({"ok": True, **data})


@require_POST
def create(request):
    try:
        payload = _json_payload(request)
        order = create_order_from_payload(
            payload,
            request=request,
            language=_language(request),
        )
    except CartValidationError as error:
        return _error_response(error)

    return JsonResponse(
        {
            "ok": True,
            "order": {
                "id": order.id,
                "status": order.status,
                "total": f"{order.total_amount:.2f}",
                "currency": order.currency,
                "confirmation_url": reverse("orders:success", args=[order.id]),
            },
            "confirmation_url": reverse("orders:success", args=[order.id]),
        },
        status=201,
    )


@require_GET
def success(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related("table", "user").prefetch_related("items__dish", "payments"),
        id=order_id,
    )

    if not _order_visible_to_request(order, request):
        return JsonResponse({"ok": False, "error": "Заказ не найден."}, status=404)

    decorate_order(order)

    return render(
        request,
        "orders/success.html",
        {
            "order": order,
            "items_json": order.items_json,
        },
    )


@login_required
@require_GET
def history(request):
    orders = list(
        Order.objects.filter(user=request.user)
        .select_related("table")
        .prefetch_related("items__dish", "payments")
        .order_by("-created_at")
    )

    return render(
        request,
        "orders/history.html",
        {
            "orders": decorate_orders(orders),
        },
    )
