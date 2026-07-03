import re
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass

from django.conf import settings

from menu.models import Dish
from menu.translations import (
    LANGUAGES,
    localized_category_values,
    localized_dish_values,
    normalize_language,
)


_TOKEN_PATTERN = re.compile(r"[\w'-]+", re.UNICODE)

_STOP_WORDS = {
    "а",
    "без",
    "бы",
    "в",
    "во",
    "для",
    "же",
    "и",
    "или",
    "из",
    "к",
    "как",
    "мне",
    "на",
    "не",
    "но",
    "по",
    "под",
    "посоветуй",
    "пожалуйста",
    "с",
    "со",
    "у",
    "хочу",
    "что",
    "я",
    "a",
    "an",
    "and",
    "can",
    "for",
    "give",
    "i",
    "in",
    "me",
    "of",
    "or",
    "please",
    "recommend",
    "suggest",
    "the",
    "to",
    "want",
    "with",
    "bir",
    "bana",
    "ben",
    "icin",
    "için",
    "ile",
    "lutfen",
    "lütfen",
    "oner",
    "öner",
    "ve",
}

_OTHER_OPTION_MARKERS = {
    "another",
    "different",
    "else",
    "more",
    "other",
    "друг",
    "другой",
    "другие",
    "еще",
    "ещё",
    "başka",
}

_DRINK_MARKERS = {
    "americano",
    "beverage",
    "bira",
    "coffee",
    "cola",
    "drink",
    "espresso",
    "juice",
    "kahve",
    "latte",
    "lemonade",
    "matcha",
    "soda",
    "tea",
    "water",
    "кофе",
    "лимонад",
    "матча",
    "напиток",
    "напитки",
    "сок",
    "чай",
}

_DESSERT_MARKERS = {
    "cake",
    "cookie",
    "dessert",
    "sweet",
    "tatli",
    "tatlı",
    "торт",
    "десерт",
    "печенье",
    "сладкое",
}

_SAVORY_MARKERS = {
    "burger",
    "doner",
    "döner",
    "food",
    "kebab",
    "meal",
    "pide",
    "pizza",
    "sandwich",
    "savory",
    "toast",
    "tost",
    "wrap",
    "бургер",
    "еда",
    "кебаб",
    "пицца",
    "сэндвич",
    "тост",
    "шаурма",
}

_ALLERGY_MARKERS = {
    "allergen",
    "allergy",
    "alerjen",
    "alerji",
    "аллерген",
    "аллергия",
    "непереносимость",
}

_NEGATIVE_MARKERS = {
    "avoid",
    "excluding",
    "free",
    "no",
    "without",
    "без",
    "исключить",
    "нет",
    "olmadan",
    "yok",
}


@dataclass(frozen=True)
class RetrievalResult:
    dishes: tuple[Dish, ...]
    query_tokens: tuple[str, ...]
    excluded_dish_ids: tuple[int, ...]

    @property
    def candidate_ids(self) -> tuple[int, ...]:
        return tuple(dish.id for dish in self.dishes)


def normalize_search_text(value) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.casefold().replace("ı", "i").strip()


def tokenize_search_text(value) -> tuple[str, ...]:
    normalized = normalize_search_text(value)
    tokens = []

    for token in _TOKEN_PATTERN.findall(normalized):
        token = token.strip("_'-")

        if len(token) < 2 or token in _STOP_WORDS:
            continue

        tokens.append(token)

    return tuple(dict.fromkeys(tokens))


def is_other_options_request(prompt) -> bool:
    return bool(set(tokenize_search_text(prompt)) & _OTHER_OPTION_MARKERS)


def _localized_dish_texts(dish: Dish) -> dict[str, str]:
    names = localized_dish_values(dish, "name")
    descriptions = localized_dish_values(dish, "description")
    categories = (
        localized_category_values(dish.category)
        if dish.category_id
        else {language: "" for language in LANGUAGES}
    )

    return {
        "names": " ".join(names.values()),
        "descriptions": " ".join(descriptions.values()),
        "categories": " ".join(categories.values()),
        "ingredients": " ".join(
            dish_ingredient.ingredient.name
            for dish_ingredient in dish.dish_ingredients.all()
        ),
        "allergens": " ".join(
            link.allergen.name
            for link in dish.allergen_links.all()
            if (
                link.verification_status == "verified"
                and link.reviewed_recipe_revision == dish.recipe_revision
            )
        ),
    }


def _document_tokens(value) -> set[str]:
    return set(tokenize_search_text(value))


def _contains_phrase(document, phrase) -> bool:
    phrase = normalize_search_text(phrase)
    return bool(phrase and phrase in normalize_search_text(document))


def _prompt_intent(prompt_tokens: set[str]) -> str:
    if prompt_tokens & _DRINK_MARKERS:
        return "drink"

    if prompt_tokens & _DESSERT_MARKERS:
        return "dessert"

    if prompt_tokens & _SAVORY_MARKERS:
        return "savory"

    return "general"


def _dish_intent(texts: dict[str, str]) -> str:
    category_and_name = _document_tokens(
        f"{texts['categories']} {texts['names']}"
    )

    if category_and_name & _DRINK_MARKERS:
        return "drink"

    if category_and_name & _DESSERT_MARKERS:
        return "dessert"

    return "savory"


def _score_dish(prompt, prompt_tokens: set[str], dish: Dish) -> int:
    texts = _localized_dish_texts(dish)
    names = _document_tokens(texts["names"])
    categories = _document_tokens(texts["categories"])
    ingredients = _document_tokens(texts["ingredients"])
    descriptions = _document_tokens(texts["descriptions"])
    allergens = _document_tokens(texts["allergens"])
    score = 0

    if _contains_phrase(texts["names"], prompt):
        score += 500

    score += len(prompt_tokens & names) * 90
    score += len(prompt_tokens & categories) * 55
    score += len(prompt_tokens & ingredients) * 30
    score += len(prompt_tokens & descriptions) * 12
    score += len(prompt_tokens & allergens) * 25

    prompt_intent = _prompt_intent(prompt_tokens)
    dish_intent = _dish_intent(texts)

    if prompt_intent != "general":
        if prompt_intent == dish_intent:
            score += 60
        else:
            score -= 45

    if prompt_tokens & _ALLERGY_MARKERS:
        if dish.is_allergen_review_complete:
            score += 35
        elif dish.public_allergen_data_status == Dish.AllergenReviewStatus.PARTIAL:
            score += 8

    if prompt_tokens & _NEGATIVE_MARKERS and prompt_tokens & allergens:
        score -= 80

    return score


def _round_robin_by_category(dishes, limit):
    groups = defaultdict(deque)

    for dish in dishes:
        groups[dish.category_id].append(dish)

    ordered_keys = sorted(
        groups,
        key=lambda value: (value is None, value or 0),
    )
    selected = []

    while ordered_keys and len(selected) < limit:
        next_keys = []

        for key in ordered_keys:
            group = groups[key]

            if group and len(selected) < limit:
                selected.append(group.popleft())

            if group:
                next_keys.append(key)

        ordered_keys = next_keys

    return selected


def retrieve_menu_dishes(
    *,
    restaurant_id: int,
    prompt: str,
    language: str = "ru",
    excluded_dish_ids=(),
    limit: int | None = None,
) -> RetrievalResult:
    if not restaurant_id:
        raise ValueError("restaurant_id is required for AI menu retrieval.")

    language = normalize_language(language)
    excluded_ids = {
        int(value)
        for value in excluded_dish_ids
        if isinstance(value, int) and not isinstance(value, bool)
    }
    configured_limit = max(1, int(settings.AI_MENU_CONTEXT_LIMIT))
    limit = max(1, min(int(limit or configured_limit), configured_limit))
    prompt_tokens = set(tokenize_search_text(prompt))
    queryset = (
        Dish.objects.filter(
            restaurant_id=restaurant_id,
            is_active=True,
            is_available=True,
        )
        .exclude(id__in=excluded_ids)
        .select_related("category")
        .prefetch_related(
            "translations",
            "category__translations",
            "dish_ingredients__ingredient",
            "allergen_links__allergen",
        )
        .order_by("category__name", "name", "id")
    )
    dishes = list(queryset)

    if not dishes:
        return RetrievalResult(
            dishes=(),
            query_tokens=tuple(sorted(prompt_tokens)),
            excluded_dish_ids=tuple(sorted(excluded_ids)),
        )

    scored = [
        (_score_dish(prompt, prompt_tokens, dish), dish)
        for dish in dishes
    ]
    scored.sort(
        key=lambda item: (
            -item[0],
            normalize_search_text(item[1].category.name if item[1].category else ""),
            normalize_search_text(item[1].name),
            item[1].id,
        )
    )
    positive = [dish for score, dish in scored if score > 0]
    selected = positive[:limit]

    if len(selected) < limit:
        selected_ids = {dish.id for dish in selected}
        remaining = [
            dish
            for _, dish in scored
            if dish.id not in selected_ids
        ]
        selected.extend(
            _round_robin_by_category(
                remaining,
                limit - len(selected),
            )
        )

    return RetrievalResult(
        dishes=tuple(selected[:limit]),
        query_tokens=tuple(sorted(prompt_tokens)),
        excluded_dish_ids=tuple(sorted(excluded_ids)),
    )
