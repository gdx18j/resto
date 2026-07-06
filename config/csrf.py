from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware


class RestoCsrfViewMiddleware(CsrfViewMiddleware):
    """Allow opaque local-development origins to rely on the CSRF token itself."""

    def process_view(self, request, callback, callback_args, callback_kwargs):
        origin = request.META.get("HTTP_ORIGIN")
        allow_null_origin = getattr(settings, "CSRF_ALLOW_NULL_ORIGIN", False)

        if origin == "null" and allow_null_origin:
            request.META.pop("HTTP_ORIGIN", None)
            try:
                return super().process_view(
                    request,
                    callback,
                    callback_args,
                    callback_kwargs,
                )
            finally:
                request.META["HTTP_ORIGIN"] = origin

        return super().process_view(
            request,
            callback,
            callback_args,
            callback_kwargs,
        )
