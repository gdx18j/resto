import json
import logging
import unicodedata
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from google.genai import errors

from menu.models import Dish, get_default_restaurant_id
from menu.translations import (
    localized_category_values,
    localized_dish_string,
    normalize_language,
)
from orders.models import Restaurant
from orders.services import CartValidationError, resolve_ordering_context

from .models import AIUsageEvent, ChatMessage, ChatSession
from .privacy import get_ai_history_retention_days, prune_expired_ai_history
from .services import (
    AIServiceError,
    detect_response_language,
    generate_ai_answer,
    generate_ai_answer_stream,
)
from .throttling import (
    acquire_ai_session_slot,
    acquire_ai_stream_slot,
    check_ai_request_allowed,
    create_ai_usage_event,
    finish_ai_usage_event,
    record_throttled_ai_request,
    release_ai_session_slot,
    release_ai_stream_slot,
)


logger = logging.getLogger(__name__)

MAX_PROMPT_LENGTH = 4000
MAX_RECOMMENDED_DISHES = 3

SAVORY_REQUEST_MARKERS = (
    "пицц",
    "pizza",
    "pide",
    "шаур",
    "шаверм",
    "doner",
    "döner",
    "донер",
    "кебаб",
    "kebab",
    "wrap",
)

DRINK_OR_DESSERT_REQUEST_MARKERS = (
    "кофе",
    "coffee",
    "americano",
    "latte",
    "матча",
    "matcha",
    "напит",
    "drink",
    "десерт",
    "dessert",
    "слад",
)

NON_SAVORY_CATEGORY_MARKERS = (
    "кофе",
    "coffee",
    "напит",
    "drink",
    "матча",
    "matcha",
    "десерт",
    "dessert",
)

OTHER_OPTIONS_MARKERS = (
    "друг",
    "ещё",
    "еще",
    "another",
    "other",
    "else",
    "more",
)

REQUEST_RECOMMENDATION_RULES = (
    {
        "markers": ("пицц", "pizza", "pide"),
        "preferred_names": (
            "Focaccia",
            "Pompei Magnus",
            "Octavian",
            "Dana Sucuklu Peynirli Tost",
        ),
        "preferred_categories": ("Другие блюда", "Сэндвичи", "Тосты", "Меню"),
        "keywords": ("фокач", "focaccia", "чиабат", "ciabatta", "сыр", "cheese", "салями", "salami"),
    },
    {
        "markers": ("шаур", "шаверм", "doner", "döner", "донер", "кебаб", "kebab", "wrap"),
        "preferred_names": (
            "Crassus",
            "Pompei Magnus",
            "Octavian",
            "Dana Sucuklu Peynirli Tost",
        ),
        "preferred_categories": ("Сэндвичи", "Тосты", "Меню"),
        "keywords": ("чиабат", "ciabatta", "индей", "куриц", "салями", "сыр", "овощ", "соус"),
    },
)


def _error_response(message, status, session=None, code=None):
    payload = {
        "error": message,
    }

    if code:
        payload["code"] = code

    if session:
        payload["session_id"] = str(session.id)

    return JsonResponse(payload, status=status)


def _ordering_error_response(error, session=None):
    return _error_response(
        error.message,
        status=error.status,
        session=session,
        code=error.code,
    )


def _rate_limited_response(decision, session=None):
    response = _error_response(
        decision.message,
        status=429,
        session=session,
    )
    response["Retry-After"] = str(decision.retry_after)
    return response


def _session_busy_response(decision, session):
    response = _error_response(
        decision.message,
        status=409,
        session=session,
        code="ai_session_busy",
    )
    response["Retry-After"] = str(decision.retry_after)
    return response


def _get_session_key(request):
    if not request.session.session_key:
        request.session.save()

    return request.session.session_key


def _get_existing_session(request, session_id):
    try:
        if request.user.is_authenticated:
            session = ChatSession.objects.filter(
                id=session_id,
                user=request.user,
            ).first()

            if session:
                return session

            guest_session = ChatSession.objects.filter(
                id=session_id,
                user__isnull=True,
                session_key=_get_session_key(request),
            ).first()

            if guest_session:
                guest_session.user = request.user
                guest_session.save(update_fields=["user", "updated_at"])
                return guest_session

            return None

        return ChatSession.objects.filter(
            id=session_id,
            user__isnull=True,
            session_key=_get_session_key(request),
        ).first()
    except (ValidationError, ValueError, TypeError):
        return None


def _create_session(request, prompt, ordering_context=None):
    session_key = _get_session_key(request)
    session_data = {
        "title": prompt[:150],
        "session_key": session_key,
    }

    if request.user.is_authenticated:
        session_data["user"] = request.user

    if ordering_context is not None:
        session_data["restaurant_id"] = ordering_context.restaurant_id

    session = ChatSession.objects.create(**session_data)
    session.ordering_context = ordering_context
    return session


def _apply_ordering_context(session, ordering_context):
    if ordering_context is None:
        return True

    if session.restaurant_id and session.restaurant_id != ordering_context.restaurant_id:
        return False

    session.ordering_context = ordering_context

    if not session.restaurant_id:
        session.restaurant_id = ordering_context.restaurant_id
        session.save(update_fields=["restaurant", "updated_at"])

    return True


def _trim_card_text(value, max_length=130):
    value = " ".join(str(value or "").split())

    if len(value) <= max_length:
        return value

    return f"{value[: max_length - 1].rstrip()}..."


def _normalize_match_text(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.casefold().replace("ı", "i").strip()


def _request_matches_any(prompt_index, markers):
    return any(_normalize_match_text(marker) in prompt_index for marker in markers)


def _is_other_options_request(prompt_index):
    return _request_matches_any(prompt_index, OTHER_OPTIONS_MARKERS)


def _is_savory_alternative_request(prompt_index):
    return (
        _request_matches_any(prompt_index, SAVORY_REQUEST_MARKERS)
        and not _request_matches_any(prompt_index, DRINK_OR_DESSERT_REQUEST_MARKERS)
    )


def _dish_index_text(dish):
    ingredient_names = []

    for dish_ingredient in dish.dish_ingredients.all():
        ingredient_names.append(dish_ingredient.ingredient.name)

    return _normalize_match_text(
        " ".join(
            [
                dish.name,
                dish.category.name if dish.category else "",
                dish.description,
                " ".join(ingredient_names),
            ]
        )
    )


def _is_poor_savory_match(dish):
    category = _normalize_match_text(dish.category.name if dish.category else "")
    name = _normalize_match_text(dish.name)
    combined = f"{category} {name}"

    return any(marker in combined for marker in NON_SAVORY_CATEGORY_MARKERS)


def _restaurant_id_for_ai(session=None, ordering_context=None):
    if ordering_context is not None:
        return ordering_context.restaurant_id

    if session is not None and getattr(session, "restaurant_id", None):
        return session.restaurant_id

    return get_default_restaurant_id()


def _menu_url_for_recommendations(restaurant_id, ordering_context=None):
    if ordering_context is not None and ordering_context.table_token:
        return reverse("menu:table_menu", args=[ordering_context.table_token])

    restaurant_slug = (
        Restaurant.objects.filter(id=restaurant_id)
        .values_list("slug", flat=True)
        .first()
    )
    menu_url = reverse("menu:dish_list")

    if restaurant_slug:
        return f"{menu_url}?{urlencode({'restaurant': restaurant_slug})}"

    return menu_url


def _score_prompt_dish_match(prompt_index, dish):
    best_score = 0
    dish_name = _normalize_match_text(dish.name)
    category = _normalize_match_text(dish.category.name if dish.category else "")
    dish_index = _dish_index_text(dish)

    for rule in REQUEST_RECOMMENDATION_RULES:
        if not _request_matches_any(prompt_index, rule["markers"]):
            continue

        score = 0

        for index, preferred_name in enumerate(rule["preferred_names"]):
            if _normalize_match_text(preferred_name) in dish_name:
                score += 650 - index * 45
                break

        if any(_normalize_match_text(value) in category for value in rule["preferred_categories"]):
            score += 240

        for keyword in rule["keywords"]:
            if _normalize_match_text(keyword) in dish_index:
                score += 35

        best_score = max(best_score, score)

    return best_score


def _get_previous_mentioned_dish_ids(
    session,
    current_message_id=None,
    ordering_context=None,
):
    messages = session.messages.filter(role=ChatMessage.Role.ASSISTANT)

    if current_message_id:
        messages = messages.exclude(id=current_message_id)

    previous_text = _normalize_match_text(
        " ".join(messages.values_list("content", flat=True))
    )

    if not previous_text:
        return set()

    dish_ids = set()

    for dish in Dish.objects.filter(
        restaurant_id=_restaurant_id_for_ai(
            session=session,
            ordering_context=ordering_context,
        ),
        is_active=True,
        is_available=True,
    ):
        if _normalize_match_text(dish.name) in previous_text:
            dish_ids.add(dish.id)

    return dish_ids


def _serialize_recommended_dishes(
    answer,
    request,
    prompt="",
    excluded_dish_ids=None,
    language="",
    session=None,
    ordering_context=None,
):
    language = normalize_language(language) if language else ""
    answer_index = str(answer or "").casefold()
    prompt_index = _normalize_match_text(prompt)
    is_savory_request = _is_savory_alternative_request(prompt_index)
    excluded_dish_ids = set(excluded_dish_ids or [])
    restaurant_id = _restaurant_id_for_ai(
        session=session,
        ordering_context=ordering_context,
    )

    if not answer_index and not prompt_index:
        return []

    dishes = (
        Dish.objects.filter(
            restaurant_id=restaurant_id,
            is_active=True,
            is_available=True,
        )
        .select_related("category")
        .prefetch_related("dish_ingredients__ingredient")
        .order_by("name")
    )

    matches = []

    for dish in dishes:
        if dish.id in excluded_dish_ids:
            continue

        if is_savory_request and _is_poor_savory_match(dish):
            continue

        name = dish.name.strip()
        prompt_score = _score_prompt_dish_match(prompt_index, dish)

        if len(name) < 3 and not prompt_score:
            continue

        position = answer_index.find(name.casefold())

        if position == -1 and not prompt_score:
            continue

        image_url = ""

        if dish.image:
            image_url = request.build_absolute_uri(dish.image.url)

        matches.append(
            {
                "position": position if position != -1 else 100000,
                "name_length": len(name),
                "prompt_score": prompt_score,
                "dish": dish,
                "image_url": image_url,
            }
        )

    matches.sort(
        key=lambda item: (
            -item["prompt_score"],
            item["position"],
            -item["name_length"],
        )
    )

    recommended = []
    seen_ids = set()
    menu_url = _menu_url_for_recommendations(
        restaurant_id,
        ordering_context=ordering_context,
    )

    for match in matches:
        dish = match["dish"]

        if dish.id in seen_ids:
            continue

        seen_ids.add(dish.id)
        recommended.append(
            {
                "id": dish.id,
                "cart_id": f"dish-{dish.id}",
                "name": (
                    localized_dish_string(dish, "name", language)
                    if language
                    else dish.name
                ),
                "description": _trim_card_text(
                    localized_dish_string(dish, "description", language)
                    if language
                    else dish.description
                ),
                "price": str(dish.price),
                "image_url": match["image_url"],
                "url": f"{menu_url}#dish-{dish.id}",
                "category": (
                    localized_category_values(dish.category.name)[language]
                    if dish.category
                    and language
                    else dish.category.name
                    if dish.category
                    else ""
                ),
            }
        )

        if len(recommended) >= MAX_RECOMMENDED_DISHES:
            break

    return recommended


def _wants_stream(request):
    return (
        request.headers.get("X-AI-Stream") == "1"
        or "application/x-ndjson" in request.headers.get("Accept", "")
    )


def _stream_event(event_type, **payload):
    payload["type"] = event_type
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _is_quota_error(exc):
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    error_text = str(exc)

    return (
        isinstance(exc, errors.APIError)
        and status_code == 429
    ) or (
        status_code == 429
        or "RESOURCE_EXHAUSTED" in error_text
        or "Quota exceeded" in error_text
    )


def _get_excluded_dish_ids_for_prompt(
    session,
    prompt,
    current_message_id=None,
    ordering_context=None,
):
    if not _is_other_options_request(_normalize_match_text(prompt)):
        return None

    return _get_previous_mentioned_dish_ids(
        session,
        current_message_id=current_message_id,
        ordering_context=ordering_context,
    )


def _build_quota_fallback_answer(
    prompt,
    request,
    session,
    language="ru",
    ordering_context=None,
):
    prompt_index = _normalize_match_text(prompt)
    answer = (
        "Сейчас лимит ИИ временно исчерпан, поэтому отвечу по опубликованному меню без Gemini. "
        "Попробуйте отправить сообщение еще раз чуть позже."
    )

    if _request_matches_any(prompt_index, ("пицц", "pizza", "pide")):
        answer = (
            "Сейчас лимит ИИ временно исчерпан, но по меню могу подсказать: пиццы нет, "
            "самые близкие варианты - Focaccia, Pompei Magnus и Octavian."
        )
    elif _request_matches_any(
        prompt_index,
        ("шаур", "шаверм", "doner", "döner", "донер", "кебаб", "kebab", "wrap"),
    ):
        answer = (
            "Сейчас лимит ИИ временно исчерпан, но по меню могу подсказать: вместо шаурмы "
            "лучше посмотреть сэндвичи Crassus, Pompei Magnus или Octavian."
        )
    elif _request_matches_any(prompt_index, ("пив", "beer", "bira")):
        answer = (
            "Сейчас лимит ИИ временно исчерпан. Пива в опубликованном меню не вижу; "
            "из напитков можно посмотреть Limonata, Coca-Cola (33 cl.) или Schweppes (25 cl.)."
        )

    return (
        answer,
        _serialize_recommended_dishes(
            answer,
            request,
            prompt=prompt,
            excluded_dish_ids=_get_excluded_dish_ids_for_prompt(
                session,
                prompt,
                ordering_context=ordering_context,
            ),
            language=language,
            session=session,
            ordering_context=ordering_context,
        ),
    )


def _get_latest_session(request, ordering_context=None):
    restaurant_id = (
        ordering_context.restaurant_id
        if ordering_context is not None
        else None
    )

    if request.user.is_authenticated:
        sessions = ChatSession.objects.filter(user=request.user)

        if restaurant_id:
            sessions = sessions.filter(restaurant_id=restaurant_id)

        return (
            sessions
            .order_by("-updated_at", "-created_at", "-id")
            .first()
        )

    session_key = request.session.session_key

    if not session_key:
        return None

    sessions = ChatSession.objects.filter(
        user__isnull=True,
        session_key=session_key,
    )

    if restaurant_id:
        sessions = sessions.filter(restaurant_id=restaurant_id)

    return (
        sessions
        .order_by("-updated_at", "-created_at", "-id")
        .first()
    )


def _serialize_timestamp(value):
    return timezone.localtime(value).isoformat()


def _serialize_chat_messages(session, request, language="", ordering_context=None):
    serialized = []
    last_user_prompt = ""

    for message in session.messages.order_by("created_at", "id"):
        dishes = []

        if message.role == ChatMessage.Role.USER:
            last_user_prompt = message.content
        elif message.role == ChatMessage.Role.ASSISTANT:
            dishes = _serialize_recommended_dishes(
                message.content,
                request,
                prompt=last_user_prompt,
                language=language,
                session=session,
                ordering_context=ordering_context,
            )

        serialized.append(
            {
                "id": message.id,
                "role": message.role,
                "text": message.content,
                "created_at": _serialize_timestamp(message.created_at),
                "dishes": dishes,
            }
        )

    return serialized


def _serialize_chat_messages_for_export(session):
    return [
        {
            "id": message.id,
            "role": message.role,
            "text": message.content,
            "model": message.model_name,
            "created_at": _serialize_timestamp(message.created_at),
        }
        for message in session.messages.order_by("created_at", "id")
    ]


def _serialize_usage_events_for_export(session):
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
            "created_at": _serialize_timestamp(event.created_at),
        }
        for event in session.usage_events.order_by("created_at", "id")
    ]


def _wants_json_response(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


@require_GET
def history(request):
    if request.user.is_authenticated:
        prune_expired_ai_history(user=request.user)
    elif request.session.session_key:
        prune_expired_ai_history(session_key=request.session.session_key)

    try:
        ordering_context = resolve_ordering_context(
            request.GET,
            allow_menu_context=True,
            allow_missing=True,
        )
    except CartValidationError as error:
        return _ordering_error_response(error)

    language_value = request.GET.get("language")
    language = normalize_language(language_value) if language_value else ""
    session_id = request.GET.get("session_id")
    session = None

    if session_id:
        session = _get_existing_session(request, session_id)

        if (
            session is not None
            and ordering_context is not None
            and session.restaurant_id
            and session.restaurant_id != ordering_context.restaurant_id
        ):
            session = None

    if session is None:
        session = _get_latest_session(
            request,
            ordering_context=ordering_context,
        )

    if session is None:
        return JsonResponse(
            {
                "session_id": None,
                "messages": [],
            }
        )

    return JsonResponse(
        {
            "session_id": str(session.id),
            "title": session.title,
            "created_at": _serialize_timestamp(session.created_at),
            "updated_at": _serialize_timestamp(session.updated_at),
            "messages": _serialize_chat_messages(
                session,
                request,
                language=language,
                ordering_context=ordering_context,
            ),
        }
    )


@login_required
@require_GET
def export_history(request):
    prune_expired_ai_history(user=request.user)
    sessions = (
        ChatSession.objects.filter(user=request.user)
        .prefetch_related("messages", "usage_events")
        .order_by("created_at", "id")
    )
    payload = {
        "exported_at": _serialize_timestamp(timezone.now()),
        "history_retention_days": get_ai_history_retention_days(),
        "provider": "Gemini",
        "sessions": [
            {
                "id": str(session.id),
                "title": session.title,
                "created_at": _serialize_timestamp(session.created_at),
                "updated_at": _serialize_timestamp(session.updated_at),
                "messages": _serialize_chat_messages_for_export(session),
                "usage_events": _serialize_usage_events_for_export(session),
            }
            for session in sessions
        ],
    }
    response = JsonResponse(
        payload,
        json_dumps_params={
            "ensure_ascii": False,
            "indent": 2,
        },
    )
    response["Content-Disposition"] = 'attachment; filename="caesar-ai-history.json"'
    return response


@login_required
@require_POST
def delete_history(request):
    session_id = request.POST.get("session_id") or request.GET.get("session_id")
    sessions = ChatSession.objects.filter(user=request.user)

    if session_id:
        try:
            sessions = sessions.filter(id=session_id)
        except (ValidationError, ValueError, TypeError):
            if _wants_json_response(request):
                return JsonResponse(
                    {
                        "error": "Диалог не найден.",
                    },
                    status=404,
                )

            messages.error(request, "Диалог не найден.")
            return redirect("accounts:profile")

    session_ids = list(sessions.values_list("id", flat=True))
    deleted_count = len(session_ids)

    if session_id:
        AIUsageEvent.objects.filter(
            user=request.user,
            chat_session_id__in=session_ids,
        ).delete()
    else:
        AIUsageEvent.objects.filter(user=request.user).delete()

    sessions.delete()

    if _wants_json_response(request):
        return JsonResponse(
            {
                "deleted": deleted_count,
            }
        )

    messages.success(request, "История ИИ-диалогов удалена.")
    return redirect("accounts:profile")


@require_POST
def ask(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _error_response(
            "Передан некорректный JSON.",
            status=400,
        )

    if not isinstance(payload, dict):
        return _error_response(
            "Тело запроса должно быть JSON-объектом.",
            status=400,
        )

    try:
        ordering_context = resolve_ordering_context(
            payload,
            allow_menu_context=True,
            allow_missing=True,
        )
    except CartValidationError as error:
        return _ordering_error_response(error)

    prompt_value = payload.get("prompt", "")

    if not isinstance(prompt_value, str):
        return _error_response(
            "Сообщение должно быть строкой.",
            status=400,
        )

    prompt = prompt_value.strip()
    session_id = payload.get("session_id")
    language_value = payload.get("language")
    language = normalize_language(language_value) if language_value else ""
    response_language = detect_response_language(prompt, fallback=language or "ru")
    card_language = response_language if language_value else ""
    wants_stream = _wants_stream(request)

    if not prompt:
        return _error_response(
            "Сообщение не может быть пустым.",
            status=400,
        )

    if len(prompt) > MAX_PROMPT_LENGTH:
        return _error_response(
            f"Сообщение слишком длинное. Максимум - {MAX_PROMPT_LENGTH} символов.",
            status=400,
        )

    throttle_decision = check_ai_request_allowed(request, prompt)

    if not throttle_decision.allowed:
        record_throttled_ai_request(
            request,
            prompt,
            throttle_decision,
            is_stream=wants_stream,
        )
        return _rate_limited_response(throttle_decision)

    if session_id:
        session = _get_existing_session(request, session_id)

        if session is None:
            return _error_response(
                "Диалог не найден. Начните новый чат.",
                status=404,
            )

        if not _apply_ordering_context(session, ordering_context):
            return _error_response(
                "Диалог относится к другому ресторану. Начните новый чат.",
                status=409,
                session=session,
                code="ai_restaurant_context_conflict",
            )
    else:
        session = _create_session(
            request,
            prompt,
            ordering_context=ordering_context,
        )

    stream_slot = None

    if wants_stream:
        stream_slot = acquire_ai_stream_slot(request)

        if not stream_slot.allowed:
            record_throttled_ai_request(
                request,
                prompt,
                stream_slot,
                chat_session=session,
                is_stream=True,
            )
            return _rate_limited_response(stream_slot, session=session)

    session_slot = acquire_ai_session_slot(session)

    if not session_slot.allowed:
        if stream_slot:
            release_ai_stream_slot(stream_slot)

        record_throttled_ai_request(
            request,
            prompt,
            session_slot,
            chat_session=session,
            is_stream=wants_stream,
        )
        return _session_busy_response(session_slot, session=session)

    session.interface_language = language or "ru"
    session.response_language = response_language

    user_message = ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.USER,
        content=prompt,
    )

    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])
    usage_event = create_ai_usage_event(
        request,
        session,
        prompt,
        is_stream=wants_stream,
    )

    if wants_stream:
        try:
            model_name, stream = generate_ai_answer_stream(session)
        except AIServiceError:
            logger.exception("AI assistant streaming request failed.")
            release_ai_stream_slot(stream_slot)
            release_ai_session_slot(session_slot)
            finish_ai_usage_event(
                usage_event,
                AIUsageEvent.Status.FAILED,
                limit_reason="ai_service_error",
            )
            return _error_response(
                (
                    "ИИ-ассистент временно недоступен. "
                    "Попробуйте отправить сообщение еще раз."
                ),
                status=503,
                session=session,
            )

        def event_stream():
            answer_parts = []

            try:
                yield _stream_event(
                    "session",
                    session_id=str(session.id),
                    user_message_id=user_message.id,
                    user_message_created_at=_serialize_timestamp(user_message.created_at),
                )

                try:
                    for chunk in stream:
                        text = (getattr(chunk, "text", None) or "")

                        if not text:
                            continue

                        answer_parts.append(text)
                        yield _stream_event("delta", text=text)
                except Exception as exc:
                    if _is_quota_error(exc) and not answer_parts:
                        logger.warning("Gemini quota exhausted during streaming response.")
                        fallback_answer, fallback_dishes = _build_quota_fallback_answer(
                            prompt,
                            request,
                            session,
                            language=card_language,
                            ordering_context=ordering_context,
                        )
                        assistant_message = ChatMessage.objects.create(
                            session=session,
                            role=ChatMessage.Role.ASSISTANT,
                            content=fallback_answer,
                            model_name="local-quota-fallback",
                        )

                        session.updated_at = timezone.now()
                        session.save(update_fields=["updated_at"])
                        finish_ai_usage_event(
                            usage_event,
                            AIUsageEvent.Status.FALLBACK,
                            response_text=fallback_answer,
                            model_name=assistant_message.model_name,
                            limit_reason="provider_quota",
                        )

                        yield _stream_event("delta", text=fallback_answer)
                        yield _stream_event(
                            "done",
                            recommended_dishes=fallback_dishes,
                            session_id=str(session.id),
                            model=assistant_message.model_name,
                            message_id=assistant_message.id,
                            created_at=_serialize_timestamp(assistant_message.created_at),
                        )
                        return

                    logger.exception("AI assistant stream interrupted.")
                    finish_ai_usage_event(
                        usage_event,
                        AIUsageEvent.Status.FAILED,
                        response_text="".join(answer_parts),
                        model_name=model_name,
                        limit_reason="stream_interrupted",
                    )
                    yield _stream_event(
                        "error",
                        error=(
                            "Ответ прервался. Попробуйте отправить сообщение еще раз."
                        ),
                        session_id=str(session.id),
                    )
                    return

                answer = "".join(answer_parts).strip()

                if not answer:
                    finish_ai_usage_event(
                        usage_event,
                        AIUsageEvent.Status.FAILED,
                        model_name=model_name,
                        limit_reason="empty_response",
                    )
                    yield _stream_event(
                        "error",
                        error="Я не получил текст ответа. Попробуйте еще раз.",
                        session_id=str(session.id),
                    )
                    return

                assistant_message = ChatMessage.objects.create(
                    session=session,
                    role=ChatMessage.Role.ASSISTANT,
                    content=answer,
                    model_name=model_name,
                )

                session.updated_at = timezone.now()
                session.save(update_fields=["updated_at"])
                finish_ai_usage_event(
                    usage_event,
                    AIUsageEvent.Status.COMPLETED,
                    response_text=answer,
                    model_name=model_name,
                )

                yield _stream_event(
                    "done",
                    recommended_dishes=_serialize_recommended_dishes(
                        assistant_message.content,
                        request,
                        prompt,
                        excluded_dish_ids=_get_excluded_dish_ids_for_prompt(
                            session,
                            prompt,
                            current_message_id=assistant_message.id,
                            ordering_context=ordering_context,
                        ),
                        language=card_language,
                        session=session,
                        ordering_context=ordering_context,
                    ),
                    session_id=str(session.id),
                    model=model_name,
                    message_id=assistant_message.id,
                    created_at=_serialize_timestamp(assistant_message.created_at),
                )
            finally:
                release_ai_stream_slot(stream_slot)
                release_ai_session_slot(session_slot)

        return StreamingHttpResponse(
            event_stream(),
            content_type="application/x-ndjson; charset=utf-8",
        )

    try:
        result = generate_ai_answer(session)
    except AIServiceError:
        logger.exception("AI assistant request failed.")
        release_ai_session_slot(session_slot)
        finish_ai_usage_event(
            usage_event,
            AIUsageEvent.Status.FAILED,
            limit_reason="ai_service_error",
        )
        return _error_response(
            (
                "ИИ-ассистент временно недоступен. "
                "Попробуйте отправить сообщение еще раз."
            ),
            status=503,
            session=session,
        )

    assistant_message = ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.ASSISTANT,
        content=result.text,
        model_name=result.model_name,
    )

    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])
    finish_ai_usage_event(
        usage_event,
        AIUsageEvent.Status.COMPLETED,
        response_text=assistant_message.content,
        model_name=result.model_name,
    )
    release_ai_session_slot(session_slot)

    return JsonResponse(
        {
            "answer": assistant_message.content,
            "recommended_dishes": _serialize_recommended_dishes(
                assistant_message.content,
                request,
                prompt=prompt,
                excluded_dish_ids=_get_excluded_dish_ids_for_prompt(
                    session,
                    prompt,
                    current_message_id=assistant_message.id,
                    ordering_context=ordering_context,
                ),
                language=card_language,
                session=session,
                ordering_context=ordering_context,
            ),
            "session_id": str(session.id),
            "model": result.model_name,
            "message_id": assistant_message.id,
            "created_at": _serialize_timestamp(assistant_message.created_at),
            "user_message_id": user_message.id,
            "user_message_created_at": _serialize_timestamp(user_message.created_at),
        },
        status=200,
    )
