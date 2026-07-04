from google.genai import errors

from .presentation import serialize_recommended_dishes
from .services import build_local_fallback_result


def is_quota_error(exc):
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


def build_quota_fallback_answer(
    request,
    session,
    language="ru",
    ordering_context=None,
):
    result = build_local_fallback_result(session)
    return (
        result,
        serialize_recommended_dishes(
            result.recommended_dish_ids,
            request,
            language=language,
            session=session,
            ordering_context=ordering_context,
        ),
    )
