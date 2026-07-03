from django.conf import settings


class SecurityPolicyMiddleware:
    """Attach application security policies to every dynamic response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not getattr(settings, "SECURITY_POLICY_HEADERS_ENABLED", True):
            return response

        policies = {
            "Content-Security-Policy": getattr(
                settings,
                "CONTENT_SECURITY_POLICY",
                "",
            ),
            "Permissions-Policy": getattr(settings, "PERMISSIONS_POLICY", ""),
            "X-Permitted-Cross-Domain-Policies": "none",
        }

        for header_name, value in policies.items():
            if value and header_name not in response:
                response[header_name] = value

        return response
