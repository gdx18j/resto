import hashlib

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse


DEFAULT_MESSAGE = "Too many requests. Please try again later."


def _client_ip(request):
    if getattr(settings, "RATE_LIMIT_TRUST_PROXY_HEADERS", False):
        real_ip = request.META.get("HTTP_X_REAL_IP", "").strip()

        if real_ip:
            return real_ip

        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")

        if forwarded_for:
            return forwarded_for.split(",")[0].strip() or "unknown"

    return request.META.get("REMOTE_ADDR") or "unknown"


def _hash(value):
    raw_value = f"{settings.SECRET_KEY}:{value}".encode("utf-8")
    return hashlib.sha256(raw_value).hexdigest()


def _field_value(request, field_name):
    if not field_name:
        return ""

    value = request.POST.get(field_name, "")

    return str(value).strip().casefold()


def _actor_value(request):
    if request.user.is_authenticated:
        return f"user:{request.user.pk}"

    session_key = getattr(request.session, "session_key", "") or ""

    if session_key:
        return f"session:{session_key}"

    return "anonymous"


def _identity(request, rule):
    scope = rule.get("identity", "ip")
    ip = _client_ip(request)

    if scope == "actor":
        return _hash(_actor_value(request))

    if scope == "ip+actor":
        return _hash(f"{ip}:{_actor_value(request)}")

    if scope == "ip+field":
        field_value = _field_value(request, rule.get("field"))
        return _hash(f"{ip}:{rule.get('field', '')}:{field_value}")

    return _hash(ip)


def _cache_key(view_name, limit_name, identity):
    raw_key = f"{view_name}:{limit_name}:{identity}".encode("utf-8")
    return "rate_limit:" + hashlib.sha256(raw_key).hexdigest()


def _increment(key, timeout):
    if cache.add(key, 1, timeout=timeout):
        return 1

    try:
        return cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=timeout)
        return 1


def _limits(rule):
    for index, limit in enumerate(rule.get("limits", ())):
        name = limit.get("name") or f"limit_{index}"
        count = int(limit.get("limit", 0))
        window = int(limit.get("window", 60))

        if count > 0 and window > 0:
            yield name, count, window


def _wants_json(request, view_name):
    if view_name.startswith(("ai_assistant:", "orders:")):
        return True

    accept = request.headers.get("Accept", "")
    content_type = request.headers.get("Content-Type", "")

    return "application/json" in accept or "application/json" in content_type


def _rate_limited_response(request, view_name, retry_after, message):
    if _wants_json(request, view_name):
        response = JsonResponse(
            {
                "ok": False,
                "error": message,
                "code": "rate_limited",
                "retry_after": retry_after,
            },
            status=429,
        )
    else:
        response = HttpResponse(message, status=429, content_type="text/plain")

    response["Retry-After"] = str(retry_after)
    response["Cache-Control"] = "no-store"

    return response


class RateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, _view_func, _view_args, _view_kwargs):
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return None

        resolver_match = getattr(request, "resolver_match", None)
        view_name = getattr(resolver_match, "view_name", "")

        if not view_name:
            return None

        rule = getattr(settings, "RATE_LIMIT_RULES", {}).get(view_name)

        if not rule:
            return None

        methods = {method.upper() for method in rule.get("methods", ("POST",))}

        if request.method.upper() not in methods:
            return None

        identity = _identity(request, rule)
        message = rule.get(
            "message",
            getattr(settings, "RATE_LIMIT_MESSAGE", DEFAULT_MESSAGE),
        )

        for name, count, window in _limits(rule):
            current = _increment(_cache_key(view_name, name, identity), window)

            if current > count:
                return _rate_limited_response(
                    request,
                    view_name,
                    retry_after=window,
                    message=message,
                )

        return None
