from .client_ip import strip_untrusted_proxy_headers


class TrustedProxyHeadersMiddleware:
    """Remove forwarding headers unless the direct peer is a trusted proxy."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.resto_proxy_headers_trusted = strip_untrusted_proxy_headers(request)
        return self.get_response(request)
