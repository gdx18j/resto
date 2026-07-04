from django.http import JsonResponse


def error_response(message, status, session=None, code=None):
    payload = {
        "error": message,
    }

    if code:
        payload["code"] = code

    if session:
        payload["session_id"] = str(session.id)

    return JsonResponse(payload, status=status)


def ordering_error_response(error, session=None):
    return error_response(
        error.message,
        status=error.status,
        session=session,
        code=error.code,
    )


def rate_limited_response(decision, session=None):
    unavailable_reasons = {
        "quota_store_unavailable",
        "guard_store_unavailable",
    }
    unavailable = decision.reason in unavailable_reasons
    response = error_response(
        decision.message,
        status=503 if unavailable else 429,
        session=session,
        code="ai_guard_unavailable" if unavailable else "ai_rate_limited",
    )
    response["Retry-After"] = str(decision.retry_after)
    response["Cache-Control"] = "no-store"
    return response


def session_busy_response(decision, session):
    response = error_response(
        decision.message,
        status=409,
        session=session,
        code="ai_session_busy",
    )
    response["Retry-After"] = str(decision.retry_after)
    return response


def request_conflict_response(error, session=None):
    response = error_response(
        error.message,
        status=error.status,
        session=session,
        code=error.code,
    )
    if error.retry_after:
        response["Retry-After"] = str(error.retry_after)
    return response
