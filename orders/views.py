import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

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
            },
        },
        status=201,
    )
