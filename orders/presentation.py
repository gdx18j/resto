import json

from menu.models import Dish, DishIngredient

from .models import Order


STATUS_LABELS = {
    Order.Status.CREATED: "Создан",
    Order.Status.CONFIRMED: "Подтвержден",
    Order.Status.COOKING: "Готовится",
    Order.Status.READY: "Готов",
    Order.Status.SERVED: "Подан",
    Order.Status.COMPLETED: "Завершен",
    Order.Status.CANCELED: "Отменен",
}


def order_items_json(order):
    items = []

    for item in order.items.all():
        items.append(
            {
                "id": f"order-item-{item.id}",
                "dish_id": item.dish_id,
                "name": item.dish_name,
                "price": f"{item.unit_price:.2f}",
                "qty": item.quantity,
                "note": item.note,
                "modifiers": [
                    {
                        "type": modifier.type,
                        "dish_ingredient_id": modifier.dish_ingredient_id,
                        "name": modifier.name,
                        "price_delta": f"{modifier.price_delta:.2f}",
                    }
                    for modifier in item.modifiers.all()
                ],
            }
        )

    return json.dumps(items, ensure_ascii=False).replace("</", "<\\/")


def _safe_json(value):
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def repeat_order_result(order):
    result = {
        "available": [],
        "changed": [],
        "unavailable": [],
        "context": {
            "restaurant_slug": order.restaurant_slug_snapshot,
            "order_mode": order.order_mode,
            "table_number": order.table_number_snapshot,
        },
    }

    items = list(order.items.all())
    dish_ids = [item.dish_id for item in items]
    dishes = {
        dish.id: dish
        for dish in Dish.objects.filter(
            id__in=dish_ids,
            restaurant_id=order.restaurant_id,
            is_active=True,
            is_available=True,
        )
    }
    dish_ingredient_ids = {
        modifier.dish_ingredient_id
        for item in items
        for modifier in item.modifiers.all()
        if modifier.dish_ingredient_id is not None
    }
    current_modifiers = {
        dish_ingredient.id: dish_ingredient
        for dish_ingredient in DishIngredient.objects.select_related("ingredient").filter(
            id__in=dish_ingredient_ids,
            can_be_removed=True,
        )
    }

    for item in items:
        base_payload = {
            "id": f"repeat-order-item-{item.id}",
            "dish_id": item.dish_id,
            "name": item.dish_name,
            "price": f"{item.unit_price:.2f}",
            "qty": item.quantity,
            "note": item.note,
            "modifiers": [],
        }
        dish = dishes.get(item.dish_id)

        if dish is None:
            result["unavailable"].append(
                {
                    **base_payload,
                    "reason": "dish_unavailable",
                }
            )
            continue

        changed_reasons = []

        if dish.name != item.dish_name:
            changed_reasons.append("name_changed")

        if dish.price != item.unit_price:
            changed_reasons.append("price_changed")
            base_payload["price"] = f"{dish.price:.2f}"

        modifiers = []
        modifier_unavailable = False

        for modifier in item.modifiers.all():
            if modifier.type != "remove" or modifier.dish_ingredient_id is None:
                changed_reasons.append("modifier_changed")
                continue

            current_modifier = current_modifiers.get(modifier.dish_ingredient_id)

            if current_modifier is None or current_modifier.dish_id != dish.id:
                modifier_unavailable = True
                result["unavailable"].append(
                    {
                        **base_payload,
                        "reason": "modifier_unavailable",
                        "modifier": modifier.name,
                    }
                )
                break

            current_name = current_modifier.ingredient.name

            if current_name != modifier.name or modifier.price_delta != 0:
                changed_reasons.append("modifier_changed")

            modifiers.append(
                {
                    "type": modifier.type,
                    "dish_ingredient_id": current_modifier.id,
                    "name": current_name,
                    "price_delta": "0.00",
                }
            )

        if modifier_unavailable:
            continue

        base_payload["name"] = dish.name
        base_payload["modifiers"] = modifiers

        if changed_reasons:
            base_payload["changes"] = sorted(set(changed_reasons))
            result["changed"].append(base_payload)
        else:
            result["available"].append(base_payload)

    return result


def _status_steps(order):
    if order.status == Order.Status.CANCELED:
        return [
            {
                "key": Order.Status.CANCELED,
                "label": STATUS_LABELS[Order.Status.CANCELED],
                "state": "current",
            }
        ]

    try:
        current_index = Order.FLOW.index(order.status)
    except ValueError:
        current_index = 0

    steps = []
    for index, status in enumerate(Order.FLOW):
        if index < current_index:
            state = "done"
        elif index == current_index:
            state = "current"
        else:
            state = "future"

        steps.append(
            {
                "key": status,
                "label": STATUS_LABELS.get(status, status),
                "state": state,
            }
        )

    return steps


def decorate_order(order):
    items = list(order.items.all())
    payments = list(order.payments.all())

    order.items_json = order_items_json(order)
    order.repeat_result = repeat_order_result(order)
    order.repeat_result_json = _safe_json(order.repeat_result)
    order.repeat_available_items_json = _safe_json(order.repeat_result["available"])
    order.can_repeat_in_table_context = (
        order.order_mode == Order.Mode.TABLE
        and bool(order.restaurant_slug_snapshot)
    )
    order.items_count = sum(item.quantity for item in items)
    order.preview_items = items[:2]
    order.hidden_items_count = max(0, len(items) - len(order.preview_items))
    order.primary_payment = payments[0] if payments else None
    order.status_label = STATUS_LABELS.get(order.status, order.get_status_display())
    order.status_steps = _status_steps(order)
    order.history_state = "active"

    if order.status == Order.Status.COMPLETED:
        order.history_state = "completed"
    elif order.status == Order.Status.CANCELED:
        order.history_state = "canceled"

    return order


def decorate_orders(orders):
    for order in orders:
        decorate_order(order)

    return orders
