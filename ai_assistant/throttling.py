import hashlib
import logging
import math
import threading
import time as time_module
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache, caches
from django.core.cache.backends.redis import RedisCache
from django.utils import timezone

from config.client_ip import get_client_ip

from .models import AIRequestRecord, AIUsageEvent, ChatSession


DEFAULT_RATE_LIMIT_MESSAGE = (
    "Слишком много запросов к ИИ. Попробуйте отправить сообщение позже."
)
STORE_UNAVAILABLE_MESSAGE = (
    "Защита ИИ временно недоступна. Попробуйте отправить сообщение позже."
)
_LOCAL_LEASE_LOCK = threading.RLock()
logger = logging.getLogger(__name__)


@dataclass
class AIThrottleDecision:
    allowed: bool
    reason: str = ""
    message: str = ""
    retry_after: int = 60
    estimated_prompt_tokens: int = 0
    estimated_response_tokens: int = 0
    estimated_total_tokens: int = 0


@dataclass(frozen=True)
class CacheLease:
    key: str
    token: str
    timeout: int


@dataclass
class AIStreamSlot:
    allowed: bool
    leases: list[CacheLease] = field(default_factory=list)
    reason: str = ""
    message: str = ""
    retry_after: int = 60


@dataclass(frozen=True)
class ReservedCounter:
    key: str
    amount: int
    timeout: int
    kind: str


@dataclass
class AIQuotaReservation(AIThrottleDecision):
    counters: list[ReservedCounter] = field(default_factory=list)
    estimated_cost_micros: int = 0
    reconciled: bool = False


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

    return max(int((next_day - now).total_seconds()), 1)


def _fixed_window(window_seconds):
    window_seconds = max(1, int(window_seconds))
    now = int(time_module.time())
    bucket = now // window_seconds
    retry_after = window_seconds - (now % window_seconds)
    return bucket, max(1, retry_after)


def _increment_cache_counter(key, amount=1, timeout=60):
    if amount <= 0:
        return max(0, int(cache.get(key, 0) or 0))

    if cache.add(key, amount, timeout=timeout):
        return amount

    try:
        return cache.incr(key, amount)
    except ValueError:
        if cache.add(key, amount, timeout=timeout):
            return amount
        return cache.incr(key, amount)


def _adjust_cache_counter(key, delta):
    if not delta:
        return

    try:
        cache.incr(key, delta)
    except Exception:
        logger.exception("Could not adjust AI quota counter %s.", key)


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

    return AIQuotaReservation(
        allowed=False,
        reason=reason,
        message=DEFAULT_RATE_LIMIT_MESSAGE,
        retry_after=max(1, int(retry_after)),
        estimated_prompt_tokens=prompt_tokens,
        estimated_response_tokens=response_tokens,
        estimated_total_tokens=total_tokens,
        estimated_cost_micros=estimate_cost_micros(total_tokens),
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

    try:
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
    except Exception:
        logger.exception("Could not record an AI abuse violation.")


def _register_scoped_violation(scope, identifier):
    if "ip" in scope:
        _register_violation("ip", identifier)
        return

    if "actor" in scope:
        _register_violation("actor", identifier)


def _redis_compare_script(operation):
    if operation == "delete":
        return (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
    return (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
    )


def _redis_compare_operation(lease, operation):
    backend = caches["default"]

    if not isinstance(backend, RedisCache):
        return None

    safe_key = backend.make_and_validate_key(lease.key)
    client = backend._cache.get_client(safe_key, write=True)
    expected = backend._cache._serializer.dumps(lease.token)
    args = [expected]

    if operation == "touch":
        args.append(max(1, int(lease.timeout)))

    return bool(
        client.eval(
            _redis_compare_script(operation),
            1,
            safe_key,
            *args,
        )
    )


def _release_lease(lease):
    redis_result = _redis_compare_operation(lease, "delete")

    if redis_result is not None:
        return redis_result

    with _LOCAL_LEASE_LOCK:
        if cache.get(lease.key) != lease.token:
            return False
        return bool(cache.delete(lease.key))


def _refresh_lease(lease):
    redis_result = _redis_compare_operation(lease, "touch")

    if redis_result is not None:
        return redis_result

    with _LOCAL_LEASE_LOCK:
        if cache.get(lease.key) != lease.token:
            return False
        return bool(cache.touch(lease.key, lease.timeout))


def _acquire_lease(key, timeout):
    timeout = max(1, int(timeout))
    token = uuid.uuid4().hex

    if not cache.add(key, token, timeout=timeout):
        return None

    return CacheLease(key=key, token=token, timeout=timeout)


def _acquire_named_lease(scope, identifier, timeout):
    return _acquire_lease(
        _cache_key("lease", scope, identifier),
        timeout,
    )


def _release_leases(leases):
    for lease in reversed(list(leases or [])):
        try:
            _release_lease(lease)
        except Exception:
            logger.exception("Could not release AI cache lease %s.", lease.key)


def _acquire_quota_mutexes(ip, actor_identifier):
    timeout = max(1, _setting_int("AI_QUOTA_LOCK_TIMEOUT_SECONDS", 5))
    identities = sorted({f"ip:{ip}", f"actor:{actor_identifier}"})
    leases = []

    for identifier in identities:
        lease = _acquire_named_lease("quota", identifier, timeout)

        if lease is None:
            _release_leases(leases)
            return None

        leases.append(lease)

    return leases


def _quota_specs(request, prompt):
    ip = get_client_ip(request)
    actor_kind, actor_id = get_request_actor(request)
    actor_identifier = f"{actor_kind}:{actor_id}"
    token_estimates = estimate_request_tokens(prompt)
    _, _, total_tokens = token_estimates
    estimated_cost = estimate_cost_micros(total_tokens)
    is_authenticated = request.user.is_authenticated
    window_seconds = max(1, _setting_int("AI_RATE_LIMIT_WINDOW_SECONDS", 60))
    minute_bucket, minute_retry = _fixed_window(window_seconds)
    daily_retry = _seconds_until_next_utc_day()
    day = timezone.now().date().isoformat()
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
    raw_specs = (
        (
            "minute:ip",
            f"{minute_bucket}:{ip}",
            1,
            _setting_int("AI_RATE_LIMIT_IP_PER_MINUTE", 30),
            minute_retry + 2,
            minute_retry,
            "ip_minute_limit",
            "request",
        ),
        (
            "minute:actor",
            f"{minute_bucket}:{actor_identifier}",
            1,
            actor_minute_limit,
            minute_retry + 2,
            minute_retry,
            "actor_minute_limit",
            "request",
        ),
        (
            "daily:ip",
            f"{day}:{ip}",
            1,
            _setting_int("AI_DAILY_QUOTA_IP", 120),
            daily_retry + 60,
            daily_retry,
            "ip_daily_quota",
            "request",
        ),
        (
            "daily:actor",
            f"{day}:{actor_identifier}",
            1,
            actor_daily_limit,
            daily_retry + 60,
            daily_retry,
            "actor_daily_quota",
            "request",
        ),
        (
            "daily_tokens:ip",
            f"{day}:{ip}",
            total_tokens,
            _setting_int("AI_DAILY_TOKEN_BUDGET_IP", 160000),
            daily_retry + 60,
            daily_retry,
            "ip_daily_token_budget",
            "tokens",
        ),
        (
            "daily_tokens:actor",
            f"{day}:{actor_identifier}",
            total_tokens,
            actor_token_budget,
            daily_retry + 60,
            daily_retry,
            "actor_daily_token_budget",
            "tokens",
        ),
        (
            "daily_cost:ip",
            f"{day}:{ip}",
            estimated_cost,
            _setting_int("AI_DAILY_COST_BUDGET_MICROS_IP", 0),
            daily_retry + 60,
            daily_retry,
            "ip_daily_cost_budget",
            "cost",
        ),
        (
            "daily_cost:actor",
            f"{day}:{actor_identifier}",
            estimated_cost,
            actor_cost_budget,
            daily_retry + 60,
            daily_retry,
            "actor_daily_cost_budget",
            "cost",
        ),
    )
    specs = []

    for scope, identifier, amount, limit, timeout, retry, reason, kind in raw_specs:
        if limit <= 0 or amount <= 0:
            continue
        specs.append(
            {
                "scope": scope,
                "identifier": identifier,
                "key": _cache_key(scope, identifier),
                "amount": amount,
                "limit": limit,
                "timeout": timeout,
                "retry_after": retry,
                "reason": reason,
                "kind": kind,
            }
        )

    return ip, actor_identifier, token_estimates, estimated_cost, specs


def reserve_ai_request_quota(request, prompt):
    ip, actor_identifier, token_estimates, estimated_cost, specs = _quota_specs(
        request,
        prompt,
    )

    try:
        blocked = _is_blocked("ip", ip) or _is_blocked(
            "actor",
            actor_identifier,
        )
    except Exception:
        logger.exception("AI quota store is unavailable during block lookup.")
        decision = _deny(
            "quota_store_unavailable",
            retry_after=5,
            token_estimates=token_estimates,
        )
        decision.message = STORE_UNAVAILABLE_MESSAGE
        return decision

    if blocked:
        return _deny(
            "abuse_block",
            retry_after=_setting_int("AI_ABUSE_BLOCK_SECONDS", 600),
            token_estimates=token_estimates,
        )

    try:
        mutexes = _acquire_quota_mutexes(ip, actor_identifier)
    except Exception:
        logger.exception("AI quota store is unavailable during lease acquisition.")
        decision = _deny(
            "quota_store_unavailable",
            retry_after=5,
            token_estimates=token_estimates,
        )
        decision.message = STORE_UNAVAILABLE_MESSAGE
        return decision

    if mutexes is None:
        return _deny(
            "quota_reservation_busy",
            retry_after=max(
                1,
                _setting_int("AI_QUOTA_LOCK_RETRY_AFTER_SECONDS", 1),
            ),
            token_estimates=token_estimates,
        )

    counters = []

    try:
        try:
            current_values = cache.get_many([spec["key"] for spec in specs])
        except Exception:
            decision = _deny(
                "quota_store_unavailable",
                retry_after=5,
                token_estimates=token_estimates,
            )
            decision.message = STORE_UNAVAILABLE_MESSAGE
            return decision

        for spec in specs:
            current = max(0, int(current_values.get(spec["key"], 0) or 0))

            if current + spec["amount"] > spec["limit"]:
                _register_scoped_violation(spec["scope"], spec["identifier"])
                return _deny(
                    spec["reason"],
                    retry_after=spec["retry_after"],
                    token_estimates=token_estimates,
                )

        try:
            for spec in specs:
                _increment_cache_counter(
                    spec["key"],
                    amount=spec["amount"],
                    timeout=spec["timeout"],
                )
                counters.append(
                    ReservedCounter(
                        key=spec["key"],
                        amount=spec["amount"],
                        timeout=spec["timeout"],
                        kind=spec["kind"],
                    )
                )
        except Exception:
            for counter in counters:
                _adjust_cache_counter(counter.key, -counter.amount)
            decision = _deny(
                "quota_store_unavailable",
                retry_after=5,
                token_estimates=token_estimates,
            )
            decision.message = STORE_UNAVAILABLE_MESSAGE
            return decision
    finally:
        _release_leases(mutexes)

    prompt_tokens, response_tokens, total_tokens = token_estimates
    return AIQuotaReservation(
        allowed=True,
        estimated_prompt_tokens=prompt_tokens,
        estimated_response_tokens=response_tokens,
        estimated_total_tokens=total_tokens,
        estimated_cost_micros=estimated_cost,
        counters=counters,
    )


def check_ai_request_allowed(request, prompt):
    """Backward-compatible name. This function now performs a reservation."""
    return reserve_ai_request_quota(request, prompt)


def release_ai_quota_reservation(reservation):
    if not reservation or not reservation.allowed or reservation.reconciled:
        return

    for counter in reservation.counters:
        _adjust_cache_counter(counter.key, -counter.amount)

    reservation.reconciled = True


def reconcile_ai_quota_reservation(reservation, provider_usage):
    if not reservation or not reservation.allowed or reservation.reconciled:
        return

    if provider_usage is None:
        reservation.reconciled = True
        return

    actual_total = max(0, int(getattr(provider_usage, "total_tokens", 0) or 0))
    actual_cost = estimate_cost_micros(actual_total)

    for counter in reservation.counters:
        if counter.kind == "tokens":
            _adjust_cache_counter(counter.key, actual_total - counter.amount)
        elif counter.kind == "cost":
            _adjust_cache_counter(counter.key, actual_cost - counter.amount)

    reservation.reconciled = True


def _effective_lease_timeout(setting_name, default):
    provider_timeout = max(1, _setting_int("AI_PROVIDER_TIMEOUT_SECONDS", 45))
    return max(
        provider_timeout + 15,
        _setting_int(setting_name, default),
    )


def _acquire_bounded_slot(scope, identifier, limit, timeout):
    if limit <= 0:
        return None

    for slot_index in range(limit):
        lease = _acquire_lease(
            _cache_key("slot", scope, identifier, slot_index),
            timeout,
        )
        if lease is not None:
            return lease

    return None


def acquire_ai_stream_slot(request):
    ip = get_client_ip(request)
    actor_kind, actor_id = get_request_actor(request)
    actor_identifier = f"{actor_kind}:{actor_id}"
    is_authenticated = request.user.is_authenticated
    timeout = _effective_lease_timeout("AI_STREAM_LOCK_TIMEOUT_SECONDS", 180)
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
    leases = []

    for scope, identifier, limit, reason in checks:
        if limit <= 0:
            continue

        try:
            lease = _acquire_bounded_slot(scope, identifier, limit, timeout)
        except Exception:
            logger.exception("AI stream guard store is unavailable.")
            _release_leases(leases)
            return AIStreamSlot(
                allowed=False,
                reason="guard_store_unavailable",
                message=STORE_UNAVAILABLE_MESSAGE,
                retry_after=5,
            )

        if lease is None:
            _release_leases(leases)
            _register_scoped_violation(scope, identifier)
            return AIStreamSlot(
                allowed=False,
                reason=reason,
                message=DEFAULT_RATE_LIMIT_MESSAGE,
                retry_after=min(timeout, 30),
            )

        leases.append(lease)

    return AIStreamSlot(
        allowed=True,
        leases=leases,
        retry_after=timeout,
    )


def acquire_ai_session_slot(session: ChatSession):
    timeout = _effective_lease_timeout(
        "AI_SESSION_LOCK_TIMEOUT_SECONDS",
        _setting_int("AI_STREAM_LOCK_TIMEOUT_SECONDS", 180),
    )
    try:
        lease = _acquire_named_lease("session", session.id, timeout)
    except Exception:
        logger.exception("AI session guard store is unavailable.")
        return AIStreamSlot(
            allowed=False,
            reason="guard_store_unavailable",
            message=STORE_UNAVAILABLE_MESSAGE,
            retry_after=5,
        )

    if lease is not None:
        return AIStreamSlot(
            allowed=True,
            leases=[lease],
            retry_after=timeout,
        )

    return AIStreamSlot(
        allowed=False,
        reason="session_in_progress",
        message=(
            "Ассистент уже отвечает в этом диалоге. "
            "Дождитесь ответа и попробуйте еще раз."
        ),
        retry_after=min(timeout, 30),
    )


def acquire_ai_request_slot(request_id):
    timeout = _effective_lease_timeout("AI_REQUEST_LOCK_TIMEOUT_SECONDS", 30)
    try:
        lease = _acquire_named_lease("request", request_id, timeout)
    except Exception:
        logger.exception("AI request guard store is unavailable.")
        return AIStreamSlot(
            allowed=False,
            reason="guard_store_unavailable",
            message=STORE_UNAVAILABLE_MESSAGE,
            retry_after=5,
        )

    if lease is None:
        return AIStreamSlot(
            allowed=False,
            reason="request_in_progress",
            message="Этот запрос уже обрабатывается.",
            retry_after=min(timeout, 15),
        )

    return AIStreamSlot(
        allowed=True,
        leases=[lease],
        retry_after=timeout,
    )


def refresh_ai_slot(slot):
    if not slot or not slot.leases:
        return False

    refreshed = True

    for lease in slot.leases:
        try:
            refreshed = _refresh_lease(lease) and refreshed
        except Exception:
            logger.exception("Could not refresh AI cache lease %s.", lease.key)
            refreshed = False

    return refreshed


def release_ai_stream_slot(slot):
    if not slot or not slot.leases:
        return

    _release_leases(slot.leases)
    slot.leases = []


def release_ai_session_slot(slot):
    release_ai_stream_slot(slot)


def release_ai_request_slot(slot):
    release_ai_stream_slot(slot)


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


def create_ai_usage_event(
    request,
    chat_session,
    prompt,
    is_stream=False,
    request_record: AIRequestRecord | None = None,
    quota_reservation: AIQuotaReservation | None = None,
):
    estimates = _event_estimates(prompt)
    response_tokens = (
        quota_reservation.estimated_response_tokens
        if quota_reservation
        else get_estimated_response_tokens()
    )
    prompt_tokens = (
        quota_reservation.estimated_prompt_tokens
        if quota_reservation
        else estimates["estimated_prompt_tokens"]
    )
    reserved_total = prompt_tokens + response_tokens

    return AIUsageEvent.objects.create(
        **_usage_identity(request),
        chat_session=chat_session,
        request_record=request_record,
        status=AIUsageEvent.Status.STARTED,
        is_stream=is_stream,
        prompt_chars=estimates["prompt_chars"],
        estimated_prompt_tokens=prompt_tokens,
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
    provider_usage=None,
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

    if provider_usage is not None:
        event.actual_prompt_tokens = max(
            0,
            int(getattr(provider_usage, "prompt_tokens", 0) or 0),
        )
        event.actual_response_tokens = max(
            0,
            int(getattr(provider_usage, "response_tokens", 0) or 0),
        )
        event.actual_total_tokens = max(
            0,
            int(getattr(provider_usage, "total_tokens", 0) or 0),
        )
        event.actual_cost_micros = estimate_cost_micros(event.actual_total_tokens)
        event.provider_response_id = str(
            getattr(provider_usage, "response_id", "") or ""
        )[:160]

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
            "actual_prompt_tokens",
            "actual_response_tokens",
            "actual_total_tokens",
            "actual_cost_micros",
            "provider_response_id",
            "model_name",
            "limit_reason",
            "updated_at",
        ]
    )
    return event
