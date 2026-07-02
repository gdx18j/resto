import logging
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from google import genai
from google.genai import errors, types

from accounts.models import UserAllergy
from menu.models import Dish, DishAllergen, get_default_restaurant_id
from menu.translations import normalize_language

from .models import ChatMessage, ChatSession
from .prompts import RESTAURANT_ASSISTANT_SYSTEM_PROMPT


logger = logging.getLogger(__name__)


RETRYABLE_ERROR_CODES = {
    429,
    500,
    502,
    503,
    504,
}

INVALID_API_KEY_PLACEHOLDERS = {
    "replace-with-new-gemini-api-key",
    "replace-with-gemini-api-key",
    "your-gemini-api-key",
    "your-gemini-api-key-here",
    "change-me",
}

LANGUAGE_INSTRUCTIONS = {
    "ru": "Response language: Russian. Answer in Russian, matching the user's latest message.",
    "en": "Response language: English. Answer in clear natural English, matching the user's latest message.",
    "tr": "Response language: Turkish. Answer in clear natural Turkish, matching the user's latest message.",
}


class AIServiceError(Exception):
    pass


class EmptyAIResponseError(Exception):
    pass


@dataclass(frozen=True)
class AIResult:
    text: str
    model_name: str


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    api_key = settings.GEMINI_API_KEY.strip()

    if not api_key:
        raise ImproperlyConfigured("GEMINI_API_KEY is not configured.")

    if api_key.casefold() in INVALID_API_KEY_PLACEHOLDERS:
        raise ImproperlyConfigured(
            "GEMINI_API_KEY contains a placeholder value."
        )

    return genai.Client(api_key=api_key)


def _format_list(values):
    values = [str(value).strip() for value in values if str(value).strip()]
    return ", ".join(values) if values else "not specified"


def _trim_text(value, max_length=240):
    value = " ".join(str(value or "").split())

    if len(value) <= max_length:
        return value

    return f"{value[: max_length - 1].rstrip()}..."


def detect_response_language(text, fallback="ru"):
    text = str(text or "").strip()

    if not text:
        return normalize_language(fallback)

    lowered = text.casefold()
    cyrillic_count = sum("а" <= char <= "я" or char == "ё" for char in lowered)
    latin_count = sum("a" <= char <= "z" for char in lowered)
    turkish_special_count = sum(char in "çğıöşü" for char in lowered)

    if cyrillic_count >= 2:
        return "ru"

    turkish_words = {
        "merhaba",
        "selam",
        "lutfen",
        "lütfen",
        "bana",
        "ben",
        "bir",
        "yemek",
        "icecek",
        "içecek",
        "kahve",
        "alerji",
        "sut",
        "süt",
        "tavsiye",
        "oner",
        "öner",
        "istiyorum",
        "var",
        "yok",
        "bira",
        "pide",
    }
    english_words = {
        "hello",
        "hi",
        "please",
        "recommend",
        "suggest",
        "want",
        "would",
        "dish",
        "food",
        "drink",
        "allergy",
        "allergen",
        "coffee",
        "milk",
        "pizza",
        "beer",
    }
    normalized_words = {
        word.strip(".,!?;:()[]{}\"'")
        for word in lowered.replace("ı", "i").split()
    }
    turkish_score = turkish_special_count + len(normalized_words & turkish_words)
    english_score = len(normalized_words & english_words)

    if latin_count:
        if turkish_score > english_score:
            return "tr"

        return "en"

    return normalize_language(fallback)


def _restaurant_id_for_session(session: ChatSession) -> int:
    ordering_context = getattr(session, "ordering_context", None)

    if ordering_context is not None:
        return ordering_context.restaurant_id

    if getattr(session, "restaurant_id", None):
        return session.restaurant_id

    return get_default_restaurant_id()


def build_menu_context(restaurant_id=None) -> str:
    restaurant_id = restaurant_id or get_default_restaurant_id()
    dishes = (
        Dish.objects.filter(
            restaurant_id=restaurant_id,
            is_active=True,
            is_available=True,
        )
        .select_related("category")
        .prefetch_related(
            "dish_ingredients__ingredient__allergens",
            "may_contain_allergens",
            "allergen_links__allergen",
        )
        .order_by("category__name", "name")[: settings.AI_MENU_CONTEXT_LIMIT]
    )

    lines = [
        "Current restaurant menu data. Use only these dishes, prices, ingredients, allergens and availability facts:",
    ]

    for dish in dishes:
        ingredients = []
        contains_allergens = set()
        trace_allergens = set()

        for link in dish.allergen_links.all():
            if link.verification_status != DishAllergen.VerificationStatus.VERIFIED:
                continue

            if link.relation_type == DishAllergen.RelationType.CONTAINS:
                contains_allergens.add(link.allergen.name)
            elif link.relation_type in {
                DishAllergen.RelationType.MAY_CONTAIN,
                DishAllergen.RelationType.CROSS_CONTAMINATION,
            }:
                trace_allergens.add(link.allergen.name)

        for dish_ingredient in dish.dish_ingredients.all():
            ingredient = dish_ingredient.ingredient
            label = ingredient.name

            if dish_ingredient.can_be_removed:
                label = f"{label} (can be removed)"

            ingredients.append(label)

        facts = [
            f"name: {dish.name}",
            f"category: {dish.category.name if dish.category else 'Other'}",
            f"price: {dish.price}",
            f"description: {_trim_text(dish.description)}",
            f"ingredients: {_format_list(ingredients)}",
            f"contains_allergens: {_format_list(sorted(contains_allergens))}",
            f"trace_allergens: {_format_list(sorted(trace_allergens))}",
        ]

        if dish.serving_weight_g:
            facts.append(f"weight_g: {dish.serving_weight_g}")

        if dish.calories_kcal_per_serving:
            facts.append(f"calories_kcal: {dish.calories_kcal_per_serving}")

        if dish.preparation_time_minutes:
            facts.append(f"prep_minutes: {dish.preparation_time_minutes}")

        lines.append("- " + "; ".join(facts))

    if len(lines) == 1:
        lines.append("- No active available dishes are currently published.")

    return "\n".join(lines)


def build_user_context(session: ChatSession) -> str:
    if not session.user_id:
        return "Visitor profile: guest user. No saved allergy profile is available."

    if not getattr(session.user, "share_allergies_with_ai", False):
        return (
            "Visitor profile: authenticated user. Saved allergy profile sharing "
            "with the external AI provider is disabled. Do not use saved allergy "
            "data unless the user explicitly writes it in this chat."
        )

    allergens = UserAllergy.objects.filter(
        user=session.user,
        status=UserAllergy.Status.CONFIRMED,
    ).select_related("allergen").order_by("allergen__name")

    allergen_names = [
        record.allergen.name
        for record in allergens
    ]

    return (
        "Visitor profile: authenticated user. Confirmed allergy names shared "
        f"with explicit consent: {_format_list(allergen_names)}. "
        "No other profile fields are included."
    )


def _latest_user_message_text(session: ChatSession) -> str:
    message = (
        session.messages.filter(role=ChatMessage.Role.USER)
        .order_by("-created_at", "-id")
        .first()
    )

    return message.content if message else ""


def _previous_assistant_dish_names(session: ChatSession) -> list[str]:
    previous_text = " ".join(
        session.messages.filter(role=ChatMessage.Role.ASSISTANT)
        .order_by("created_at", "id")
        .values_list("content", flat=True)
    ).casefold()

    if not previous_text:
        return []

    names = []

    for dish in Dish.objects.filter(
        restaurant_id=_restaurant_id_for_session(session),
        is_active=True,
        is_available=True,
    ).order_by("name"):
        if dish.name.casefold() in previous_text:
            names.append(dish.name)

    return names


def build_request_context(session: ChatSession) -> str:
    prompt = _latest_user_message_text(session).casefold()

    if not prompt:
        return "Current request guidance: no current user request."

    guidance = [
        "Current request guidance:",
        "Prefer a direct recommendation over a clarifying question when the menu has close alternatives.",
    ]

    savory_request = any(
        marker in prompt
        for marker in (
            "пицц",
            "pizza",
            "pide",
            "шаур",
            "шаверм",
            "doner",
            "döner",
            "донер",
            "кебаб",
            "kebab",
            "wrap",
            "сэндвич",
            "sandwich",
            "тост",
            "tost",
        )
    )

    if any(marker in prompt for marker in ("пицц", "pizza", "pide")):
        guidance.append(
            "The user is asking for pizza or pizza-like food. Pizza is not listed in the menu. "
            "Recommend Focaccia first, then savory bread/cheese alternatives like Pompei Magnus, "
            "Octavian or Dana Sucuklu Peynirli Tost if available. Do not recommend coffee, matcha, "
            "cold drinks or desserts as pizza alternatives."
        )

    if any(
        marker in prompt
        for marker in ("шаур", "шаверм", "doner", "döner", "донер", "кебаб", "kebab", "wrap")
    ):
        guidance.append(
            "The user is asking for shawarma/doner/wrap-like savory food. Recommend savory sandwiches "
            "and toasts such as Crassus, Pompei Magnus, Octavian or Dana Sucuklu Peynirli Tost if available. "
            "Do not recommend coffee, matcha, cold drinks or desserts as similar alternatives."
        )

    if savory_request:
        guidance.append(
            "For this savory food request, drinks-only, coffee-only and dessert-only items are poor matches "
            "unless the user explicitly asks for a drink or dessert."
        )

    if any(marker in prompt for marker in ("друг", "ещё", "еще", "another", "other", "else", "more")):
        previous_names = _previous_assistant_dish_names(session)

        if previous_names:
            guidance.append(
                "The user is asking for different options. Do not repeat these dishes from earlier assistant "
                f"answers: {', '.join(previous_names)}. Recommend other suitable menu items instead."
            )
        else:
            guidance.append(
                "The user is asking for different options. Avoid repeating earlier suggestions when possible."
            )

    return "\n".join(guidance)


def build_system_instruction(session: ChatSession) -> str:
    language = normalize_language(
        getattr(
            session,
            "response_language",
            getattr(session, "interface_language", "ru"),
        )
    )

    return "\n\n".join(
        [
            RESTAURANT_ASSISTANT_SYSTEM_PROMPT,
            LANGUAGE_INSTRUCTIONS[language],
            build_menu_context(_restaurant_id_for_session(session)),
            build_user_context(session),
            build_request_context(session),
        ]
    )


def build_conversation_contents(session: ChatSession) -> list[dict]:
    messages = list(
        session.messages.order_by(
            "-created_at",
            "-id",
        )[: settings.AI_HISTORY_LIMIT]
    )
    messages.reverse()

    while messages and messages[0].role != ChatMessage.Role.USER:
        messages.pop(0)

    contents: list[dict] = []

    for message in messages:
        text = message.content.strip()

        if not text:
            continue

        role = (
            "model"
            if message.role == ChatMessage.Role.ASSISTANT
            else "user"
        )

        if contents and contents[-1]["role"] == role:
            previous_text = contents[-1]["parts"][0]["text"]
            contents[-1]["parts"][0]["text"] = f"{previous_text}\n\n{text}"
        else:
            contents.append(
                {
                    "role": role,
                    "parts": [
                        {
                            "text": text,
                        }
                    ],
                }
            )

    return contents


def build_generation_config(session: ChatSession) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=build_system_instruction(session),
        max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
        temperature=0.2,
    )


def get_configured_model_names() -> list[str]:
    model_names = [
        settings.GEMINI_MODEL,
        settings.GEMINI_FALLBACK_MODEL,
    ]

    return list(
        dict.fromkeys(
            str(model_name).strip()
            for model_name in model_names
            if str(model_name).strip()
        )
    )


def generate_with_model(
    model_name: str,
    session: ChatSession,
    contents: list[dict],
) -> AIResult:
    client = get_gemini_client()

    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=build_generation_config(session),
    )

    answer = (response.text or "").strip()

    if not answer:
        raise EmptyAIResponseError(f"Model {model_name} returned empty text.")

    return AIResult(
        text=answer,
        model_name=model_name,
    )


def stream_with_model(
    model_name: str,
    session: ChatSession,
    contents: list[dict],
):
    client = get_gemini_client()

    return client.models.generate_content_stream(
        model=model_name,
        contents=contents,
        config=build_generation_config(session),
    )


def generate_ai_answer_stream(session: ChatSession):
    contents = build_conversation_contents(session)

    if not contents:
        raise AIServiceError("Conversation has no user messages.")

    model_names = get_configured_model_names()

    if not model_names:
        raise AIServiceError("No Gemini models are configured.")

    last_error: Exception | None = None

    for model_name in model_names:
        try:
            return model_name, stream_with_model(
                model_name=model_name,
                session=session,
                contents=contents,
            )
        except (errors.APIError, EmptyAIResponseError, ImproperlyConfigured) as exc:
            last_error = exc

            if isinstance(exc, errors.APIError):
                status_code = getattr(exc, "code", None)

                if status_code not in RETRYABLE_ERROR_CODES:
                    logger.exception("Gemini streaming request failed with non-retryable error.")
                    break

            logger.warning(
                "Gemini streaming model %s failed, trying fallback if configured.",
                model_name,
                exc_info=True,
            )

    raise AIServiceError("All Gemini streaming models failed.") from last_error


def generate_ai_answer(session: ChatSession) -> AIResult:
    contents = build_conversation_contents(session)

    if not contents:
        raise AIServiceError("Conversation has no user messages.")

    model_names = get_configured_model_names()

    if not model_names:
        raise AIServiceError("No Gemini models are configured.")

    last_error: Exception | None = None

    for model_name in model_names:
        try:
            return generate_with_model(
                model_name=model_name,
                session=session,
                contents=contents,
            )
        except ImproperlyConfigured as exc:
            raise AIServiceError("AI service is not configured.") from exc
        except EmptyAIResponseError as exc:
            last_error = exc
            logger.warning("Gemini returned empty text. Model: %s", model_name)
        except errors.APIError as exc:
            last_error = exc
            error_code = getattr(exc, "code", None)
            logger.warning(
                "Gemini API error. Model: %s, code: %s",
                model_name,
                error_code,
            )

            if error_code not in RETRYABLE_ERROR_CODES:
                raise AIServiceError("AI service request failed.") from exc

    raise AIServiceError("All configured Gemini models are unavailable.") from last_error
