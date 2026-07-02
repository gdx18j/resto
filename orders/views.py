import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import Order, Payment
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


def _payload_with_session_table(payload, request):
    if not isinstance(payload, dict):
        return payload

    table_id = request.session.get("table_id")
    if table_id and not payload.get("table_id"):
        payload = payload.copy()
        payload["table_id"] = table_id
        payload.setdefault("table_number", request.session.get("table_number", ""))

    return payload


def _error_response(error, status=400):
    return JsonResponse(
        {
            "ok": False,
            "error": error.message,
            "code": error.code,
        },
        status=getattr(error, "status", status),
    )


def _order_visible_to_request(order, request):
    if request.user.is_authenticated and order.user_id == request.user.id:
        return True

    return bool(order.session_key and order.session_key == request.session.session_key)


@require_POST
def quote(request):
    try:
        payload = _payload_with_session_table(_json_payload(request), request)
        data = quote_cart(payload, language=_language(request))
    except CartValidationError as error:
        return _error_response(error)

    return JsonResponse({"ok": True, **data})


@require_POST
def create(request):
    try:
        payload = _payload_with_session_table(_json_payload(request), request)
        order = create_order_from_payload(
            payload,
            request=request,
            language=_language(request),
        )
    except CartValidationError as error:
        return _error_response(error)

    is_replay = bool(getattr(order, "idempotency_replayed", False))

    return JsonResponse(
        {
            "ok": True,
            "idempotency_replayed": is_replay,
            "order": {
                "id": order.id,
                "status": order.status,
                "total": f"{order.total_amount:.2f}",
                "currency": order.currency,
                "confirmation_url": reverse("orders:success", args=[order.id]),
            },
            "confirmation_url": reverse("orders:success", args=[order.id]),
        },
        status=200 if is_replay else 201,
    )


@require_GET
def success(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related("table", "user").prefetch_related("items__dish", "items__modifiers", "payments"),
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


@require_http_methods(["GET", "POST"])
def mock_pay(request, order_id):
    if not settings.YOOKASSA_MOCK:
        return JsonResponse({"ok": False, "error": "Mock payments are disabled."}, status=404)

    order = get_object_or_404(
        Order.objects.select_related("table", "user").prefetch_related("items__dish", "items__modifiers", "payments"),
        id=order_id,
    )

    if not _order_visible_to_request(order, request):
        return JsonResponse({"ok": False, "error": "Заказ не найден."}, status=404)

    payment = (
        order.payments.filter(provider="mock")
        .order_by("-created_at")
        .first()
        or order.payments.filter(method=Payment.Method.ONLINE).order_by("-created_at").first()
    )

    if request.method == "POST":
        if payment:
            if request.POST.get("outcome") == "success":
                payment.status = Payment.Status.PAID
                payment.paid_at = timezone.now()
                payment.save(update_fields=["status", "paid_at"])
            else:
                payment.status = Payment.Status.FAILED
                payment.save(update_fields=["status"])

        return redirect("orders:success", order_id=order.id)

    decorate_order(order)

    return render(
        request,
        "orders/mock_pay.html",
        {
            "order": order,
            "payment": payment,
        },
    )


@login_required
@require_GET
def history(request):
    orders_queryset = (
        Order.objects.filter(user=request.user)
        .select_related("table")
        .prefetch_related("items__dish", "items__modifiers", "payments")
        .order_by("-created_at")
    )
    paginator = Paginator(orders_queryset, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    orders = list(page_obj.object_list)

    return render(
        request,
        "orders/history.html",
        {
            "orders": decorate_orders(orders),
            "page_obj": page_obj,
            "paginator": paginator,
        },
    )
