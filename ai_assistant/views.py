import json
import logging

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from menu.models import Dish

from .models import ChatMessage, ChatSession
from .services import AIServiceError, generate_ai_answer


logger = logging.getLogger(__name__)

MAX_PROMPT_LENGTH = 4000
MAX_RECOMMENDED_DISHES = 3


def _error_response(message, status, session=None):
    payload = {
        "error": message,
    }

    if session:
        payload["session_id"] = str(session.id)

    return JsonResponse(payload, status=status)


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


def _create_session(request, prompt):
    session_key = _get_session_key(request)
    session_data = {
        "title": prompt[:150],
        "session_key": session_key,
    }

    if request.user.is_authenticated:
        session_data["user"] = request.user

    return ChatSession.objects.create(**session_data)


def _trim_card_text(value, max_length=130):
    value = " ".join(str(value or "").split())

    if len(value) <= max_length:
        return value

    return f"{value[: max_length - 1].rstrip()}..."


def _serialize_recommended_dishes(answer, request):
    answer_index = str(answer or "").casefold()

    if not answer_index:
        return []

    dishes = (
        Dish.objects.filter(
            is_active=True,
            is_available=True,
        )
        .select_related("category")
        .order_by("name")
    )

    matches = []

    for dish in dishes:
        name = dish.name.strip()

        if len(name) < 3:
            continue

        position = answer_index.find(name.casefold())

        if position == -1:
            continue

        image_url = ""

        if dish.image:
            image_url = request.build_absolute_uri(dish.image.url)

        matches.append(
            {
                "position": position,
                "name_length": len(name),
                "dish": dish,
                "image_url": image_url,
            }
        )

    matches.sort(key=lambda item: (item["position"], -item["name_length"]))

    recommended = []
    seen_ids = set()
    menu_url = reverse("menu:dish_list")

    for match in matches:
        dish = match["dish"]

        if dish.id in seen_ids:
            continue

        seen_ids.add(dish.id)
        recommended.append(
            {
                "id": dish.id,
                "name": dish.name,
                "description": _trim_card_text(dish.description),
                "price": str(dish.price),
                "image_url": match["image_url"],
                "url": f"{menu_url}#dish-{dish.id}",
                "category": dish.category.name if dish.category else "",
            }
        )

        if len(recommended) >= MAX_RECOMMENDED_DISHES:
            break

    return recommended


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

    prompt_value = payload.get("prompt", "")

    if not isinstance(prompt_value, str):
        return _error_response(
            "Сообщение должно быть строкой.",
            status=400,
        )

    prompt = prompt_value.strip()
    session_id = payload.get("session_id")

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

    if session_id:
        session = _get_existing_session(request, session_id)

        if session is None:
            return _error_response(
                "Диалог не найден. Начните новый чат.",
                status=404,
            )
    else:
        session = _create_session(request, prompt)

    ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.USER,
        content=prompt,
    )

    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    try:
        result = generate_ai_answer(session)
    except AIServiceError:
        logger.exception("AI assistant request failed.")
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

    return JsonResponse(
        {
            "answer": assistant_message.content,
            "recommended_dishes": _serialize_recommended_dishes(
                assistant_message.content,
                request,
            ),
            "session_id": str(session.id),
            "model": result.model_name,
            "message_id": assistant_message.id,
        },
        status=200,
    )
