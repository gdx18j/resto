from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone

from menu.models import Dish
from menu.translations import (
    localized_category_values,
    localized_dish_string,
    normalize_language,
)
from orders.models import Restaurant

from .models import ChatMessage


def trim_card_text(value, max_length=130):
    value = " ".join(str(value or "").split())

    if len(value) <= max_length:
        return value

    return f"{value[: max_length - 1].rstrip()}..."


def restaurant_id_for_ai(session=None, ordering_context=None):
    if ordering_context is not None:
        return ordering_context.restaurant_id

    if session is not None and session.restaurant_id:
        return session.restaurant_id

    raise ValueError("AI restaurant context is required.")


def menu_url_for_recommendations(restaurant_id, ordering_context=None):
    if ordering_context is not None and ordering_context.table_context:
        return reverse(
            "menu:table_context_menu",
            args=[ordering_context.table_context],
        )

    restaurant_slug = (
        Restaurant.objects.filter(id=restaurant_id)
        .values_list("slug", flat=True)
        .first()
    )
    menu_url = reverse("menu:dish_list")

    if restaurant_slug:
        return f"{menu_url}?{urlencode({'restaurant': restaurant_slug})}"

    return menu_url


def normalize_recommended_ids(values, *, max_items=3):
    normalized = []

    if not isinstance(values, (list, tuple)):
        return normalized

    for value in values:
        if not isinstance(value, int) or isinstance(value, bool):
            continue

        if value in normalized:
            continue

        normalized.append(value)

        if len(normalized) >= max_items:
            break

    return normalized


def serialize_recommended_dishes(
    dish_ids,
    request,
    language="",
    session=None,
    ordering_context=None,
):
    dish_ids = normalize_recommended_ids(dish_ids)

    if not dish_ids:
        return []

    language = normalize_language(language) if language else ""
    restaurant_id = restaurant_id_for_ai(
        session=session,
        ordering_context=ordering_context,
    )
    dishes_by_id = {
        dish.id: dish
        for dish in Dish.objects.filter(
            restaurant_id=restaurant_id,
            id__in=dish_ids,
            is_active=True,
            is_available=True,
        )
        .select_related("category")
        .prefetch_related("translations", "category__translations")
    }
    menu_url = menu_url_for_recommendations(
        restaurant_id,
        ordering_context=ordering_context,
    )
    recommended = []

    for dish_id in dish_ids:
        dish = dishes_by_id.get(dish_id)

        if dish is None:
            continue

        image_url = (
            request.build_absolute_uri(dish.image.url)
            if dish.image
            else ""
        )
        recommended.append(
            {
                "id": dish.id,
                "cart_id": f"dish-{dish.id}",
                "name": (
                    localized_dish_string(dish, "name", language)
                    if language
                    else dish.name
                ),
                "description": trim_card_text(
                    localized_dish_string(dish, "description", language)
                    if language
                    else dish.description
                ),
                "price": str(dish.price),
                "image_url": image_url,
                "url": f"{menu_url}#dish-{dish.id}",
                "category": (
                    localized_category_values(dish.category)[language]
                    if dish.category and language
                    else dish.category.name
                    if dish.category
                    else ""
                ),
            }
        )

    return recommended


def serialize_timestamp(value):
    return timezone.localtime(value).isoformat()


def serialize_chat_messages(session, request, language="", ordering_context=None):
    serialized = []

    for message in session.messages.order_by("created_at", "id"):
        dishes = []

        if message.role == ChatMessage.Role.ASSISTANT:
            dishes = serialize_recommended_dishes(
                message.recommended_dish_ids,
                request,
                language=language,
                session=session,
                ordering_context=ordering_context,
            )

        serialized.append(
            {
                "id": message.id,
                "role": message.role,
                "text": message.content,
                "created_at": serialize_timestamp(message.created_at),
                "dishes": dishes,
            }
        )

    return serialized


def serialize_chat_messages_for_export(session):
    return [
        {
            "id": message.id,
            "role": message.role,
            "text": message.content,
            "model": message.model_name,
            "recommended_dish_ids": message.recommended_dish_ids,
            "created_at": serialize_timestamp(message.created_at),
        }
        for message in session.messages.order_by("created_at", "id")
    ]


def serialize_usage_events_for_export(session):
    return [
        {
            "id": event.id,
            "status": event.status,
            "model": event.model_name,
            "limit_reason": event.limit_reason,
            "is_stream": event.is_stream,
            "prompt_chars": event.prompt_chars,
            "response_chars": event.response_chars,
            "estimated_prompt_tokens": event.estimated_prompt_tokens,
            "estimated_response_tokens": event.estimated_response_tokens,
            "estimated_total_tokens": event.estimated_total_tokens,
            "estimated_cost_micros": event.estimated_cost_micros,
            "actual_prompt_tokens": event.actual_prompt_tokens,
            "actual_response_tokens": event.actual_response_tokens,
            "actual_total_tokens": event.actual_total_tokens,
            "actual_cost_micros": event.actual_cost_micros,
            "provider_response_id": event.provider_response_id,
            "request_id": str(event.request_record_id) if event.request_record_id else None,
            "created_at": serialize_timestamp(event.created_at),
        }
        for event in session.usage_events.order_by("created_at", "id")
    ]


def request_result_payload(
    request_record,
    request,
    *,
    card_language,
    ordering_context,
    replayed,
):
    session = request_record.chat_session
    assistant_message = request_record.assistant_message
    user_message = request_record.user_message

    return {
        "answer": assistant_message.content,
        "recommended_dishes": serialize_recommended_dishes(
            assistant_message.recommended_dish_ids,
            request,
            language=card_language,
            session=session,
            ordering_context=ordering_context,
        ),
        "session_id": str(session.id),
        "model": assistant_message.model_name,
        "message_id": assistant_message.id,
        "created_at": serialize_timestamp(assistant_message.created_at),
        "user_message_id": user_message.id if user_message else None,
        "user_message_created_at": (
            serialize_timestamp(user_message.created_at)
            if user_message
            else None
        ),
        "request_id": str(request_record.id),
        "replayed": bool(replayed),
    }
