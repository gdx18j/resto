from django.utils.html import format_html_join


LANGUAGES = ("ru", "en", "tr")
DEFAULT_LANGUAGE = "ru"
LANGUAGE_CHOICES = (
    ("ru", "Russian"),
    ("en", "English"),
    ("tr", "Turkish"),
)

UNCATEGORIZED_CATEGORY_TRANSLATIONS = {
    "ru": "Другое",
    "en": "Other",
    "tr": "Diger",
}


def normalize_language(language):
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


def localized_text_html(values):
    return format_html_join(
        "",
        '<span class="lang lang--{}">{}</span>',
        ((language, values[language]) for language in LANGUAGES),
    )


def _prefetched_translations(obj):
    cached_relations = getattr(obj, "_prefetched_objects_cache", {})

    if "translations" in cached_relations:
        return list(cached_relations["translations"])

    return list(obj.translations.all())


def _complete_values(values, fallback):
    return {
        language: (values.get(language) or fallback or "")
        for language in LANGUAGES
    }


def _single_field_values(obj, field_name, fallback):
    if obj is None:
        return _complete_values({}, fallback)

    values = {
        translation.language: getattr(translation, field_name, "")
        for translation in _prefetched_translations(obj)
    }

    return _complete_values(values, fallback)


def localized_category_values(category):
    if isinstance(category, str):
        if category == "Другое":
            return UNCATEGORIZED_CATEGORY_TRANSLATIONS.copy()
        return _complete_values({}, category)

    return _single_field_values(category, "name", category.name)


def localized_category_html(category):
    return localized_text_html(localized_category_values(category))


def localized_allergen_values(allergen):
    return _single_field_values(allergen, "name", allergen.name)


def localized_allergen_html(allergen):
    return localized_text_html(localized_allergen_values(allergen))


def localized_dish_values(dish, field):
    fallback = getattr(dish, field)
    values = {}

    for translation in _prefetched_translations(dish):
        values[translation.language] = getattr(translation, field, "")

    return _complete_values(values, fallback)


def localized_dish_string(dish, field, language=DEFAULT_LANGUAGE):
    return localized_dish_values(dish, field)[normalize_language(language)]


def localized_dish_html(dish, field):
    return localized_text_html(localized_dish_values(dish, field))
