import hashlib

from django.utils.text import slugify


def build_stable_code(value, prefix="item"):
    base = slugify(str(value or "").strip(), allow_unicode=False)

    if base:
        return base[:180]

    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
