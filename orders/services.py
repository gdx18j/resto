import hashlib
import json
import re
from decimal import Decimal

from django.db import IntegrityError, transaction

from menu.models import Dish, DishIngredient
from menu.translations import localized_dish_string

from .models import (
    Order,
    OrderItem,
    OrderItemModifier,
    Payment,
    Restaurant,
    Table,
)


class CartValidationError(ValueError):
    def __init__(self, message, code="invalid_cart", status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def normalize_dish_id(value):
    if isinstance(value, int):
        return value

    if not isinstance(value, str):
        raise CartValidationError("Некорректное блюдо.")

    value = value.strip()
    match = re.search(r"(\d+)$", value)

    if not match:
        raise CartValidationError("Некорректное блюдо.")

    return int(match.group(1))


def normalize_quantity(value):
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        raise CartValidationError("Некорректное количество.")

    if quantity < 1:
        raise CartValidationError("Количество должно быть больше нуля.")

    if quantity > 99:
        raise CartValidationError("Слишком большое количество в одной позиции.")

    return quantity


def normalize_cart_payload(payload):
    raw_items = payload.get("items") if isinstance(payload, dict) else None

    if not isinstance(raw_items, list) or not raw_items:
        raise CartValidationError("Корзина пуста.", code="empty_cart")

    normalized = []
    seen = {}

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise CartValidationError("Некорректная позиция заказа.")

        dish_id = normalize_dish_id(
            raw_item.get("dish_id") or raw_item.get("id")
        )
        quantity = normalize_quantity(
            raw_item.get("quantity") or raw_item.get("qty")
        )
        modifiers = raw_item.get("modifiers") or []

        if not isinstance(modifiers, list):
            raise CartValidationError("Некорректные модификаторы.")

        if dish_id in seen:
            seen[dish_id]["quantity"] += quantity

            if seen[dish_id]["quantity"] > 99:
                raise CartValidationError("Слишком большое количество в одной позиции.")

            seen[dish_id]["modifiers"].extend(modifiers)
            continue

        item = {
            "dish_id": dish_id,
            "quantity": quantity,
            "modifiers": list(modifiers),
        }
        normalized.append(item)
        seen[dish_id] = item

    return normalized


def get_idempotency_key(payload, request=None):
    header_value = ""

    if request is not None:
        header_value = request.headers.get("Idempotency-Key", "")

    value = header_value or payload.get("idempotency_key") or ""
    value = str(value).strip()

    if not value:
        raise CartValidationError(
            "Не удалось безопасно оформить заказ. Обновите страницу и попробуйте еще раз.",
            code="idempotency_key_required",
        )

    if len(value) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        raise CartValidationError(
            "Некорректный ключ повтора заказа.",
            code="invalid_idempotency_key",
        )

    return value


def order_payload_fingerprint(payload, restaurant=None):
    normalized_items = normalize_cart_payload(payload)
    payment_method = payload.get("payment_method") or payload.get("payment") or ""
    table_id = payload.get("table_id") or ""
    table_number = payload.get("table_number") or payload.get("table") or ""
    comment = (payload.get("comment") or "").strip()[:2000]

    canonical_payload = {
        "items": normalized_items,
        "guests_count": normalize_quantity(payload.get("guests_count") or payload.get("persons") or 1),
        "payment_method": str(payment_method),
        "comment": comment,
        "restaurant_id": restaurant.id if restaurant else "",
        "table_id": str(table_id),
        "table_number": str(table_number).strip(),
    }
    canonical_json = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _return_idempotent_order(order, fingerprint):
    if order.idempotency_fingerprint != fingerprint:
        raise CartValidationError(
            "Этот ключ уже использован для другого состава заказа.",
            code="idempotency_conflict",
            status=409,
        )

    order.idempotency_replayed = True
    return order


def _format_money(value):
    value = Decimal(value).quantize(Decimal("0.01"))
    return f"{value:.2f}"


def get_default_restaurant():
    restaurant = Restaurant.objects.filter(is_active=True).order_by("id").first()

    if restaurant:
        return restaurant

    restaurant, _ = Restaurant.objects.get_or_create(
        slug="caesar-company",
        defaults={"name": "Caesar & Company"},
    )

    if not restaurant.is_active:
        restaurant.is_active = True
        restaurant.save(update_fields=["is_active"])

    return restaurant


def get_restaurant_for_payload(payload):
    restaurant_id = payload.get("restaurant_id")
    restaurant_slug = payload.get("restaurant_slug") or payload.get("restaurant")
    table_id = payload.get("table_id")
    table_number = payload.get("table_number") or payload.get("table")

    if restaurant_id:
        try:
            return Restaurant.objects.get(id=restaurant_id, is_active=True)
        except (Restaurant.DoesNotExist, TypeError, ValueError):
            raise CartValidationError("Ресторан не найден.", code="restaurant_not_found")

    if restaurant_slug:
        restaurant = Restaurant.objects.filter(
            slug=str(restaurant_slug).strip(),
            is_active=True,
        ).first()

        if restaurant is None:
            raise CartValidationError("Ресторан не найден.", code="restaurant_not_found")

        return restaurant

    if table_id:
        try:
            return Table.objects.select_related("restaurant").get(
                id=table_id,
                is_active=True,
                restaurant__is_active=True,
            ).restaurant
        except (Table.DoesNotExist, TypeError, ValueError):
            raise CartValidationError("Стол не найден.", code="table_not_found")

    if table_number:
        tables = list(
            Table.objects.select_related("restaurant")
            .filter(
                number=str(table_number).strip(),
                is_active=True,
                restaurant__is_active=True,
            )
            .order_by("restaurant_id", "id")
            [:2]
        )

        if len(tables) > 1:
            raise CartValidationError(
                "Уточните ресторан для выбранного стола.",
                code="restaurant_required",
            )

        if tables:
            return tables[0].restaurant

    return get_default_restaurant()


def _get_dishes_by_id(dish_ids, restaurant):
    dishes = {
        dish.id: dish
        for dish in Dish.objects.filter(
            restaurant=restaurant,
            id__in=dish_ids,
            is_active=True,
            is_available=True,
        ).select_related("category")
    }

    missing_ids = [dish_id for dish_id in dish_ids if dish_id not in dishes]

    if missing_ids:
        raise CartValidationError(
            "Некоторые блюда больше недоступны в меню.",
            code="dish_unavailable",
        )

    return dishes


def _normalize_modifiers(dish, raw_modifiers):
    normalized = []

    for raw_modifier in raw_modifiers:
        if not isinstance(raw_modifier, dict):
            raise CartValidationError("Некорректный модификатор.")

        modifier_type = raw_modifier.get("type") or OrderItemModifier.Type.REMOVE

        if modifier_type != OrderItemModifier.Type.REMOVE:
            raise CartValidationError("Сейчас доступны только модификаторы удаления.")

        dish_ingredient_id = raw_modifier.get("dish_ingredient_id")

        try:
            dish_ingredient = DishIngredient.objects.select_related("ingredient").get(
                id=dish_ingredient_id,
                dish=dish,
                can_be_removed=True,
            )
        except (DishIngredient.DoesNotExist, TypeError, ValueError):
            raise CartValidationError("Этот ингредиент нельзя убрать из блюда.")

        normalized.append(
            {
                "type": modifier_type,
                "dish_ingredient": dish_ingredient,
                "name": dish_ingredient.ingredient.name,
                "price_delta": Decimal("0.00"),
            }
        )

    return normalized


def quote_cart(payload, language="ru", restaurant=None):
    restaurant = restaurant or get_restaurant_for_payload(payload)
    normalized_items = normalize_cart_payload(payload)
    dishes = _get_dishes_by_id([item["dish_id"] for item in normalized_items], restaurant)
    response_items = []
    subtotal = Decimal("0.00")

    for item in normalized_items:
        dish = dishes[item["dish_id"]]
        quantity = item["quantity"]
        unit_price = dish.price
        line_total = unit_price * quantity
        modifiers = _normalize_modifiers(dish, item["modifiers"])
        subtotal += line_total

        response_items.append(
            {
                "id": f"dish-{dish.id}",
                "dish_id": dish.id,
                "name": localized_dish_string(dish, "name", language=language),
                "quantity": quantity,
                "unit_price": _format_money(unit_price),
                "line_total": _format_money(line_total),
                "modifiers": [
                    {
                        "type": modifier["type"],
                        "name": modifier["name"],
                        "price_delta": _format_money(modifier["price_delta"]),
                    }
                    for modifier in modifiers
                ],
            }
        )

    return {
        "currency": "RUB",
        "items": response_items,
        "subtotal": _format_money(subtotal),
        "total": _format_money(subtotal),
    }

def get_table_for_payload(payload, restaurant):
    table_id = payload.get("table_id")
    table_number = payload.get("table_number") or payload.get("table")

    if table_id:
        try:
            return Table.objects.get(
                id=table_id,
                restaurant=restaurant,
                is_active=True,
            )
        except Table.DoesNotExist:
            raise CartValidationError("Стол не найден.", code="table_not_found")

    if table_number:
        return Table.objects.filter(
            restaurant=restaurant,
            number=str(table_number).strip(),
            is_active=True,
        ).first()

    return None


@transaction.atomic
def create_order_from_payload(payload, request=None, language="ru"):
    idempotency_key = get_idempotency_key(payload, request=request)
    restaurant = get_restaurant_for_payload(payload)
    idempotency_fingerprint = order_payload_fingerprint(payload, restaurant=restaurant)
    existing_order = Order.objects.filter(idempotency_key=idempotency_key).first()

    if existing_order:
        return _return_idempotent_order(existing_order, idempotency_fingerprint)

    quote = quote_cart(payload, language=language, restaurant=restaurant)
    table = get_table_for_payload(payload, restaurant)
    payment_method = payload.get("payment_method") or payload.get("payment")

    if payment_method not in Payment.Method.values:
        raise CartValidationError(
            "Выберите способ оплаты.",
            code="payment_required",
        )

    user = None
    session_key = ""

    if request is not None:
        if request.user.is_authenticated:
            user = request.user

        if not request.session.session_key:
            request.session.save()
        session_key = request.session.session_key or ""

    try:
        with transaction.atomic():
            order = Order.objects.create(
                restaurant=restaurant,
                table=table,
                user=user,
                session_key=session_key,
                idempotency_key=idempotency_key,
                idempotency_fingerprint=idempotency_fingerprint,
                guests_count=normalize_quantity(payload.get("guests_count") or payload.get("persons") or 1),
                comment=(payload.get("comment") or "").strip()[:2000],
                subtotal_amount=Decimal(quote["subtotal"]),
                total_amount=Decimal(quote["total"]),
            )
    except IntegrityError:
        existing_order = Order.objects.get(idempotency_key=idempotency_key)
        return _return_idempotent_order(existing_order, idempotency_fingerprint)

    normalized_items = normalize_cart_payload(payload)
    dishes = _get_dishes_by_id([item["dish_id"] for item in normalized_items], restaurant)

    for raw_item in normalized_items:
        dish = dishes[raw_item["dish_id"]]
        quantity = raw_item["quantity"]
        order_item = OrderItem.objects.create(
            order=order,
            dish=dish,
            dish_name=localized_dish_string(dish, "name", language=language),
            quantity=quantity,
            unit_price=dish.price,
            line_total=dish.price * quantity,
        )

        for modifier in _normalize_modifiers(dish, raw_item["modifiers"]):
            OrderItemModifier.objects.create(
                order_item=order_item,
                type=modifier["type"],
                dish_ingredient=modifier["dish_ingredient"],
                name=modifier["name"],
                price_delta=modifier["price_delta"],
            )

    Payment.objects.create(
        order=order,
        method=payment_method,
        amount=order.total_amount,
        currency=order.currency,
    )

    return order
