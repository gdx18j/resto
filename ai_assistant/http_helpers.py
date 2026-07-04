import json
import logging


logger = logging.getLogger(__name__)


def wants_stream(request):
    return (
        request.headers.get("X-AI-Stream") == "1"
        or "application/x-ndjson" in request.headers.get("Accept", "")
    )


def stream_event(event_type, **payload):
    payload["type"] = event_type
    return json.dumps(payload, ensure_ascii=False) + "\n"


def wants_json_response(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def close_provider_stream(stream_handle):
    stream = getattr(stream_handle, "stream", None)
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("Could not close Gemini stream cleanly.", exc_info=True)
