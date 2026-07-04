import hashlib
import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from menu.models import Dish, DishIngredient
from menu.translations import localized_dish_string

from .models import (
    Order,
    ORDER_COMMENT_MAX_LENGTH,
    ORDER_ITEM_NOTE_MAX_LENGTH,
    OrderItem,
    OrderItemModifier,
    OrderStatusHistory,
    Payment,
    Restaurant,
    Table,
    TableQrTokenAudit,
    hash_table_qr_token,
)


logger = logging.getLogger(__name__)


class CartValidationError(ValueError):
    def __init__(self, message, code="invalid_cart", status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ValidatedCartModifier:
    type: str
    dish_ingredient: DishIngredient
    name: str
    price_delta: Decimal


@dataclass(frozen=True)
class OrderingContext:
    restaurant_id: int
    table_id: int | None
    source: str
    table_context: str | None = None
    table_token_version: int | None = None


OrderMode = Order.Mode


@dataclass(frozen=True)
class ValidatedCartItem:
    id: str
    dish: Dish
    dish_id: int
    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    note: str
    modifiers: tuple[ValidatedCartModifier, ...]


@dataclass(frozen=True)
class ValidatedCart:
    restaurant: Restaurant
    ordering_context: OrderingContext
    items: tuple[ValidatedCartItem, ...]
    subtotal: Decimal
    total: Decimal
    currency: str
    fingerprint: str
    pricing_revision: str


NO_TABLE_ORDER_MODES = {
    OrderMode.PICKUP,
    OrderMode.COUNTER,
    OrderMode.DELIVERY,
}
TABLE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DISH_CART_ID_PATTERN = re.compile(r"^dish-(\d+)$")
QUOTE_TTL_SECONDS = 180
QUOTE_SIGNING_SALT = "orders.quote"
GUEST_SCOPE_SIGNING_SALT = "orders.idempotency.guest"
TABLE_CONTEXT_SIGNING_SALT = "orders.table-context"
TABLE_CONTEXT_MAX_LENGTH = 512
DEFAULT_TABLE_CONTEXT_TTL_SECONDS = 12 * 60 * 60
ORDER_REQUEST_MAX_BYTES = 128 * 1024
MAX_CART_LINE_ITEMS = 50
MAX_CART_TOTAL_QUANTITY = 100
MAX_MODIFIERS_PER_ITEM = 20
MAX_CART_TOTAL_MODIFIERS = 200
MAX_GUESTS_COUNT = 20


def normalize_limited_text(value, max_length, error_message, error_code):
    text = str(value or "").strip()

    if len(text) > max_length:
        raise CartValidationError(error_message, code=error_code)

    return text


def normalize_legacy_dish_id(value):
    if isinstance(value, bool):
        raise CartValidationError("Некорректное блюдо.")

    if isinstance(value, int):
        return value

    if isinstance(value, str):
        value = value.strip()

        if value.isdecimal():
            return int(value)

    raise CartValidationError("Некорректное блюдо.")


def normalize_cart_item_dish_id(value):
    if not isinstance(value, str):
        raise CartValidationError("Некорректное блюдо.")

    match = DISH_CART_ID_PATTERN.fullmatch(value.strip())

    if not match:
        raise CartValidationError("Некорректное блюдо.")

    return int(match.group(1))


def normalize_dish_id(raw_item):
    for key in ("dish_id", "dishId", "dish"):
        if key in raw_item and raw_item[key] is not None:
            return normalize_legacy_dish_id(raw_item[key])

    if "id" in raw_item and raw_item["id"] is not None:
        return normalize_cart_item_dish_id(raw_item["id"])

    raise CartValidationError("Некорректное блюдо.")


def normalize_quantity(value):
    if isinstance(value, bool):
        raise CartValidationError("Некорректное количество.")

    try:
        quantity = int(value)
    except (TypeError, ValueError):
        raise CartValidationError("Некорректное количество.")

    if quantity < 1:
        raise CartValidationError("Количество должно быть больше нуля.")

    if quantity > 99:
        raise CartValidationError("Слишком большое количество в одной позиции.")

    return quantity


def normalize_guests_count(value):
    if isinstance(value, bool):
        raise CartValidationError(
            "Некорректное количество гостей.",
            code="invalid_guests_count",
        )

    try:
        guests_count = int(value)
    except (TypeError, ValueError):
        raise CartValidationError(
            "Некорректное количество гостей.",
            code="invalid_guests_count",
        )

    if guests_count < 1 or guests_count > MAX_GUESTS_COUNT:
        raise CartValidationError(
            f"Количество гостей должно быть от 1 до {MAX_GUESTS_COUNT}.",
            code="invalid_guests_count",
        )

    return guests_count


def guests_count_from_payload(payload):
    if "guests_count" in payload:
        return payload.get("guests_count")

    if "persons" in payload:
        return payload.get("persons")

    return 1


def normalize_item_note(value):
    return normalize_limited_text(
        value,
        ORDER_ITEM_NOTE_MAX_LENGTH,
        "Комментарий к позиции слишком длинный. Максимум — 255 символов.",
        "item_note_too_long",
    )


def normalize_order_comment(value):
    return normalize_limited_text(
        value,
        ORDER_COMMENT_MAX_LENGTH,
        "Комментарий к заказу слишком длинный. Максимум — 2000 символов.",
        "order_comment_too_long",
    )


def normalize_modifier_payload(raw_modifier):
    if not isinstance(raw_modifier, dict):
        raise CartValidationError("Некорректный модификатор.")

    modifier_type = raw_modifier.get("type") or OrderItemModifier.Type.REMOVE

    try:
        dish_ingredient_id = int(raw_modifier.get("dish_ingredient_id"))
    except (TypeError, ValueError):
        raise CartValidationError("Некорректный модификатор.")

    return {
        "type": str(modifier_type),
        "dish_ingredient_id": dish_ingredient_id,
    }


def normalize_modifier_payloads(modifiers):
    if not isinstance(modifiers, list):
        raise CartValidationError("Некорректные модификаторы.")

    if len(modifiers) > MAX_MODIFIERS_PER_ITEM:
        raise CartValidationError(
            f"В одной позиции можно указать не более {MAX_MODIFIERS_PER_ITEM} модификаторов.",
            code="too_many_modifiers",
        )

    normalized = [
        normalize_modifier_payload(modifier)
        for modifier in modifiers
    ]
    normalized.sort(
        key=lambda modifier: (
            modifier["type"],
            modifier["dish_ingredient_id"],
        )
    )

    seen = set()

    for modifier in normalized:
        key = (
            modifier["type"],
            modifier["dish_ingredient_id"],
        )

        if key in seen:
            raise CartValidationError(
                "Один и тот же модификатор нельзя указать несколько раз.",
                code="duplicate_modifier",
            )

        seen.add(key)

    return normalized


def cart_item_identity(dish_id, modifiers, note):
    return (
        dish_id,
        tuple(
            (
                modifier["type"],
                modifier["dish_ingredient_id"],
            )
            for modifier in modifiers
        ),
        note,
    )


def cart_item_id(raw_item, dish_id, modifiers, note):
    if not modifiers and not note:
        return f"dish-{dish_id}"

    fingerprint = json.dumps(
        {
            "dish_id": dish_id,
            "modifiers": modifiers,
            "note": note,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return f"dish-{dish_id}-{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()[:12]}"


def normalize_cart_payload(payload):
    raw_items = payload.get("items") if isinstance(payload, dict) else None

    if not isinstance(raw_items, list) or not raw_items:
        raise CartValidationError("Корзина пуста.", code="empty_cart")

    if len(raw_items) > MAX_CART_LINE_ITEMS:
        raise CartValidationError(
            f"В заказе может быть не более {MAX_CART_LINE_ITEMS} позиций.",
            code="too_many_cart_lines",
        )

    normalized = []
    seen = {}
    total_quantity = 0
    total_modifiers = 0

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise CartValidationError("Некорректная позиция заказа.")

        dish_id = normalize_dish_id(raw_item)
        quantity = normalize_quantity(
            raw_item.get("quantity") or raw_item.get("qty")
        )
        modifiers = normalize_modifier_payloads(raw_item.get("modifiers") or [])
        note = normalize_item_note(raw_item.get("note"))
        total_quantity += quantity
        total_modifiers += len(modifiers)

        if total_quantity > MAX_CART_TOTAL_QUANTITY:
            raise CartValidationError(
                f"В одном заказе может быть не более {MAX_CART_TOTAL_QUANTITY} блюд.",
                code="cart_quantity_limit",
            )

        if total_modifiers > MAX_CART_TOTAL_MODIFIERS:
            raise CartValidationError(
                "В заказе слишком много модификаторов.",
                code="cart_modifiers_limit",
            )

        identity = cart_item_identity(dish_id, modifiers, note)
        cart_id = cart_item_id(raw_item, dish_id, modifiers, note)

        if identity in seen:
            seen[identity]["quantity"] += quantity

            if seen[identity]["quantity"] > 99:
                raise CartValidationError("Слишком большое количество в одной позиции.")

            continue

        item = {
            "id": cart_id,
            "dish_id": dish_id,
            "quantity": quantity,
            "modifiers": modifiers,
            "note": note,
        }
        normalized.append(item)
        seen[identity] = item

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


def get_idempotency_actor_scope(request=None):
    if request is None:
        return "system:anonymous"

    user = getattr(request, "user", None)

    if user is not None and user.is_authenticated:
        return f"user:{user.pk}"

    if not request.session.session_key:
        request.session.save()

    session_key = request.session.session_key or ""
    signed_session = signing.Signer(salt=GUEST_SCOPE_SIGNING_SALT).sign(session_key)
    return f"guest:{signed_session}"


def build_cart_fingerprint(
    payload,
    restaurant,
    normalized_items=None,
    ordering_context=None,
):
    normalized_items = normalized_items or normalize_cart_payload(payload)
    ordering_context = ordering_context or OrderingContext(
        restaurant_id=restaurant.id,
        table_id=None,
        source="legacy",
    )
    payment_method = payload.get("payment_method") or payload.get("payment") or ""
    comment = normalize_order_comment(payload.get("comment"))
    fingerprint_items = [
        {
            "dish_id": item["dish_id"],
            "quantity": item["quantity"],
            "modifiers": item["modifiers"],
            "note": item["note"],
        }
        for item in normalized_items
    ]
    fingerprint_payload = {
        "items": fingerprint_items,
        "guests_count": normalize_guests_count(guests_count_from_payload(payload)),
        "payment_method": str(payment_method),
        "comment": comment,
        "restaurant_id": ordering_context.restaurant_id,
        "table_id": str(ordering_context.table_id or ""),
        "table_token_version": str(ordering_context.table_token_version or ""),
        "ordering_source": ordering_context.source,
    }
    fingerprint_json = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(fingerprint_json.encode("utf-8")).hexdigest()


def build_pricing_revision(cart):
    pricing_payload = {
        "currency": cart.currency,
        "restaurant_id": cart.restaurant.id,
        "subtotal": str(cart.subtotal),
        "total": str(cart.total),
        "items": [
            {
                "dish_id": item.dish_id,
                "dish_updated_at": item.dish.updated_at.isoformat(),
                "dish_is_active": item.dish.is_active,
                "dish_is_available": item.dish.is_available,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "line_total": str(item.line_total),
                "modifiers": [
                    {
                        "dish_ingredient_id": modifier.dish_ingredient.id,
                        "price_delta": str(modifier.price_delta),
                    }
                    for modifier in item.modifiers
                ],
            }
            for item in cart.items
        ],
    }
    pricing_json = json.dumps(
        pricing_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(pricing_json.encode("utf-8")).hexdigest()


def build_quote_payload(cart, expires_at):
    expires_at_value = (
        expires_at.isoformat()
        if hasattr(expires_at, "isoformat")
        else str(expires_at or "")
    )

    return {
        "fingerprint": cart.fingerprint,
        "pricing_revision": cart.pricing_revision,
        "restaurant_id": cart.restaurant.id,
        "expires_at": expires_at_value,
    }


def build_quote_id(cart, expires_at):
    return signing.dumps(
        build_quote_payload(cart, expires_at),
        salt=QUOTE_SIGNING_SALT,
    )


def validate_quote_for_cart(payload, cart):
    quote_id = str(payload.get("quote_id") or "").strip()

    if not quote_id:
        raise CartValidationError(
            "Подтвердите актуальную сумму заказа.",
            code="quote_required",
            status=409,
        )

    try:
        quote_payload = signing.loads(
            quote_id,
            salt=QUOTE_SIGNING_SALT,
            max_age=QUOTE_TTL_SECONDS,
        )
    except signing.SignatureExpired:
        raise CartValidationError(
            "Расчёт заказа устарел. Проверьте сумму ещё раз.",
            code="quote_expired",
            status=409,
        )
    except signing.BadSignature:
        raise CartValidationError(
            "Расчёт заказа не подтверждён.",
            code="invalid_quote",
            status=409,
        )

    expected = build_quote_payload(cart, quote_payload.get("expires_at", ""))

    if (
        quote_payload.get("fingerprint") != expected["fingerprint"]
        or quote_payload.get("pricing_revision") != expected["pricing_revision"]
        or quote_payload.get("restaurant_id") != expected["restaurant_id"]
    ):
        raise CartValidationError(
            "Состав или сумма заказа изменились. Проверьте корзину и подтвердите заказ ещё раз.",
            code="quote_changed",
            status=409,
        )

    return quote_payload


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


def _priced_unit_amount(base_price, modifiers):
    unit_price = Decimal(base_price)

    for modifier in modifiers:
        unit_price += modifier.price_delta

    if unit_price < Decimal("0.00"):
        raise CartValidationError(
            "Итоговая цена позиции не может быть отрицательной.",
            code="invalid_item_price",
        )

    return unit_price


def get_default_restaurant():
    restaurant, _ = Restaurant.objects.get_or_create(
        slug="caesar-company",
        defaults={"name": "Caesar & Company"},
    )

    if not restaurant.is_active:
        restaurant.is_active = True
        restaurant.save(update_fields=["is_active"])

    return restaurant


def _clean_payload_value(payload, *names):
    for name in names:
        value = payload.get(name)

        if value is not None and str(value).strip():
            return str(value).strip()

    return ""


def _get_restaurant_by_payload_identity(payload):
    restaurant_id = payload.get("restaurant_id")
    restaurant_slug = payload.get("restaurant_slug") or payload.get("restaurant")

    if restaurant_id:
        try:
            return Restaurant.objects.get(id=restaurant_id, is_active=True)
        except (Restaurant.DoesNotExist, TypeError, ValueError):
            raise CartValidationError(
                "Ресторан не найден.",
                code="restaurant_not_found",
                status=404,
            )

    if restaurant_slug:
        restaurant = Restaurant.objects.filter(
            slug=str(restaurant_slug).strip(),
            is_active=True,
        ).first()

        if restaurant is None:
            raise CartValidationError(
                "Ресторан не найден.",
                code="restaurant_not_found",
                status=404,
            )

        return restaurant

    return None


def _order_mode_from_payload(payload):
    raw_mode = _clean_payload_value(
        payload,
        "order_source",
        "order_mode",
        "fulfillment",
        "source",
    ).casefold()

    aliases = {
        "qr": OrderMode.TABLE.value,
        "dine_in": OrderMode.TABLE.value,
        "dine-in": OrderMode.TABLE.value,
        "eat_in": OrderMode.TABLE.value,
        "eat-in": OrderMode.TABLE.value,
        "takeaway": "pickup",
        "takeout": "pickup",
        "self_pickup": "pickup",
        "front_desk": "counter",
        "desk": "counter",
    }
    mode = aliases.get(raw_mode, raw_mode)

    if not mode:
        return None

    try:
        return OrderMode(mode)
    except ValueError:
        raise CartValidationError(
            "Некорректный режим заказа.",
            code="invalid_order_mode",
        )


def _has_untrusted_table_reference(payload):
    return bool(
        _clean_payload_value(payload, "table_id")
        or _clean_payload_value(payload, "table_number", "table")
    )


def _log_untrusted_table_reference(payload, reason):
    logger.warning(
        "Rejected untrusted table reference: reason=%s table_id=%r table_number=%r order_mode=%r restaurant=%r",
        reason,
        payload.get("table_id"),
        payload.get("table_number") or payload.get("table"),
        _clean_payload_value(payload, "order_source", "order_mode", "fulfillment", "source"),
        payload.get("restaurant_slug") or payload.get("restaurant_id") or payload.get("restaurant"),
    )


def get_table_context_ttl_seconds():
    try:
        value = int(
            getattr(
                settings,
                "TABLE_CONTEXT_TTL_SECONDS",
                DEFAULT_TABLE_CONTEXT_TTL_SECONDS,
            )
        )
    except (TypeError, ValueError):
        value = DEFAULT_TABLE_CONTEXT_TTL_SECONDS

    return max(60, value)


def build_table_context_token(table):
    return signing.dumps(
        {
            "restaurant_id": table.restaurant_id,
            "table_id": table.id,
            "token_version": table.qr_token_version,
        },
        salt=TABLE_CONTEXT_SIGNING_SALT,
        compress=True,
    )


def _validate_table_for_context(table, token_version):
    if (
        table.qr_token_revoked_at
        or not table.is_active
        or not table.restaurant.is_active
        or table.qr_token_version != token_version
    ):
        raise CartValidationError(
            "Контекст стола больше не действует.",
            code="table_context_revoked",
            status=410,
        )

    if (
        table.qr_token_expires_at
        and table.qr_token_expires_at <= timezone.now()
    ):
        raise CartValidationError(
            "Контекст стола истёк.",
            code="table_context_expired",
            status=410,
        )


def _context_for_table_context(table_context):
    table_context = str(table_context or "").strip()

    if not table_context or len(table_context) > TABLE_CONTEXT_MAX_LENGTH:
        raise CartValidationError(
            "Некорректный контекст стола.",
            code="invalid_table_context",
            status=400,
        )

    try:
        context_payload = signing.loads(
            table_context,
            salt=TABLE_CONTEXT_SIGNING_SALT,
            max_age=get_table_context_ttl_seconds(),
        )
    except signing.SignatureExpired:
        raise CartValidationError(
            "Контекст стола истёк.",
            code="table_context_expired",
            status=410,
        )
    except signing.BadSignature:
        raise CartValidationError(
            "Некорректный контекст стола.",
            code="invalid_table_context",
            status=400,
        )

    if not isinstance(context_payload, dict):
        raise CartValidationError(
            "Некорректный контекст стола.",
            code="invalid_table_context",
            status=400,
        )

    try:
        restaurant_id = int(context_payload["restaurant_id"])
        table_id = int(context_payload["table_id"])
        token_version = int(context_payload["token_version"])
    except (KeyError, TypeError, ValueError):
        raise CartValidationError(
            "Некорректный контекст стола.",
            code="invalid_table_context",
            status=400,
        )

    table = (
        Table.objects.select_related("restaurant")
        .filter(
            id=table_id,
            restaurant_id=restaurant_id,
        )
        .first()
    )

    if table is None:
        raise CartValidationError(
            "Контекст стола больше не действует.",
            code="table_context_revoked",
            status=410,
        )

    _validate_table_for_context(table, token_version)

    return OrderingContext(
        restaurant_id=table.restaurant_id,
        table_id=table.id,
        source=OrderMode.TABLE.value,
        table_context=table_context,
        table_token_version=token_version,
    )


def _context_for_table_token(table_token):
    if not TABLE_TOKEN_PATTERN.fullmatch(table_token):
        raise CartValidationError(
            "Некорректный QR-токен стола.",
            code="invalid_table_token",
            status=400,
        )

    table_token_hash = hash_table_qr_token(table_token)
    table = (
        Table.objects.select_related("restaurant")
        .filter(qr_token_hash=table_token_hash)
        .first()
    )

    if table is None:
        if TableQrTokenAudit.objects.filter(
            token_hash=table_token_hash,
            action=TableQrTokenAudit.Action.REVOKED,
        ).exists():
            raise CartValidationError(
                "QR-токен стола больше не действует.",
                code="table_token_revoked",
                status=410,
            )

        raise CartValidationError(
            "QR-токен стола не найден.",
            code="table_token_not_found",
            status=404,
        )

    if (
        table.qr_token_revoked_at
        or not table.is_active
        or not table.restaurant.is_active
    ):
        raise CartValidationError(
            "QR-токен стола больше не действует.",
            code="table_token_revoked",
            status=410,
        )

    if (
        table.qr_token_expires_at
        and table.qr_token_expires_at <= timezone.now()
    ):
        raise CartValidationError(
            "QR-токен стола истёк.",
            code="table_token_expired",
            status=410,
        )

    return OrderingContext(
        restaurant_id=table.restaurant_id,
        table_id=table.id,
        source=OrderMode.TABLE.value,
        table_context=build_table_context_token(table),
        table_token_version=table.qr_token_version,
    )


def get_table_for_qr_token(table_token):
    ordering_context = _context_for_table_token(table_token)
    return get_table_for_ordering_context(ordering_context)


def get_table_for_table_context(table_context):
    ordering_context = _context_for_table_context(table_context)
    return get_table_for_ordering_context(ordering_context)


def resolve_ordering_context(
    payload,
    *,
    restaurant=None,
    allow_menu_context=False,
    allow_missing=False,
):
    if not isinstance(payload, dict):
        raise CartValidationError("Некорректная корзина.")

    table_context = _clean_payload_value(payload, "table_context")

    if table_context:
        return _context_for_table_context(table_context)

    table_token = _clean_payload_value(payload, "table_token", "qr_token")

    if table_token:
        return _context_for_table_token(table_token)

    if _has_untrusted_table_reference(payload):
        _log_untrusted_table_reference(payload, "missing_table_token")
        raise CartValidationError(
            "Для заказа за столом нужен QR-токен стола.",
            code="table_token_required",
        )

    if restaurant is not None:
        return OrderingContext(
            restaurant_id=restaurant.id,
            table_id=None,
            source="menu" if allow_menu_context else "restaurant",
        )

    order_mode = _order_mode_from_payload(payload)
    explicit_restaurant = _get_restaurant_by_payload_identity(payload)

    if order_mode == OrderMode.TABLE:
        _log_untrusted_table_reference(payload, "table_mode_without_token")
        raise CartValidationError(
            "Для заказа за столом нужен QR-токен стола.",
            code="table_token_required",
        )

    if order_mode in NO_TABLE_ORDER_MODES:
        if explicit_restaurant is None:
            raise CartValidationError(
                "Для заказа нужен ресторан.",
                code="restaurant_required",
            )

        return OrderingContext(
            restaurant_id=explicit_restaurant.id,
            table_id=None,
            source=order_mode.value,
        )

    if allow_menu_context and explicit_restaurant is not None:
        return OrderingContext(
            restaurant_id=explicit_restaurant.id,
            table_id=None,
            source="menu",
        )

    if allow_missing and explicit_restaurant is None and order_mode is None:
        return None

    if explicit_restaurant is None:
        raise CartValidationError(
            "Ресторан заказа не определён.",
            code="restaurant_required",
        )

    raise CartValidationError(
        "Выберите режим заказа: за столом, самовывоз, заказ у стойки или доставка.",
        code="order_mode_required",
    )


def get_restaurant_for_ordering_context(ordering_context):
    try:
        return Restaurant.objects.get(
            id=ordering_context.restaurant_id,
            is_active=True,
        )
    except Restaurant.DoesNotExist:
        raise CartValidationError(
            "Ресторан не найден.",
            code="restaurant_not_found",
            status=404,
        )


def get_restaurant_for_payload(payload):
    ordering_context = resolve_ordering_context(
        payload,
        allow_menu_context=True,
    )
    return get_restaurant_for_ordering_context(ordering_context)


def _get_dishes_by_id(dish_ids, restaurant):
    dishes = {
        dish.id: dish
        for dish in Dish.objects.filter(
            restaurant=restaurant,
            id__in=dish_ids,
            is_active=True,
            is_available=True,
        ).select_related("category").prefetch_related("translations")
    }

    missing_ids = [dish_id for dish_id in dish_ids if dish_id not in dishes]

    if missing_ids:
        raise CartValidationError(
            "Некоторые блюда больше недоступны в меню.",
            code="dish_unavailable",
        )

    return dishes


def _get_removable_dish_ingredients(dish_ingredient_ids):
    if not dish_ingredient_ids:
        return {}

    return {
        dish_ingredient.id: dish_ingredient
        for dish_ingredient in DishIngredient.objects.filter(
            id__in=dish_ingredient_ids,
            can_be_removed=True,
        ).select_related("ingredient")
    }


def _normalize_modifiers(dish, raw_modifiers, dish_ingredients_by_id):
    normalized = []

    for raw_modifier in raw_modifiers:
        if not isinstance(raw_modifier, dict):
            raise CartValidationError("Некорректный модификатор.")

        modifier_type = raw_modifier.get("type") or OrderItemModifier.Type.REMOVE

        if modifier_type != OrderItemModifier.Type.REMOVE:
            raise CartValidationError("Сейчас доступны только модификаторы удаления.")

        dish_ingredient_id = raw_modifier.get("dish_ingredient_id")
        dish_ingredient = dish_ingredients_by_id.get(dish_ingredient_id)

        if dish_ingredient is None or dish_ingredient.dish_id != dish.id:
            raise CartValidationError("Этот ингредиент нельзя убрать из блюда.")

        normalized.append(
            ValidatedCartModifier(
                type=modifier_type,
                dish_ingredient=dish_ingredient,
                name=dish_ingredient.ingredient.name,
                price_delta=Decimal("0.00"),
            )
        )

    return tuple(normalized)


def validate_cart(payload, language="ru", restaurant=None, ordering_context=None):
    ordering_context = ordering_context or resolve_ordering_context(
        payload,
        restaurant=restaurant,
        allow_menu_context=True,
    )

    if restaurant is None or restaurant.id != ordering_context.restaurant_id:
        restaurant = get_restaurant_for_ordering_context(ordering_context)

    normalized_items = normalize_cart_payload(payload)
    dishes = _get_dishes_by_id([item["dish_id"] for item in normalized_items], restaurant)
    dish_ingredients_by_id = _get_removable_dish_ingredients(
        {
            modifier["dish_ingredient_id"]
            for item in normalized_items
            for modifier in item["modifiers"]
        }
    )
    validated_items = []
    subtotal = Decimal("0.00")

    for item in normalized_items:
        dish = dishes[item["dish_id"]]
        quantity = item["quantity"]
        modifiers = _normalize_modifiers(
            dish,
            item["modifiers"],
            dish_ingredients_by_id,
        )
        unit_price = _priced_unit_amount(dish.price, modifiers)
        line_total = unit_price * quantity
        subtotal += line_total

        validated_items.append(
            ValidatedCartItem(
                id=item["id"],
                dish=dish,
                dish_id=dish.id,
                name=localized_dish_string(dish, "name", language=language),
                quantity=quantity,
                unit_price=unit_price,
                line_total=line_total,
                note=item["note"],
                modifiers=modifiers,
            )
        )

    cart = ValidatedCart(
        restaurant=restaurant,
        ordering_context=ordering_context,
        items=tuple(validated_items),
        subtotal=subtotal,
        total=subtotal,
        currency="RUB",
        fingerprint=build_cart_fingerprint(
            payload,
            restaurant,
            normalized_items=normalized_items,
            ordering_context=ordering_context,
        ),
        pricing_revision="",
    )
    return replace(cart, pricing_revision=build_pricing_revision(cart))


def quote_cart(payload, language="ru", restaurant=None, ordering_context=None):
    cart = validate_cart(
        payload,
        language=language,
        restaurant=restaurant,
        ordering_context=ordering_context,
    )
    expires_at = timezone.now() + timedelta(seconds=QUOTE_TTL_SECONDS)
    quote_id = build_quote_id(cart, expires_at)
    response_items = []

    for item in cart.items:
        response_items.append(
            {
                "id": item.id,
                "dish_id": item.dish_id,
                "name": item.name,
                "quantity": item.quantity,
                "unit_price": _format_money(item.unit_price),
                "line_total": _format_money(item.line_total),
                "note": item.note,
                "modifiers": [
                    {
                        "type": modifier.type,
                        "name": modifier.name,
                        "price_delta": _format_money(modifier.price_delta),
                    }
                    for modifier in item.modifiers
                ],
            }
        )

    return {
        "quote_id": quote_id,
        "pricing_revision": cart.pricing_revision,
        "expires_at": expires_at.isoformat(),
        "fingerprint": cart.fingerprint,
        "currency": cart.currency,
        "items": response_items,
        "subtotal": _format_money(cart.subtotal),
        "total": _format_money(cart.total),
    }


def get_table_for_ordering_context(ordering_context):
    if ordering_context.table_id is None:
        return None

    try:
        return Table.objects.get(
            id=ordering_context.table_id,
            restaurant_id=ordering_context.restaurant_id,
            is_active=True,
        )
    except Table.DoesNotExist:
        raise CartValidationError(
            "Стол не найден.",
            code="table_not_found",
            status=404,
        )


def get_table_for_payload(payload, restaurant):
    ordering_context = resolve_ordering_context(
        payload,
        restaurant=restaurant,
        allow_menu_context=True,
    )
    return get_table_for_ordering_context(ordering_context)


def get_order_mode_for_ordering_context(ordering_context):
    try:
        order_mode = Order.Mode(ordering_context.source)
    except ValueError:
        raise CartValidationError(
            "Режим заказа не определён.",
            code="order_mode_required",
        )

    if order_mode == Order.Mode.LEGACY:
        raise CartValidationError(
            "Старый режим заказа нельзя использовать для нового заказа.",
            code="invalid_order_mode",
        )

    return order_mode


def create_order_from_payload(payload, request=None, language="ru"):
    ordering_context = resolve_ordering_context(payload)
    idempotency_key = get_idempotency_key(payload, request=request)
    restaurant = get_restaurant_for_ordering_context(ordering_context)
    actor_scope = get_idempotency_actor_scope(request)
    existing_order = Order.objects.filter(
        idempotency_actor_scope=actor_scope,
        restaurant=restaurant,
        idempotency_key=idempotency_key,
    ).first()

    if existing_order:
        idempotency_fingerprint = build_cart_fingerprint(
            payload,
            restaurant,
            ordering_context=ordering_context,
        )
        return _return_idempotent_order(existing_order, idempotency_fingerprint)

    cart = validate_cart(
        payload,
        language=language,
        restaurant=restaurant,
        ordering_context=ordering_context,
    )
    restaurant = cart.restaurant
    idempotency_fingerprint = cart.fingerprint
    validate_quote_for_cart(payload, cart)
    table = get_table_for_ordering_context(ordering_context)
    order_mode = get_order_mode_for_ordering_context(ordering_context)
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
                order_mode=order_mode,
                restaurant_name_snapshot=restaurant.name,
                restaurant_slug_snapshot=restaurant.slug,
                table_number_snapshot=table.number if table else "",
                table_title_snapshot=table.title if table else "",
                user=user,
                session_key=session_key,
                idempotency_key=idempotency_key,
                idempotency_actor_scope=actor_scope,
                idempotency_fingerprint=idempotency_fingerprint,
                guests_count=normalize_guests_count(guests_count_from_payload(payload)),
                comment=normalize_order_comment(payload.get("comment")),
                currency=cart.currency,
                subtotal_amount=cart.subtotal,
                total_amount=cart.total,
            )

            for item in cart.items:
                order_item = OrderItem.objects.create(
                    order=order,
                    dish=item.dish,
                    dish_name=item.name,
                    dish_code_snapshot=item.dish.code,
                    category_name_snapshot=(
                        item.dish.category.name
                        if item.dish.category_id
                        else ""
                    ),
                    category_code_snapshot=(
                        item.dish.category.code
                        if item.dish.category_id
                        else ""
                    ),
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_total=item.line_total,
                    note=item.note,
                )

                for modifier in item.modifiers:
                    OrderItemModifier.objects.create(
                        order_item=order_item,
                        type=modifier.type,
                        dish_ingredient=modifier.dish_ingredient,
                        name=modifier.name,
                        price_delta=modifier.price_delta,
                    )

            Payment.objects.create(
                order=order,
                method=payment_method,
                amount=order.total_amount,
                currency=order.currency,
            )

            OrderStatusHistory.objects.create(
                order=order,
                from_status="",
                to_status=Order.Status.CREATED,
                changed_by=user,
                reason="Order created",
                order_version=order.version,
            )
    except IntegrityError:
        existing_order = Order.objects.filter(
            idempotency_actor_scope=actor_scope,
            restaurant=restaurant,
            idempotency_key=idempotency_key,
        ).first()

        if existing_order is None:
            raise

        return _return_idempotent_order(existing_order, idempotency_fingerprint)

    return order
