import json
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from google.genai import errors

from menu.models import Dish
from menu.translations import (
    localized_category_values,
    localized_dish_string,
    normalize_language,
)
from orders.models import Restaurant
from orders.services import CartValidationError, resolve_ordering_context

from .models import AIRequestRecord, AIUsageEvent, ChatMessage, ChatSession
from .privacy import get_ai_history_retention_days, prune_expired_ai_history
from .request_tracking import (
    AIRequestConflict,
    AIRequestIdError,
    build_request_fingerprint,
    get_existing_request_record,
    mark_request_record,
    normalize_request_id,
    request_owner_values,
    validate_existing_request_record,
)
from .services import (
    AIProviderUsage,
    AIServiceError,
    build_local_fallback_result,
    detect_response_language,
    generate_ai_answer,
    generate_ai_answer_stream,
    is_provider_timeout_error,
    parse_streamed_ai_response,
    provider_usage_from_response,
)
from .throttling import (
    acquire_ai_request_slot,
    acquire_ai_session_slot,
    acquire_ai_stream_slot,
    create_ai_usage_event,
    finish_ai_usage_event,
    reconcile_ai_quota_reservation,
    record_throttled_ai_request,
    refresh_ai_slot,
    release_ai_quota_reservation,
    release_ai_request_slot,
    release_ai_session_slot,
    release_ai_stream_slot,
    reserve_ai_request_quota,
)


logger = logging.getLogger(__name__)

MAX_PROMPT_LENGTH = 4000
MAX_RECOMMENDED_DISHES = 3

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
    unavailable_reasons = {
        "quota_store_unavailable",
        "guard_store_unavailable",
    }
    unavailable = decision.reason in unavailable_reasons
    response = _error_response(
        decision.message,
        status=503 if unavailable else 429,
        session=session,
        code="ai_guard_unavailable" if unavailable else "ai_rate_limited",
    )
    response["Retry-After"] = str(decision.retry_after)
    response["Cache-Control"] = "no-store"
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


def _create_session(request, prompt, ordering_context):
    if ordering_context is None:
        raise CartValidationError(
            "Для ИИ-ассистента нужен контекст ресторана.",
            code="restaurant_required",
        )

    session_data = {
        "title": prompt[:150],
        "session_key": _get_session_key(request),
        "restaurant_id": ordering_context.restaurant_id,
    }

    if request.user.is_authenticated:
        session_data["user"] = request.user

    session = ChatSession.objects.create(**session_data)
    session.ordering_context = ordering_context
    return session


def _apply_ordering_context(session, ordering_context):
    if ordering_context is None:
        return False

    if session.restaurant_id != ordering_context.restaurant_id:
        return False

    session.ordering_context = ordering_context
    return True


def _trim_card_text(value, max_length=130):
    value = " ".join(str(value or "").split())

    if len(value) <= max_length:
        return value

    return f"{value[: max_length - 1].rstrip()}..."


def _restaurant_id_for_ai(session=None, ordering_context=None):
    if ordering_context is not None:
        return ordering_context.restaurant_id

    if session is not None and session.restaurant_id:
        return session.restaurant_id

    raise ValueError("AI restaurant context is required.")


def _menu_url_for_recommendations(restaurant_id, ordering_context=None):
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


def _normalize_recommended_ids(values):
    normalized = []

    if not isinstance(values, (list, tuple)):
        return normalized

    for value in values:
        if not isinstance(value, int) or isinstance(value, bool):
            continue

        if value in normalized:
            continue

        normalized.append(value)

        if len(normalized) >= MAX_RECOMMENDED_DISHES:
            break

    return normalized


def _serialize_recommended_dishes(
    dish_ids,
    request,
    language="",
    session=None,
    ordering_context=None,
):
    dish_ids = _normalize_recommended_ids(dish_ids)

    if not dish_ids:
        return []

    language = normalize_language(language) if language else ""
    restaurant_id = _restaurant_id_for_ai(
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
    menu_url = _menu_url_for_recommendations(
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
                "description": _trim_card_text(
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


def _build_quota_fallback_answer(
    request,
    session,
    language="ru",
    ordering_context=None,
):
    result = build_local_fallback_result(session)
    return (
        result,
        _serialize_recommended_dishes(
            result.recommended_dish_ids,
            request,
            language=language,
            session=session,
            ordering_context=ordering_context,
        ),
    )


def _get_latest_session(request, ordering_context):
    if ordering_context is None:
        return None

    restaurant_id = ordering_context.restaurant_id

    if request.user.is_authenticated:
        return (
            ChatSession.objects.filter(
                user=request.user,
                restaurant_id=restaurant_id,
            )
            .order_by("-updated_at", "-created_at", "-id")
            .first()
        )

    session_key = request.session.session_key

    if not session_key:
        return None

    return (
        ChatSession.objects.filter(
            user__isnull=True,
            session_key=session_key,
            restaurant_id=restaurant_id,
        )
        .order_by("-updated_at", "-created_at", "-id")
        .first()
    )


def _serialize_timestamp(value):
    return timezone.localtime(value).isoformat()


def _serialize_chat_messages(session, request, language="", ordering_context=None):
    serialized = []

    for message in session.messages.order_by("created_at", "id"):
        dishes = []

        if message.role == ChatMessage.Role.ASSISTANT:
            dishes = _serialize_recommended_dishes(
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
            "recommended_dish_ids": message.recommended_dish_ids,
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
            "actual_prompt_tokens": event.actual_prompt_tokens,
            "actual_response_tokens": event.actual_response_tokens,
            "actual_total_tokens": event.actual_total_tokens,
            "actual_cost_micros": event.actual_cost_micros,
            "provider_response_id": event.provider_response_id,
            "request_id": str(event.request_record_id) if event.request_record_id else None,
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
            allow_missing=False,
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
        .select_related("restaurant")
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
                "restaurant": {
                    "id": session.restaurant_id,
                    "name": session.restaurant.name,
                    "slug": session.restaurant.slug,
                },
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

    AIUsageEvent.objects.filter(
        chat_session_id__in=session_ids,
    ).delete()

    if not session_id:
        AIUsageEvent.objects.filter(user=request.user).delete()

    AIRequestRecord.objects.filter(
        chat_session_id__in=session_ids,
    ).delete()

    sessions.delete()

    if _wants_json_response(request):
        return JsonResponse(
            {
                "deleted": deleted_count,
            }
        )

    messages.success(request, "История ИИ-диалогов удалена.")
    return redirect("accounts:profile")


def _request_conflict_response(error, session=None):
    response = _error_response(
        error.message,
        status=error.status,
        session=session,
        code=error.code,
    )
    if error.retry_after:
        response["Retry-After"] = str(error.retry_after)
    return response


def _request_result_payload(
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
        "recommended_dishes": _serialize_recommended_dishes(
            assistant_message.recommended_dish_ids,
            request,
            language=card_language,
            session=session,
            ordering_context=ordering_context,
        ),
        "session_id": str(session.id),
        "model": assistant_message.model_name,
        "message_id": assistant_message.id,
        "created_at": _serialize_timestamp(assistant_message.created_at),
        "user_message_id": user_message.id if user_message else None,
        "user_message_created_at": (
            _serialize_timestamp(user_message.created_at)
            if user_message
            else None
        ),
        "request_id": str(request_record.id),
        "replayed": bool(replayed),
    }


def _close_provider_stream(stream_handle):
    stream = getattr(stream_handle, "stream", None)
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("Could not close Gemini stream cleanly.", exc_info=True)


@require_POST
def ask(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _error_response("Передан некорректный JSON.", status=400)

    if not isinstance(payload, dict):
        return _error_response("Тело запроса должно быть JSON-объектом.", status=400)

    try:
        ordering_context = resolve_ordering_context(
            payload,
            allow_menu_context=True,
            allow_missing=False,
        )
    except CartValidationError as error:
        return _ordering_error_response(error)

    prompt_value = payload.get("prompt", "")
    if not isinstance(prompt_value, str):
        return _error_response("Сообщение должно быть строкой.", status=400)

    prompt = prompt_value.strip()
    if not prompt:
        return _error_response("Сообщение не может быть пустым.", status=400)
    if len(prompt) > MAX_PROMPT_LENGTH:
        return _error_response(
            f"Сообщение слишком длинное. Максимум - {MAX_PROMPT_LENGTH} символов.",
            status=400,
        )

    try:
        request_id = normalize_request_id(
            payload.get("request_id"),
            generate_if_missing=True,
        )
    except AIRequestIdError as error:
        return _error_response(str(error), status=400, code="invalid_ai_request_id")

    session_id = payload.get("session_id")
    language_value = payload.get("language")
    language = normalize_language(language_value) if language_value else ""
    response_language = detect_response_language(prompt, fallback=language or "ru")
    card_language = response_language if language_value else ""
    wants_stream = _wants_stream(request)
    session = None
    created_session = False

    # Ownership and tenant validation happen before any quota is reserved.
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

    fingerprint = build_request_fingerprint(
        prompt=prompt,
        language=language,
        session_id=session_id,
        ordering_context=ordering_context,
    )

    try:
        existing_request = get_existing_request_record(request, request_id)
        if existing_request is not None:
            outcome = validate_existing_request_record(
                existing_request,
                fingerprint=fingerprint,
                restaurant_id=ordering_context.restaurant_id,
            )
            if outcome == "replay":
                existing_request.chat_session.ordering_context = ordering_context
                return JsonResponse(
                    _request_result_payload(
                        existing_request,
                        request,
                        card_language=card_language,
                        ordering_context=ordering_context,
                        replayed=True,
                    )
                )
    except AIRequestConflict as error:
        return _request_conflict_response(error, session=session)

    request_slot = acquire_ai_request_slot(request_id)
    if not request_slot.allowed:
        if request_slot.reason == "guard_store_unavailable":
            return _rate_limited_response(request_slot, session=session)
        error = AIRequestConflict(
            request_slot.message,
            code="ai_request_in_progress",
            retry_after=request_slot.retry_after,
        )
        return _request_conflict_response(error, session=session)

    stream_slot = None
    session_slot = None
    quota_reservation = None
    request_record = None
    user_message = None
    usage_event = None
    request_lifecycle_started = False

    try:
        # Re-check after acquiring the unique request lease to close the race.
        existing_request = get_existing_request_record(request, request_id)
        if existing_request is not None:
            try:
                outcome = validate_existing_request_record(
                    existing_request,
                    fingerprint=fingerprint,
                    restaurant_id=ordering_context.restaurant_id,
                )
            except AIRequestConflict as error:
                return _request_conflict_response(error, session=session)
            if outcome == "replay":
                existing_request.chat_session.ordering_context = ordering_context
                return JsonResponse(
                    _request_result_payload(
                        existing_request,
                        request,
                        card_language=card_language,
                        ordering_context=ordering_context,
                        replayed=True,
                    )
                )

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

        if session is not None:
            session_slot = acquire_ai_session_slot(session)
            if not session_slot.allowed:
                release_ai_stream_slot(stream_slot)
                record_throttled_ai_request(
                    request,
                    prompt,
                    session_slot,
                    chat_session=session,
                    is_stream=wants_stream,
                )
                if session_slot.reason == "guard_store_unavailable":
                    return _rate_limited_response(session_slot, session=session)
                return _session_busy_response(session_slot, session=session)

        quota_reservation = reserve_ai_request_quota(request, prompt)
        if not quota_reservation.allowed:
            release_ai_stream_slot(stream_slot)
            release_ai_session_slot(session_slot)
            record_throttled_ai_request(
                request,
                prompt,
                quota_reservation,
                chat_session=session,
                is_stream=wants_stream,
            )
            return _rate_limited_response(quota_reservation, session=session)

        if session is None:
            session = _create_session(
                request,
                prompt,
                ordering_context=ordering_context,
            )
            created_session = True
            session_slot = acquire_ai_session_slot(session)
            if not session_slot.allowed:
                release_ai_quota_reservation(quota_reservation)
                release_ai_stream_slot(stream_slot)
                session.delete()
                created_session = False
                record_throttled_ai_request(
                    request,
                    prompt,
                    session_slot,
                    is_stream=wants_stream,
                )
                if session_slot.reason == "guard_store_unavailable":
                    return _rate_limited_response(session_slot, session=session)
                return _session_busy_response(session_slot, session=session)

        session.interface_language = language or "ru"
        session.response_language = response_language

        with transaction.atomic():
            user_message = ChatMessage.objects.create(
                session=session,
                role=ChatMessage.Role.USER,
                content=prompt,
            )
            request_record = AIRequestRecord.objects.create(
                id=request_id,
                **request_owner_values(request),
                restaurant_id=ordering_context.restaurant_id,
                chat_session=session,
                user_message=user_message,
                request_fingerprint=fingerprint,
                is_stream=wants_stream,
            )
            session.updated_at = timezone.now()
            session.save(update_fields=["updated_at"])
            usage_event = create_ai_usage_event(
                request,
                session,
                prompt,
                is_stream=wants_stream,
                request_record=request_record,
                quota_reservation=quota_reservation,
            )
        request_lifecycle_started = True
    except IntegrityError:
        release_ai_quota_reservation(quota_reservation)
        release_ai_stream_slot(stream_slot)
        release_ai_session_slot(session_slot)
        if created_session and session and not session.messages.exists():
            session.delete()
        try:
            existing_request = get_existing_request_record(request, request_id)
            if existing_request is not None:
                outcome = validate_existing_request_record(
                    existing_request,
                    fingerprint=fingerprint,
                    restaurant_id=ordering_context.restaurant_id,
                )
                if outcome == "replay":
                    existing_request.chat_session.ordering_context = ordering_context
                    return JsonResponse(
                        _request_result_payload(
                            existing_request,
                            request,
                            card_language=card_language,
                            ordering_context=ordering_context,
                            replayed=True,
                        )
                    )
        except AIRequestConflict as error:
            return _request_conflict_response(error, session=session)
        raise
    except Exception:
        release_ai_quota_reservation(quota_reservation)
        release_ai_stream_slot(stream_slot)
        release_ai_session_slot(session_slot)
        if created_session and session and not session.messages.exists():
            session.delete()
        logger.exception("AI request preflight failed.")
        return _error_response(
            "Не удалось подготовить запрос к ассистенту.",
            status=503,
            session=session,
            code="ai_request_preflight_failed",
        )
    finally:
        if not request_lifecycle_started:
            release_ai_request_slot(request_slot)

    if wants_stream:
        try:
            stream_handle = generate_ai_answer_stream(session)
        except AIServiceError as error:
            logger.exception("AI assistant streaming request failed.")
            release_ai_stream_slot(stream_slot)
            release_ai_session_slot(session_slot)
            release_ai_request_slot(request_slot)
            mark_request_record(
                request_record,
                status=AIRequestRecord.Status.FAILED,
                error_code=error.code,
            )
            finish_ai_usage_event(
                usage_event,
                AIUsageEvent.Status.FAILED,
                limit_reason=error.code,
            )
            if error.code == "ai_not_configured":
                release_ai_quota_reservation(quota_reservation)
            return _error_response(
                "ИИ-ассистент временно недоступен. Попробуйте отправить сообщение еще раз.",
                status=503,
                session=session,
                code=error.code,
            )
        except Exception:
            logger.exception("Unexpected AI stream initialization failure.")
            release_ai_stream_slot(stream_slot)
            release_ai_session_slot(session_slot)
            release_ai_request_slot(request_slot)
            mark_request_record(
                request_record,
                status=AIRequestRecord.Status.FAILED,
                error_code="stream_initialization_failed",
            )
            finish_ai_usage_event(
                usage_event,
                AIUsageEvent.Status.FAILED,
                limit_reason="stream_initialization_failed",
            )
            return _error_response(
                "ИИ-ассистент временно недоступен. Попробуйте отправить сообщение еще раз.",
                status=503,
                session=session,
                code="stream_initialization_failed",
            )

        def event_stream():
            raw_parts = []
            last_response = None
            finalized = False
            last_heartbeat = timezone.now()
            heartbeat_seconds = max(
                1,
                int(getattr(settings, "AI_STREAM_HEARTBEAT_SECONDS", 5)),
            )

            try:
                yield _stream_event(
                    "session",
                    session_id=str(session.id),
                    request_id=str(request_record.id),
                    user_message_id=user_message.id,
                    user_message_created_at=_serialize_timestamp(
                        user_message.created_at
                    ),
                )

                try:
                    for chunk in stream_handle.stream:
                        last_response = chunk
                        text = getattr(chunk, "text", None) or ""
                        if text:
                            raw_parts.append(text)

                        now = timezone.now()
                        if (now - last_heartbeat).total_seconds() >= heartbeat_seconds:
                            refresh_ai_slot(stream_slot)
                            refresh_ai_slot(session_slot)
                            refresh_ai_slot(request_slot)
                            AIRequestRecord.objects.filter(
                                pk=request_record.pk,
                                status=AIRequestRecord.Status.PROCESSING,
                            ).update(updated_at=now)
                            yield _stream_event(
                                "heartbeat",
                                request_id=str(request_record.id),
                            )
                            last_heartbeat = now
                except GeneratorExit:
                    raise
                except Exception as exc:
                    provider_usage = (
                        provider_usage_from_response(last_response)
                        if last_response is not None
                        else None
                    )
                    if _is_quota_error(exc) and not raw_parts:
                        logger.warning("Gemini quota exhausted during streaming response.")
                        fallback_result, fallback_dishes = _build_quota_fallback_answer(
                            request,
                            session,
                            language=card_language,
                            ordering_context=ordering_context,
                        )
                        assistant_message = ChatMessage.objects.create(
                            session=session,
                            role=ChatMessage.Role.ASSISTANT,
                            content=fallback_result.text,
                            model_name=fallback_result.model_name,
                            recommended_dish_ids=list(
                                fallback_result.recommended_dish_ids
                            ),
                        )
                        session.updated_at = timezone.now()
                        session.save(update_fields=["updated_at"])
                        mark_request_record(
                            request_record,
                            status=AIRequestRecord.Status.FALLBACK,
                            assistant_message=assistant_message,
                            error_code="provider_quota",
                        )
                        zero_usage = AIProviderUsage()
                        finish_ai_usage_event(
                            usage_event,
                            AIUsageEvent.Status.FALLBACK,
                            response_text=fallback_result.text,
                            model_name=fallback_result.model_name,
                            limit_reason="provider_quota",
                            provider_usage=zero_usage,
                        )
                        reconcile_ai_quota_reservation(
                            quota_reservation,
                            zero_usage,
                        )
                        finalized = True
                        yield _stream_event("delta", text=fallback_result.text)
                        yield _stream_event(
                            "done",
                            recommended_dishes=fallback_dishes,
                            session_id=str(session.id),
                            request_id=str(request_record.id),
                            model=fallback_result.model_name,
                            message_id=assistant_message.id,
                            created_at=_serialize_timestamp(
                                assistant_message.created_at
                            ),
                        )
                        return

                    reason = (
                        "provider_timeout"
                        if is_provider_timeout_error(exc)
                        else "stream_interrupted"
                    )
                    logger.warning(
                        "AI assistant stream interrupted: %s",
                        reason,
                        exc_info=True,
                    )
                    mark_request_record(
                        request_record,
                        status=AIRequestRecord.Status.FAILED,
                        error_code=reason,
                    )
                    finish_ai_usage_event(
                        usage_event,
                        AIUsageEvent.Status.FAILED,
                        model_name=stream_handle.model_name,
                        limit_reason=reason,
                        provider_usage=provider_usage,
                    )
                    if provider_usage is not None:
                        reconcile_ai_quota_reservation(
                            quota_reservation,
                            provider_usage,
                        )
                    finalized = True
                    yield _stream_event(
                        "error",
                        error="Ответ прервался. Попробуйте отправить сообщение еще раз.",
                        session_id=str(session.id),
                        request_id=str(request_record.id),
                    )
                    return

                try:
                    result = parse_streamed_ai_response(
                        stream_handle,
                        "".join(raw_parts),
                        response=last_response,
                    )
                except Exception:
                    logger.exception(
                        "AI assistant returned invalid structured stream data."
                    )
                    provider_usage = (
                        provider_usage_from_response(last_response)
                        if last_response is not None
                        else None
                    )
                    mark_request_record(
                        request_record,
                        status=AIRequestRecord.Status.FAILED,
                        error_code="invalid_structured_response",
                    )
                    finish_ai_usage_event(
                        usage_event,
                        AIUsageEvent.Status.FAILED,
                        model_name=stream_handle.model_name,
                        limit_reason="invalid_structured_response",
                        provider_usage=provider_usage,
                    )
                    if provider_usage is not None:
                        reconcile_ai_quota_reservation(
                            quota_reservation,
                            provider_usage,
                        )
                    finalized = True
                    yield _stream_event(
                        "error",
                        error="Не удалось проверить ответ ассистента. Попробуйте ещё раз.",
                        session_id=str(session.id),
                        request_id=str(request_record.id),
                    )
                    return

                with transaction.atomic():
                    assistant_message = ChatMessage.objects.create(
                        session=session,
                        role=ChatMessage.Role.ASSISTANT,
                        content=result.text,
                        model_name=result.model_name,
                        recommended_dish_ids=list(result.recommended_dish_ids),
                    )
                    session.updated_at = timezone.now()
                    session.save(update_fields=["updated_at"])
                    mark_request_record(
                        request_record,
                        status=AIRequestRecord.Status.COMPLETED,
                        assistant_message=assistant_message,
                    )

                finish_ai_usage_event(
                    usage_event,
                    AIUsageEvent.Status.COMPLETED,
                    response_text=result.text,
                    model_name=result.model_name,
                    provider_usage=result.provider_usage,
                )
                reconcile_ai_quota_reservation(
                    quota_reservation,
                    result.provider_usage,
                )
                finalized = True
                yield _stream_event("delta", text=result.text)
                yield _stream_event(
                    "done",
                    recommended_dishes=_serialize_recommended_dishes(
                        result.recommended_dish_ids,
                        request,
                        language=card_language,
                        session=session,
                        ordering_context=ordering_context,
                    ),
                    session_id=str(session.id),
                    request_id=str(request_record.id),
                    model=result.model_name,
                    message_id=assistant_message.id,
                    created_at=_serialize_timestamp(assistant_message.created_at),
                )
            except GeneratorExit:
                if not finalized:
                    mark_request_record(
                        request_record,
                        status=AIRequestRecord.Status.CANCELED,
                        error_code="client_disconnected",
                    )
                    provider_usage = (
                        provider_usage_from_response(last_response)
                        if last_response is not None
                        else None
                    )
                    finish_ai_usage_event(
                        usage_event,
                        AIUsageEvent.Status.CANCELED,
                        model_name=stream_handle.model_name,
                        limit_reason="client_disconnected",
                        provider_usage=provider_usage,
                    )
                    if provider_usage is not None:
                        reconcile_ai_quota_reservation(
                            quota_reservation,
                            provider_usage,
                        )
                raise
            except Exception:
                logger.exception("Unexpected AI streaming lifecycle failure.")
                if not finalized:
                    mark_request_record(
                        request_record,
                        status=AIRequestRecord.Status.FAILED,
                        error_code="stream_lifecycle_error",
                    )
                    finish_ai_usage_event(
                        usage_event,
                        AIUsageEvent.Status.FAILED,
                        model_name=stream_handle.model_name,
                        limit_reason="stream_lifecycle_error",
                    )
                raise
            finally:
                _close_provider_stream(stream_handle)
                release_ai_stream_slot(stream_slot)
                release_ai_session_slot(session_slot)
                release_ai_request_slot(request_slot)

        response = StreamingHttpResponse(
            event_stream(),
            content_type="application/x-ndjson; charset=utf-8",
        )
        response["X-AI-Request-ID"] = str(request_record.id)
        response["Cache-Control"] = "no-store, private"
        return response

    try:
        result = generate_ai_answer(session)
    except AIServiceError as error:
        logger.exception("AI assistant request failed.")
        release_ai_session_slot(session_slot)
        release_ai_request_slot(request_slot)
        mark_request_record(
            request_record,
            status=AIRequestRecord.Status.FAILED,
            error_code=error.code,
        )
        finish_ai_usage_event(
            usage_event,
            AIUsageEvent.Status.FAILED,
            limit_reason=error.code,
        )
        if error.code == "ai_not_configured":
            release_ai_quota_reservation(quota_reservation)
        return _error_response(
            "ИИ-ассистент временно недоступен. Попробуйте отправить сообщение еще раз.",
            status=503,
            session=session,
            code=error.code,
        )
    except Exception:
        logger.exception("Unexpected AI request failure.")
        release_ai_session_slot(session_slot)
        release_ai_request_slot(request_slot)
        mark_request_record(
            request_record,
            status=AIRequestRecord.Status.FAILED,
            error_code="ai_request_failed",
        )
        finish_ai_usage_event(
            usage_event,
            AIUsageEvent.Status.FAILED,
            limit_reason="ai_request_failed",
        )
        return _error_response(
            "ИИ-ассистент временно недоступен. Попробуйте отправить сообщение еще раз.",
            status=503,
            session=session,
            code="ai_request_failed",
        )

    try:
        with transaction.atomic():
            assistant_message = ChatMessage.objects.create(
                session=session,
                role=ChatMessage.Role.ASSISTANT,
                content=result.text,
                model_name=result.model_name,
                recommended_dish_ids=list(result.recommended_dish_ids),
            )
            session.updated_at = timezone.now()
            session.save(update_fields=["updated_at"])
            mark_request_record(
                request_record,
                status=AIRequestRecord.Status.COMPLETED,
                assistant_message=assistant_message,
            )
        finish_ai_usage_event(
            usage_event,
            AIUsageEvent.Status.COMPLETED,
            response_text=assistant_message.content,
            model_name=result.model_name,
            provider_usage=result.provider_usage,
        )
        reconcile_ai_quota_reservation(
            quota_reservation,
            result.provider_usage,
        )
    except Exception:
        logger.exception("Could not persist AI assistant response.")
        mark_request_record(
            request_record,
            status=AIRequestRecord.Status.FAILED,
            error_code="response_persistence_failed",
        )
        finish_ai_usage_event(
            usage_event,
            AIUsageEvent.Status.FAILED,
            model_name=result.model_name,
            limit_reason="response_persistence_failed",
            provider_usage=result.provider_usage,
        )
        reconcile_ai_quota_reservation(
            quota_reservation,
            result.provider_usage,
        )
        return _error_response(
            "Ответ получен, но не удалось безопасно сохранить диалог.",
            status=503,
            session=session,
            code="response_persistence_failed",
        )
    finally:
        release_ai_session_slot(session_slot)
        release_ai_request_slot(request_slot)

    return JsonResponse(
        _request_result_payload(
            request_record,
            request,
            card_language=card_language,
            ordering_context=ordering_context,
            replayed=False,
        ),
        status=200,
    )
