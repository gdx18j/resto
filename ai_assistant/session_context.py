from django.core.exceptions import ValidationError

from orders.services import CartValidationError

from .models import ChatSession


def get_session_key(request):
    if not request.session.session_key:
        request.session.save()

    return request.session.session_key


def get_existing_session(request, session_id):
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
                session_key=get_session_key(request),
            ).first()

            if guest_session:
                guest_session.user = request.user
                guest_session.save(update_fields=["user", "updated_at"])
                return guest_session

            return None

        return ChatSession.objects.filter(
            id=session_id,
            user__isnull=True,
            session_key=get_session_key(request),
        ).first()
    except (ValidationError, ValueError, TypeError):
        return None


def create_session(request, prompt, ordering_context):
    if ordering_context is None:
        raise CartValidationError(
            "Для ИИ-ассистента нужен контекст ресторана.",
            code="restaurant_required",
        )

    session_data = {
        "title": prompt[:150],
        "session_key": get_session_key(request),
        "restaurant_id": ordering_context.restaurant_id,
    }

    if request.user.is_authenticated:
        session_data["user"] = request.user

    session = ChatSession.objects.create(**session_data)
    session.ordering_context = ordering_context
    return session


def apply_ordering_context(session, ordering_context):
    if ordering_context is None:
        return False

    if session.restaurant_id != ordering_context.restaurant_id:
        return False

    session.ordering_context = ordering_context
    return True


def get_latest_session(request, ordering_context):
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
