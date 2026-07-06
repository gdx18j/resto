from django.conf import settings


SUPPORTED_UI_LANGUAGES = ("ru", "en", "tr")
DEFAULT_UI_LANGUAGE = "ru"
UI_LANGUAGE_COOKIE_NAME = "cc_language"


def normalize_ui_language(value):
    language = str(value or "").strip().lower()
    return language if language in SUPPORTED_UI_LANGUAGES else DEFAULT_UI_LANGUAGE


def ui_preferences(request):
    return {
        "ui_language": normalize_ui_language(
            request.COOKIES.get(UI_LANGUAGE_COOKIE_NAME)
        ),
        "ui_supported_languages": SUPPORTED_UI_LANGUAGES,
    }


def oauth_providers(request):
    return {
        "google_oauth_enabled": bool(
            getattr(settings, "GOOGLE_OAUTH_ENABLED", False)
        ),
    }
