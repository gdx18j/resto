import hashlib
import json
import uuid

from django.conf import settings
from django.utils import timezone

from .models import AIRequestRecord
from .throttling import ensure_request_session_key


class AIRequestIdError(ValueError):
    pass


class AIRequestConflict(ValueError):
    def __init__(self, message, *, code, status=409, retry_after=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.retry_after = retry_after


def normalize_request_id(value, *, generate_if_missing=False):
    if value in {None, ""} and generate_if_missing:
        return uuid.uuid4()

    if isinstance(value, uuid.UUID):
        return value

    if not isinstance(value, str):
        raise AIRequestIdError("request_id должен быть UUID-строкой.")

    try:
        return uuid.UUID(value.strip())
    except (AttributeError, ValueError, TypeError) as exc:
        raise AIRequestIdError("Передан некорректный request_id.") from exc


def build_request_fingerprint(
    *,
    prompt,
    language,
    session_id,
    ordering_context,
):
    payload = {
        "prompt": str(prompt),
        "language": str(language or ""),
        "session_id": str(session_id or ""),
        "restaurant_id": ordering_context.restaurant_id,
        "table_id": ordering_context.table_id,
        "source": ordering_context.source,
        "table_token_version": ordering_context.table_token_version,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def request_owner_values(request):
    session_key = ensure_request_session_key(request)
    return {
        "user": request.user if request.user.is_authenticated else None,
        "session_key": session_key,
    }


def request_record_belongs_to_request(record, request):
    if request.user.is_authenticated:
        if record.user_id == request.user.pk:
            return True
        return record.user_id is None and record.session_key == ensure_request_session_key(
            request
        )

    return (
        record.user_id is None
        and record.session_key == ensure_request_session_key(request)
    )


def get_existing_request_record(request, request_id):
    record = (
        AIRequestRecord.objects.select_related(
            "chat_session",
            "user_message",
            "assistant_message",
            "restaurant",
        )
        .filter(pk=request_id)
        .first()
    )

    if record is None:
        return None

    if not request_record_belongs_to_request(record, request):
        raise AIRequestConflict(
            "Этот request_id уже используется другим клиентом.",
            code="ai_request_owner_conflict",
        )

    return record


def validate_existing_request_record(
    record,
    *,
    fingerprint,
    restaurant_id,
):
    if record.request_fingerprint != fingerprint:
        raise AIRequestConflict(
            "request_id уже использован для другого запроса.",
            code="ai_request_payload_conflict",
        )

    if record.restaurant_id != restaurant_id:
        raise AIRequestConflict(
            "request_id относится к другому ресторану.",
            code="ai_request_restaurant_conflict",
        )

    if record.status in {
        AIRequestRecord.Status.COMPLETED,
        AIRequestRecord.Status.FALLBACK,
    }:
        if record.assistant_message_id and record.chat_session_id:
            return "replay"

        raise AIRequestConflict(
            "Завершенный AI-запрос поврежден и не может быть воспроизведен.",
            code="ai_request_result_missing",
        )

    if record.status == AIRequestRecord.Status.PROCESSING:
        stale_seconds = max(
            30,
            int(getattr(settings, "AI_REQUEST_STALE_SECONDS", 180)),
        )
        age = (timezone.now() - record.updated_at).total_seconds()

        if age <= stale_seconds:
            raise AIRequestConflict(
                "Этот запрос уже выполняется.",
                code="ai_request_in_progress",
                retry_after=min(stale_seconds, 15),
            )

        record.status = AIRequestRecord.Status.FAILED
        record.error_code = "stale_processing_request"
        record.completed_at = timezone.now()
        record.save(
            update_fields=[
                "status",
                "error_code",
                "completed_at",
                "updated_at",
            ]
        )

    raise AIRequestConflict(
        "Этот request_id относится к завершившемуся запросу. Отправьте новый запрос.",
        code="ai_request_not_reusable",
    )


def mark_request_record(
    record,
    *,
    status,
    assistant_message=None,
    error_code="",
):
    if record is None:
        return None

    record.status = status
    record.error_code = str(error_code or "")[:120]
    record.completed_at = timezone.now()

    update_fields = [
        "status",
        "error_code",
        "completed_at",
        "updated_at",
    ]

    if assistant_message is not None:
        record.assistant_message = assistant_message
        update_fields.append("assistant_message")

    record.save(update_fields=update_fields)
    return record
