from ipaddress import ip_address, ip_network

from django.conf import settings


PROXY_HEADER_NAMES = (
    "HTTP_FORWARDED",
    "HTTP_X_FORWARDED_FOR",
    "HTTP_X_FORWARDED_HOST",
    "HTTP_X_FORWARDED_PORT",
    "HTTP_X_FORWARDED_PREFIX",
    "HTTP_X_FORWARDED_PROTO",
    "HTTP_X_FORWARDED_SERVER",
    "HTTP_X_FORWARDED_SSL",
    "HTTP_X_REAL_IP",
)


def normalize_ip(value):
    value = str(value or "").strip()

    if not value:
        return ""

    try:
        return ip_address(value).compressed
    except ValueError:
        return ""


def trusted_proxy_networks():
    networks = []

    for value in getattr(settings, "TRUSTED_PROXY_CIDRS", ()):
        try:
            networks.append(ip_network(str(value).strip(), strict=False))
        except ValueError:
            continue

    return tuple(networks)


def is_trusted_proxy_address(value):
    normalized = normalize_ip(value)

    if not normalized:
        return False

    address = ip_address(normalized)
    return any(address in network for network in trusted_proxy_networks())


def proxy_headers_are_trusted(request):
    if not getattr(settings, "TRUST_PROXY_HEADERS", False):
        return False

    return is_trusted_proxy_address(request.META.get("REMOTE_ADDR"))


def strip_untrusted_proxy_headers(request):
    if proxy_headers_are_trusted(request):
        return True

    for header_name in PROXY_HEADER_NAMES:
        request.META.pop(header_name, None)

    return False


def _forwarded_chain(request):
    raw_value = request.META.get("HTTP_X_FORWARDED_FOR", "")
    addresses = []

    for part in raw_value.split(","):
        normalized = normalize_ip(part)
        if normalized:
            addresses.append(normalized)

    return addresses


def get_client_ip(request):
    remote_addr = normalize_ip(request.META.get("REMOTE_ADDR")) or "unknown"

    if not proxy_headers_are_trusted(request):
        return remote_addr

    chain = _forwarded_chain(request)
    chain.append(remote_addr)

    # X-Forwarded-For is ordered from the original client to the nearest proxy.
    # Walk from the trusted edge backwards and return the first untrusted hop.
    for candidate in reversed(chain):
        if not is_trusted_proxy_address(candidate):
            return candidate

    real_ip = normalize_ip(request.META.get("HTTP_X_REAL_IP"))
    if real_ip:
        return real_ip

    return chain[0] if chain else remote_addr
