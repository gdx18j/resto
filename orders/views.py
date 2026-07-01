import json
import logging

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from tables.models import Table

from .models import Order, OrderItem

logger = logging.getLogger(__name__)


def _order_items_json(order):
    """Список позиций заказа в виде JSON-строки — используется кнопкой
    «Повторить заказ» на фронтенде (см. static/js/cart.js: repeatOrder).
    Экранируем "</" на случай, если в названии блюда встретится такая
    последовательность — иначе она может преждевременно закрыть тег
    <script>, в который эта строка вставляется.
    """
    items = [
        {"name": item.dish_name, "price": str(item.price), "qty": item.qty}
        for item in order.items.all()
    ]
    return json.dumps(items).replace("</", "<\\/")


@require_POST
def create_order(request):
    """Принимает корзину из cart.js, создаёт Order + OrderItem
    и сразу помечает заказ оплаченным.

    ЮKassa пока не подключена (нет оформленной самозанятости/ИП),
    поэтому оплата имитируется вручную: как только заказ создан —
    сразу переводим его в статус "оплачен" и отправляем на кухню.
    Когда появятся настоящие ключи ЮKassa — здесь нужно будет
    вернуть вызов create_payment() и вести гостя на страницу оплаты
    вместо мгновенного успеха.
    """
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"error": "Некорректные данные заказа."}, status=400)

    items = payload.get("items") or {}
    comment = (payload.get("comment") or "").strip()
    guests_count = payload.get("guests_count") or 1
    payment_method_map = {
        "card": Order.PAYMENT_METHOD_CARD,
        "online": Order.PAYMENT_METHOD_SBP,
        "cash": Order.PAYMENT_METHOD_CASH,
    }
    payment_method = payment_method_map.get(payload.get("payment_method"), Order.PAYMENT_METHOD_CARD)

    if not items:
        return JsonResponse({"error": "Корзина пуста."}, status=400)

    table_id = request.session.get("table_id")
    table = None
    if table_id:
        table = Table.objects.filter(id=table_id, is_active=True).first()

    order = Order.objects.create(
        table=table,
        user=request.user if request.user.is_authenticated else None,
        status=Order.STATUS_DRAFT,
        comment=comment,
        guests_count=guests_count,
    )

    order_items = []
    for dish_id, item in items.items():
        try:
            price = Decimal(str(item.get("price", 0)))
            qty = int(item.get("qty", 1))
        except (InvalidOperation, TypeError, ValueError):
            continue

        if qty <= 0 or price < 0:
            continue

        order_items.append(
            OrderItem(
                order=order,
                dish_name=str(item.get("name", "Без названия"))[:200],
                price=price,
                qty=qty,
            )
        )

    if not order_items:
        order.delete()
        return JsonResponse({"error": "Не удалось распознать товары в корзине."}, status=400)

    OrderItem.objects.bulk_create(order_items)
    order.recalc_total()

    if order.total <= 0:
        return JsonResponse({"error": "Сумма заказа должна быть больше нуля."}, status=400)

    order.status = Order.STATUS_PAID
    order.payment_method = payment_method
    order.paid_at = timezone.now()
    order.save(update_fields=["status", "payment_method", "paid_at"])
    send_order_to_kitchen(order)

    confirmation_url = reverse("orders:success", args=[order.id])

    return JsonResponse({
        "order_id": order.id,
        "confirmation_url": confirmation_url,
    })


def send_order_to_kitchen(order):
    """Заглушка отправки заказа на кухню / официанту.

    Сюда позже можно подключить: печать чека на кухонном принтере,
    интеграцию с R-Keeper/iiko, уведомление официантам в Telegram и т.п.
    Пока просто переводим заказ в статус "передан на кухню".
    """
    order.status = Order.STATUS_SENT_TO_KITCHEN
    order.save(update_fields=["status"])
    logger.info("Заказ №%s передан на кухню (заглушка).", order.id)


def order_success(request, order_id):
    """Страница «Спасибо за оплату» — открывается сразу после create_order."""
    order = get_object_or_404(Order, id=order_id)
    context = {
        "order": order,
        "items_json": _order_items_json(order),
    }
    return render(request, "orders/success.html", context)


@login_required
def order_history(request):
    """История заказов гостя — список всех его заказов с их статусами."""
    orders = (
        Order.objects.filter(user=request.user)
        .exclude(status=Order.STATUS_DRAFT)
        .prefetch_related("items")
        .order_by("-created_at")
    )
    orders = list(orders)
    for order in orders:
        order.items_json = _order_items_json(order)

    return render(request, "orders/history.html", {"orders": orders})