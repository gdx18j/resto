import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import AIUsageEvent, ChatSession


DEFAULT_RATE_LIMIT_MESSAGE = (
    "Слишком много запросов к ИИ. Попробуйте отправить сообщение позже."
)


@dataclass(frozen=True)
class AIThrottleDecision:
    allowed: bool
    reason: str = ""
    message: str = ""
    retry_after: int = 60
    estimated_prompt_tokens: int = 0
    estimated_response_tokens: int = 0
    estimated_total_tokens: int = 0


@dataclass
class AIStreamSlot:
    allowed: bool
    keys: list[str] = field(default_factory=list)
    reason: str = ""
    message: str = ""
    retry_after: int = 60


def _setting_int(name, default):
    value = getattr(settings, name, default)

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _setting_bool(name, default=False):
    value = getattr(settings, name, default)

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_client_ip(request):
    if _setting_bool("AI_TRUST_X_FORWARDED_FOR", False):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")

        if forwarded_for:
            return forwarded_for.split(",")[0].strip() or "unknown"

    return request.META.get("REMOTE_ADDR") or "unknown"


def ensure_request_session_key(request):
    if not request.session.session_key:
        request.session.save()

    return request.session.session_key or ""


def get_request_actor(request):
    if request.user.is_authenticated:
        return "user", str(request.user.pk)

    return "session", ensure_request_session_key(request)


def _hash_identifier(value):
    raw_value = f"{settings.SECRET_KEY}:{value}".encode("utf-8")
    return hashlib.sha256(raw_value).hexdigest()


def get_request_ip_hash(request):
    return _hash_identifier(f"ip:{get_client_ip(request)}")


def _cache_key(*parts):
    joined = ":".join(str(part) for part in parts if str(part))
    return "ai_guard:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _seconds_until_next_utc_day():
    now = timezone.now()
    tomorrow = now.date() + timedelta(days=1)
    next_day = datetime.combine(
        tomorrow,
        time.min,
        tzinfo=now.tzinfo,
    )

    return max(int((next_day - now).total_seconds()), 60)


def _increment_cache_counter(key, amount=1, timeout=60):
    if amount <= 0:
        return cache.get(key, 0) or 0

    if cache.add(key, amount, timeout=timeout):
        return amount

    try:
        return cache.incr(key, amount)
    except ValueError:
        cache.add(key, amount, timeout=timeout)
        return amount


def _decrement_cache_counter(key):
    try:
        value = cache.decr(key)
    except ValueError:
        cache.delete(key)
        return 0

    if value <= 0:
        cache.delete(key)
        return 0

    return value


def estimate_tokens_from_text(value):
    value = str(value or "")

    if not value:
        return 0

    return max(1, math.ceil(len(value) / 4))


def get_estimated_response_tokens():
    default_value = min(
        _setting_int("AI_MAX_OUTPUT_TOKENS", 1000),
        600,
    )

    return max(
        1,
        _setting_int("AI_ESTIMATED_RESPONSE_TOKENS", default_value),
    )


def estimate_request_tokens(prompt):
    prompt_tokens = estimate_tokens_from_text(prompt)
    response_tokens = get_estimated_response_tokens()

    return (
        prompt_tokens,
        response_tokens,
        prompt_tokens + response_tokens,
    )


def estimate_cost_micros(total_tokens):
    cost_per_1000_tokens = _setting_int(
        "AI_ESTIMATED_COST_MICROS_PER_1000_TOKENS",
        0,
    )

    if cost_per_1000_tokens <= 0 or total_tokens <= 0:
        return 0

    return math.ceil(total_tokens * cost_per_1000_tokens / 1000)


def _deny(reason, retry_after=60, token_estimates=None):
    prompt_tokens, response_tokens, total_tokens = token_estimates or (0, 0, 0)

    return AIThrottleDecision(
        allowed=False,
        reason=reason,
        message=DEFAULT_RATE_LIMIT_MESSAGE,
        retry_after=max(1, int(retry_after)),
        estimated_prompt_tokens=prompt_tokens,
        estimated_response_tokens=response_tokens,
        estimated_total_tokens=total_tokens,
    )


def _allow(token_estimates):
    prompt_tokens, response_tokens, total_tokens = token_estimates

    return AIThrottleDecision(
        allowed=True,
        estimated_prompt_tokens=prompt_tokens,
        estimated_response_tokens=response_tokens,
        estimated_total_tokens=total_tokens,
    )


def _block_key(scope, identifier):
    return _cache_key("block", scope, identifier)


def _is_blocked(scope, identifier):
    return bool(cache.get(_block_key(scope, identifier)))


def _register_violation(scope, identifier):
    threshold = _setting_int("AI_ABUSE_BLOCK_THRESHOLD", 8)
    block_seconds = _setting_int("AI_ABUSE_BLOCK_SECONDS", 600)

    if threshold <= 0 or block_seconds <= 0:
        return

    key = _cache_key("violation", scope, identifier)
    count = _increment_cache_counter(
        key,
        amount=1,
        timeout=3600,
    )

    if count >= threshold:
        cache.set(
            _block_key(scope, identifier),
            "1",
            timeout=block_seconds,
        )


def _register_scoped_violation(scope, identifier):
    if "ip" in scope:
        _register_violation("ip", identifier)
        return

    if "actor" in scope:
        _register_violation("actor", identifier)


def _check_counter(scope, identifier, amount, limit, timeout, reason):
    if limit <= 0:
        return None

    key = _cache_key(scope, identifier)
    current = _increment_cache_counter(
        key,
        amount=amount,
        timeout=timeout,
    )

    if current > limit:
        _register_scoped_violation(scope, identifier)
        return reason

    return None


def check_ai_request_allowed(request, prompt):
    ip = get_client_ip(request)
    actor_kind, actor_id = get_request_actor(request)
    actor_identifier = f"{actor_kind}:{actor_id}"
    token_estimates = estimate_request_tokens(prompt)
    _, _, total_tokens = token_estimates
    estimated_cost = estimate_cost_micros(total_tokens)

    if _is_blocked("ip", ip) or _is_blocked("actor", actor_identifier):
        return _deny(
            "abuse_block",
            retry_after=_setting_int("AI_ABUSE_BLOCK_SECONDS", 600),
            token_estimates=token_estimates,
        )

    window_seconds = _setting_int("AI_RATE_LIMIT_WINDOW_SECONDS", 60)
    daily_seconds = _seconds_until_next_utc_day()
    is_authenticated = request.user.is_authenticated
    actor_minute_limit = (
        _setting_int("AI_RATE_LIMIT_USER_PER_MINUTE", 12)
        if is_authenticated
        else _setting_int("AI_RATE_LIMIT_GUEST_PER_MINUTE", 6)
    )
    actor_daily_limit = (
        _setting_int("AI_DAILY_QUOTA_USER", 80)
        if is_authenticated
        else _setting_int("AI_DAILY_QUOTA_GUEST", 25)
    )
    actor_token_budget = (
        _setting_int("AI_DAILY_TOKEN_BUDGET_USER", 100000)
        if is_authenticated
        else _setting_int("AI_DAILY_TOKEN_BUDGET_GUEST", 30000)
    )
    actor_cost_budget = (
        _setting_int("AI_DAILY_COST_BUDGET_MICROS_USER", 0)
        if is_authenticated
        else _setting_int("AI_DAILY_COST_BUDGET_MICROS_GUEST", 0)
    )
    checks = (
        (
            "minute:ip",
            ip,
            1,
            _setting_int("AI_RATE_LIMIT_IP_PER_MINUTE", 30),
            window_seconds,
            "ip_minute_limit",
        ),
        (
            "minute:actor",
            actor_identifier,
            1,
            actor_minute_limit,
            window_seconds,
            "actor_minute_limit",
        ),
        (
            "daily:ip",
            f"{timezone.now().date()}:{ip}",
            1,
            _setting_int("AI_DAILY_QUOTA_IP", 120),
            daily_seconds,
            "ip_daily_quota",
        ),
        (
            "daily:actor",
            f"{timezone.now().date()}:{actor_identifier}",
            1,
            actor_daily_limit,
            daily_seconds,
            "actor_daily_quota",
        ),
        (
            "daily_tokens:ip",
            f"{timezone.now().date()}:{ip}",
            total_tokens,
            _setting_int("AI_DAILY_TOKEN_BUDGET_IP", 160000),
            daily_seconds,
            "ip_daily_token_budget",
        ),
        (
            "daily_tokens:actor",
            f"{timezone.now().date()}:{actor_identifier}",
            total_tokens,
            actor_token_budget,
            daily_seconds,
            "actor_daily_token_budget",
        ),
        (
            "daily_cost:ip",
            f"{timezone.now().date()}:{ip}",
            estimated_cost,
            _setting_int("AI_DAILY_COST_BUDGET_MICROS_IP", 0),
            daily_seconds,
            "ip_daily_cost_budget",
        ),
        (
            "daily_cost:actor",
            f"{timezone.now().date()}:{actor_identifier}",
            estimated_cost,
            actor_cost_budget,
            daily_seconds,
            "actor_daily_cost_budget",
        ),
    )

    for scope, identifier, amount, limit, timeout, reason in checks:
        failed_reason = _check_counter(
            scope,
            identifier,
            amount=amount,
            limit=limit,
            timeout=timeout,
            reason=reason,
        )

        if failed_reason:
            return _deny(
                failed_reason,
                retry_after=timeout,
                token_estimates=token_estimates,
            )

    return _allow(token_estimates)


def acquire_ai_stream_slot(request):
    ip = get_client_ip(request)
    actor_kind, actor_id = get_request_actor(request)
    actor_identifier = f"{actor_kind}:{actor_id}"
    is_authenticated = request.user.is_authenticated
    timeout = _setting_int("AI_STREAM_LOCK_TIMEOUT_SECONDS", 180)
    actor_limit = (
        _setting_int("AI_STREAM_CONCURRENCY_USER", 2)
        if is_authenticated
        else _setting_int("AI_STREAM_CONCURRENCY_GUEST", 1)
    )
    checks = (
        (
            "stream:ip",
            ip,
            _setting_int("AI_STREAM_CONCURRENCY_IP", 5),
            "ip_stream_concurrency",
        ),
        (
            "stream:actor",
            actor_identifier,
            actor_limit,
            "actor_stream_concurrency",
        ),
    )
    acquired_keys = []

    for scope, identifier, limit, reason in checks:
        if limit <= 0:
            continue

        key = _cache_key(scope, identifier)
        current = _increment_cache_counter(
            key,
            amount=1,
            timeout=timeout,
        )

        if current > limit:
            _decrement_cache_counter(key)

            for acquired_key in acquired_keys:
                _decrement_cache_counter(acquired_key)

            _register_scoped_violation(scope, identifier)
            return AIStreamSlot(
                allowed=False,
                reason=reason,
                message=DEFAULT_RATE_LIMIT_MESSAGE,
                retry_after=timeout,
            )

        acquired_keys.append(key)

    return AIStreamSlot(
        allowed=True,
        keys=acquired_keys,
        retry_after=timeout,
    )


def release_ai_stream_slot(slot):
    if not slot or not slot.keys:
        return

    for key in slot.keys:
        _decrement_cache_counter(key)

    slot.keys = []


def _usage_identity(request):
    actor_kind, _ = get_request_actor(request)

    return {
        "user": request.user if request.user.is_authenticated else None,
        "session_key": request.session.session_key or "",
        "actor_kind": actor_kind,
        "ip_address_hash": get_request_ip_hash(request),
    }


def _event_estimates(prompt, response_text=""):
    prompt_tokens = estimate_tokens_from_text(prompt)
    response_tokens = estimate_tokens_from_text(response_text)
    total_tokens = prompt_tokens + response_tokens

    return {
        "prompt_chars": len(str(prompt or "")),
        "response_chars": len(str(response_text or "")),
        "estimated_prompt_tokens": prompt_tokens,
        "estimated_response_tokens": response_tokens,
        "estimated_total_tokens": total_tokens,
        "estimated_cost_micros": estimate_cost_micros(total_tokens),
    }


def record_throttled_ai_request(
    request,
    prompt,
    decision,
    chat_session: ChatSession | None = None,
    is_stream=False,
):
    estimates = _event_estimates(prompt)
    estimated_prompt = (
        getattr(decision, "estimated_prompt_tokens", 0)
        or estimates["estimated_prompt_tokens"]
    )
    estimated_response = getattr(decision, "estimated_response_tokens", 0) or 0
    estimated_total = (
        getattr(decision, "estimated_total_tokens", 0)
        or estimated_prompt + estimated_response
    )

    return AIUsageEvent.objects.create(
        **_usage_identity(request),
        chat_session=chat_session,
        status=AIUsageEvent.Status.THROTTLED,
        limit_reason=getattr(decision, "reason", ""),
        is_stream=is_stream,
        prompt_chars=estimates["prompt_chars"],
        estimated_prompt_tokens=estimated_prompt,
        estimated_response_tokens=estimated_response,
        estimated_total_tokens=estimated_total,
        estimated_cost_micros=estimate_cost_micros(estimated_total),
    )


def create_ai_usage_event(request, chat_session, prompt, is_stream=False):
    estimates = _event_estimates(prompt)
    response_tokens = get_estimated_response_tokens()
    reserved_total = estimates["estimated_prompt_tokens"] + response_tokens

    return AIUsageEvent.objects.create(
        **_usage_identity(request),
        chat_session=chat_session,
        status=AIUsageEvent.Status.STARTED,
        is_stream=is_stream,
        prompt_chars=estimates["prompt_chars"],
        estimated_prompt_tokens=estimates["estimated_prompt_tokens"],
        estimated_response_tokens=response_tokens,
        estimated_total_tokens=reserved_total,
        estimated_cost_micros=estimate_cost_micros(reserved_total),
    )


def finish_ai_usage_event(
    event,
    status,
    response_text="",
    model_name="",
    limit_reason="",
):
    if event is None:
        return None

    estimates = _event_estimates(
        "x" * event.prompt_chars,
        response_text=response_text,
    )
    event.status = status
    event.response_chars = estimates["response_chars"]
    event.estimated_response_tokens = estimates["estimated_response_tokens"]
    event.estimated_total_tokens = (
        event.estimated_prompt_tokens + event.estimated_response_tokens
    )
    event.estimated_cost_micros = estimate_cost_micros(
        event.estimated_total_tokens
    )

    if model_name:
        event.model_name = model_name

    if limit_reason:
        event.limit_reason = limit_reason

    event.save(
        update_fields=[
            "status",
            "response_chars",
            "estimated_response_tokens",
            "estimated_total_tokens",
            "estimated_cost_micros",
            "model_name",
            "limit_reason",
            "updated_at",
        ]
    )
    return event
