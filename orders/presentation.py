import json


def order_items_json(order):
    items = []

    for item in order.items.all():
        items.append(
            {
                "id": f"dish-{item.dish_id}" if item.dish_id else "",
                "dish_id": item.dish_id,
                "name": item.dish_name,
                "price": f"{item.unit_price:.2f}",
                "qty": item.quantity,
            }
        )

    return json.dumps(items, ensure_ascii=False).replace("</", "<\\/")


def decorate_orders(orders):
    for order in orders:
        order.items_json = order_items_json(order)

    return orders
