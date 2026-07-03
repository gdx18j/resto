from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


def health_live(_request):
    return JsonResponse({"status": "ok", "check": "live"})


def health_ready(_request):
    checks = {
        "database": False,
        "cache": False,
    }

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["database"] = cursor.fetchone() == (1,)
    except Exception:
        checks["database"] = False

    cache_key = "health:ready"
    try:
        cache.set(cache_key, "ok", timeout=10)
        checks["cache"] = cache.get(cache_key) == "ok"
        cache.delete(cache_key)
    except Exception:
        checks["cache"] = False

    ready = all(checks.values())
    response = JsonResponse(
        {
            "status": "ok" if ready else "unavailable",
            "check": "ready",
            "dependencies": checks,
        },
        status=200 if ready else 503,
    )
    response["Cache-Control"] = "no-store"
    return response
