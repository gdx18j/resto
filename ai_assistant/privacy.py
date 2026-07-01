from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import AIUsageEvent, ChatSession


DEFAULT_AI_HISTORY_RETENTION_DAYS = 180


def get_ai_history_retention_days():
    raw_value = getattr(
        settings,
        "AI_HISTORY_RETENTION_DAYS",
        DEFAULT_AI_HISTORY_RETENTION_DAYS,
    )

    try:
        return max(int(raw_value), 0)
    except (TypeError, ValueError):
        return DEFAULT_AI_HISTORY_RETENTION_DAYS


def get_ai_history_cutoff():
    retention_days = get_ai_history_retention_days()

    if retention_days <= 0:
        return None

    return timezone.now() - timedelta(days=retention_days)


def prune_expired_ai_history(user=None, session_key=""):
    cutoff = get_ai_history_cutoff()

    if cutoff is None:
        return 0

    sessions = ChatSession.objects.filter(updated_at__lt=cutoff)

    if user is not None and getattr(user, "is_authenticated", False):
        sessions = sessions.filter(user=user)
        AIUsageEvent.objects.filter(
            user=user,
            created_at__lt=cutoff,
        ).delete()
    elif session_key:
        sessions = sessions.filter(
            user__isnull=True,
            session_key=session_key,
        )
        AIUsageEvent.objects.filter(
            user__isnull=True,
            session_key=session_key,
            created_at__lt=cutoff,
        ).delete()
    else:
        AIUsageEvent.objects.filter(created_at__lt=cutoff).delete()

    deleted_count, _ = sessions.delete()
    return deleted_count
