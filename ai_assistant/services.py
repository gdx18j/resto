import logging
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from accounts.models import UserAllergy
from menu.models import DishAllergen
from menu.translations import (
    localized_category_values,
    localized_dish_string,
    normalize_language,
)

from .models import ChatMessage, ChatSession
from .prompts import RESTAURANT_ASSISTANT_SYSTEM_PROMPT
from .retrieval import (
    RetrievalResult,
    is_other_options_request,
    retrieve_menu_dishes,
)


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
    "ru": "Response language: Russian. Answer in natural Russian.",
    "en": "Response language: English. Answer in clear natural English.",
    "tr": "Response language: Turkish. Answer in clear natural Turkish.",
}

LOCAL_FALLBACK_MESSAGES = {
    "ru": {
        "with_dishes": (
            "Сейчас внешний ИИ временно недоступен, но по опубликованному меню "
            "могу предложить: {names}."
        ),
        "without_dishes": (
            "Сейчас внешний ИИ временно недоступен, а подходящих опубликованных "
            "позиций по этому запросу не найдено. Попробуйте немного изменить запрос."
        ),
    },
    "en": {
        "with_dishes": (
            "The external AI is temporarily unavailable, but based on the published "
            "menu I can suggest: {names}."
        ),
        "without_dishes": (
            "The external AI is temporarily unavailable, and I could not find suitable "
            "published menu items for this request. Try rephrasing it."
        ),
    },
    "tr": {
        "with_dishes": (
            "Harici yapay zekâ şu anda geçici olarak kullanılamıyor, ancak yayımlanan "
            "menüye göre şunları önerebilirim: {names}."
        ),
        "without_dishes": (
            "Harici yapay zekâ şu anda geçici olarak kullanılamıyor ve bu istek için "
            "uygun yayımlanmış menü öğesi bulamadım. İsteği farklı yazmayı deneyin."
        ),
    },
}


class AIServiceError(Exception):
    def __init__(self, message, *, code="ai_service_error"):
        super().__init__(message)
        self.code = code


class EmptyAIResponseError(Exception):
    pass


class InvalidAIResponseError(Exception):
    pass


class AssistantResponsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    recommended_dish_ids: list[StrictInt] = Field(
        default_factory=list,
        max_length=3,
    )


@dataclass(frozen=True)
class AIProviderUsage:
    prompt_tokens: int = 0
    response_tokens: int = 0
    total_tokens: int = 0
    response_id: str = ""


@dataclass(frozen=True)
class AIResult:
    text: str
    model_name: str
    recommended_dish_ids: tuple[int, ...] = ()
    provider_usage: AIProviderUsage | None = None


@dataclass(frozen=True)
class AIRequestBundle:
    contents: list[dict]
    config: types.GenerateContentConfig
    candidate_dish_ids: tuple[int, ...]


@dataclass(frozen=True)
class AIStreamHandle:
    model_name: str
    stream: object
    candidate_dish_ids: tuple[int, ...]


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    api_key = settings.GEMINI_API_KEY.strip()

    if not api_key:
        raise ImproperlyConfigured("GEMINI_API_KEY is not configured.")

    if api_key.casefold() in INVALID_API_KEY_PLACEHOLDERS:
        raise ImproperlyConfigured(
            "GEMINI_API_KEY contains a placeholder value."
        )

    timeout_seconds = max(
        1,
        int(getattr(settings, "AI_PROVIDER_TIMEOUT_SECONDS", 45)),
    )
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_seconds * 1000),
    )


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


def _require_session_restaurant_id(session: ChatSession) -> int:
    if not session.restaurant_id:
        raise AIServiceError(
            "AI chat session has no restaurant context."
        )

    return session.restaurant_id


def _latest_user_message_text(session: ChatSession) -> str:
    message = (
        session.messages.filter(role=ChatMessage.Role.USER)
        .order_by("-created_at", "-id")
        .first()
    )

    return message.content if message else ""


def _previous_recommended_dish_ids(session: ChatSession) -> set[int]:
    ids = set()

    for values in session.messages.filter(
        role=ChatMessage.Role.ASSISTANT,
    ).values_list("recommended_dish_ids", flat=True):
        if not isinstance(values, list):
            continue

        for value in values:
            if isinstance(value, int) and not isinstance(value, bool):
                ids.add(value)

    return ids


def _retrieve_for_session(session: ChatSession) -> RetrievalResult:
    prompt = _latest_user_message_text(session)
    language = normalize_language(
        getattr(
            session,
            "response_language",
            getattr(session, "interface_language", "ru"),
        )
    )
    excluded_ids = (
        _previous_recommended_dish_ids(session)
        if is_other_options_request(prompt)
        else set()
    )

    return retrieve_menu_dishes(
        restaurant_id=_require_session_restaurant_id(session),
        prompt=prompt,
        language=language,
        excluded_dish_ids=excluded_ids,
    )


def _build_menu_context_from_retrieval(
    retrieval: RetrievalResult,
    *,
    language="ru",
) -> str:
    language = normalize_language(language)
    lines = [
        "menu_candidates:",
        (
            "The server selected these candidates from the current restaurant menu. "
            "Use only these dish_id values in recommended_dish_ids."
        ),
    ]

    for dish in retrieval.dishes:
        ingredients = []
        contains_allergens = set()
        trace_allergens = set()

        for link in dish.allergen_links.all():
            if (
                link.verification_status
                != DishAllergen.VerificationStatus.VERIFIED
                or link.reviewed_recipe_revision != dish.recipe_revision
            ):
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

        category_name = (
            localized_category_values(dish.category)[language]
            if dish.category_id
            else "Other"
        )
        facts = [
            f"dish_id: {dish.id}",
            f"name: {localized_dish_string(dish, 'name', language)}",
            f"category: {category_name}",
            f"price: {dish.price}",
            (
                "description: "
                f"{_trim_text(localized_dish_string(dish, 'description', language))}"
            ),
            f"ingredients: {_format_list(ingredients)}",
            f"contains_allergens: {_format_list(sorted(contains_allergens))}",
            f"trace_allergens: {_format_list(sorted(trace_allergens))}",
            f"allergen_data_status: {dish.public_allergen_data_status}",
            (
                "allergen_data_complete: yes"
                if dish.is_allergen_review_complete
                else "allergen_data_complete: no"
            ),
        ]

        if dish.serving_weight_g:
            facts.append(f"weight_g: {dish.serving_weight_g}")

        if dish.calories_kcal_per_serving:
            facts.append(f"calories_kcal: {dish.calories_kcal_per_serving}")

        if dish.preparation_time_minutes:
            facts.append(f"prep_minutes: {dish.preparation_time_minutes}")

        lines.append("- " + "; ".join(facts))

    if not retrieval.dishes:
        lines.append("- No active available dishes matched the current request.")

    return "\n".join(lines)


def build_menu_context(
    restaurant_id,
    prompt="",
    language="ru",
    excluded_dish_ids=(),
) -> str:
    if not restaurant_id:
        raise AIServiceError("restaurant_id is required for AI menu context.")

    retrieval = retrieve_menu_dishes(
        restaurant_id=restaurant_id,
        prompt=prompt,
        language=language,
        excluded_dish_ids=excluded_dish_ids,
    )
    return _build_menu_context_from_retrieval(
        retrieval,
        language=language,
    )


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

    allergen_names = [record.allergen.name for record in allergens]

    return (
        "Visitor profile: authenticated user. Confirmed allergy names shared "
        f"with explicit consent: {_format_list(allergen_names)}. "
        "No other profile fields are included."
    )


def build_request_context(session: ChatSession, retrieval: RetrievalResult) -> str:
    prompt = _latest_user_message_text(session).strip()
    excluded = retrieval.excluded_dish_ids
    guidance = [
        "Current request guidance:",
        f"User request: {_trim_text(prompt, max_length=1000)}",
        (
            "Give a direct answer when the retrieved candidates contain reasonable "
            "options. Do not invent an exact menu match that is absent from the candidates."
        ),
    ]

    if excluded:
        guidance.append(
            "The user requested different options. Do not recommend these previously "
            f"recommended dish IDs again: {', '.join(map(str, excluded))}."
        )

    return "\n".join(guidance)


def build_system_instruction(
    session: ChatSession,
    retrieval: RetrievalResult,
) -> str:
    language = normalize_language(
        getattr(
            session,
            "response_language",
            getattr(session, "interface_language", "ru"),
        )
    )
    restaurant = session.restaurant

    return "\n\n".join(
        [
            RESTAURANT_ASSISTANT_SYSTEM_PROMPT,
            f"Current restaurant: {restaurant.name} (restaurant_id: {restaurant.id}).",
            LANGUAGE_INSTRUCTIONS[language],
            _build_menu_context_from_retrieval(retrieval, language=language),
            build_user_context(session),
            build_request_context(session, retrieval),
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

        role = "model" if message.role == ChatMessage.Role.ASSISTANT else "user"

        if contents and contents[-1]["role"] == role:
            previous_text = contents[-1]["parts"][0]["text"]
            contents[-1]["parts"][0]["text"] = f"{previous_text}\n\n{text}"
        else:
            contents.append(
                {
                    "role": role,
                    "parts": [{"text": text}],
                }
            )

    return contents


def _build_generation_config(
    session: ChatSession,
    retrieval: RetrievalResult,
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=build_system_instruction(session, retrieval),
        max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
        temperature=0.2,
        response_mime_type="application/json",
        response_schema=AssistantResponsePayload,
    )


def _prepare_ai_request(session: ChatSession) -> AIRequestBundle:
    contents = build_conversation_contents(session)

    if not contents:
        raise AIServiceError("Conversation has no user messages.")

    retrieval = _retrieve_for_session(session)

    return AIRequestBundle(
        contents=contents,
        config=_build_generation_config(session, retrieval),
        candidate_dish_ids=retrieval.candidate_ids,
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


def provider_usage_from_response(response) -> AIProviderUsage | None:
    metadata = getattr(response, "usage_metadata", None)

    if metadata is None:
        return None

    prompt_tokens = max(0, int(getattr(metadata, "prompt_token_count", 0) or 0))
    response_tokens = max(
        0,
        int(getattr(metadata, "candidates_token_count", 0) or 0),
    )
    total_tokens = max(0, int(getattr(metadata, "total_token_count", 0) or 0))

    if total_tokens <= 0:
        total_tokens = prompt_tokens + response_tokens

    return AIProviderUsage(
        prompt_tokens=prompt_tokens,
        response_tokens=response_tokens,
        total_tokens=total_tokens,
        response_id=str(getattr(response, "response_id", "") or ""),
    )


def is_provider_timeout_error(exc):
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return True

    error_text = str(exc).casefold()
    return "timeout" in error_text or "timed out" in error_text


def _service_error_code(exc):
    if isinstance(exc, ImproperlyConfigured):
        return "ai_not_configured"
    if is_provider_timeout_error(exc):
        return "provider_timeout"
    return "ai_service_error"


def parse_ai_response(
    raw_text,
    *,
    model_name,
    candidate_dish_ids,
    provider_usage=None,
) -> AIResult:
    raw_text = str(raw_text or "").strip()

    if not raw_text:
        raise EmptyAIResponseError(f"Model {model_name} returned empty text.")

    try:
        payload = AssistantResponsePayload.model_validate_json(raw_text)
    except ValidationError as exc:
        raise InvalidAIResponseError(
            f"Model {model_name} returned invalid structured output."
        ) from exc

    answer = payload.answer.strip()

    if not answer:
        raise EmptyAIResponseError(f"Model {model_name} returned empty answer.")

    allowed_ids = set(candidate_dish_ids)
    recommendation_ids = []

    for dish_id in payload.recommended_dish_ids:
        if dish_id not in allowed_ids or dish_id in recommendation_ids:
            continue

        recommendation_ids.append(dish_id)

        if len(recommendation_ids) >= 3:
            break

    return AIResult(
        text=answer,
        model_name=model_name,
        recommended_dish_ids=tuple(recommendation_ids),
        provider_usage=provider_usage,
    )


def generate_with_model(
    model_name: str,
    bundle: AIRequestBundle,
) -> AIResult:
    client = get_gemini_client()
    response = client.models.generate_content(
        model=model_name,
        contents=bundle.contents,
        config=bundle.config,
    )

    return parse_ai_response(
        response.text,
        model_name=model_name,
        candidate_dish_ids=bundle.candidate_dish_ids,
        provider_usage=provider_usage_from_response(response),
    )


def stream_with_model(
    model_name: str,
    bundle: AIRequestBundle,
):
    client = get_gemini_client()

    return client.models.generate_content_stream(
        model=model_name,
        contents=bundle.contents,
        config=bundle.config,
    )


def parse_streamed_ai_response(
    handle: AIStreamHandle,
    raw_text,
    response=None,
) -> AIResult:
    return parse_ai_response(
        raw_text,
        model_name=handle.model_name,
        candidate_dish_ids=handle.candidate_dish_ids,
        provider_usage=(
            provider_usage_from_response(response)
            if response is not None
            else None
        ),
    )


def build_local_fallback_result(session: ChatSession) -> AIResult:
    retrieval = _retrieve_for_session(session)
    language = normalize_language(
        getattr(
            session,
            "response_language",
            getattr(session, "interface_language", "ru"),
        )
    )
    selected = retrieval.dishes[:3]
    messages = LOCAL_FALLBACK_MESSAGES[language]

    if selected:
        names = ", ".join(
            localized_dish_string(dish, "name", language)
            for dish in selected
        )
        answer = messages["with_dishes"].format(names=names)
    else:
        answer = messages["without_dishes"]

    return AIResult(
        text=answer,
        model_name="local-menu-fallback",
        recommended_dish_ids=tuple(dish.id for dish in selected),
    )


def generate_ai_answer_stream(session: ChatSession) -> AIStreamHandle:
    bundle = _prepare_ai_request(session)
    model_names = get_configured_model_names()

    if not model_names:
        raise AIServiceError("No Gemini models are configured.", code="ai_not_configured")

    last_error: Exception | None = None

    for model_name in model_names:
        try:
            return AIStreamHandle(
                model_name=model_name,
                stream=stream_with_model(model_name, bundle),
                candidate_dish_ids=bundle.candidate_dish_ids,
            )
        except (
            errors.APIError,
            ImproperlyConfigured,
            httpx.TimeoutException,
            TimeoutError,
        ) as exc:
            last_error = exc

            if is_provider_timeout_error(exc):
                logger.warning(
                    "Gemini streaming request timed out. Model: %s",
                    model_name,
                )
                break

            if isinstance(exc, errors.APIError):
                status_code = getattr(exc, "code", None)

                if status_code not in RETRYABLE_ERROR_CODES:
                    logger.exception(
                        "Gemini streaming request failed with non-retryable error."
                    )
                    break

            logger.warning(
                "Gemini streaming model %s failed, trying fallback if configured.",
                model_name,
                exc_info=True,
            )

    error_code = _service_error_code(last_error)
    raise AIServiceError(
        "All Gemini streaming models failed.",
        code=error_code,
    ) from last_error


def generate_ai_answer(session: ChatSession) -> AIResult:
    bundle = _prepare_ai_request(session)
    model_names = get_configured_model_names()

    if not model_names:
        raise AIServiceError("No Gemini models are configured.", code="ai_not_configured")

    last_error: Exception | None = None

    for model_name in model_names:
        try:
            return generate_with_model(
                model_name=model_name,
                bundle=bundle,
            )
        except ImproperlyConfigured as exc:
            raise AIServiceError("AI service is not configured.", code="ai_not_configured") from exc
        except (EmptyAIResponseError, InvalidAIResponseError) as exc:
            last_error = exc
            logger.warning(
                "Gemini returned invalid structured output. Model: %s",
                model_name,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            last_error = exc
            logger.warning(
                "Gemini request timed out. Model: %s",
                model_name,
            )
            break
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

    error_code = _service_error_code(last_error)
    raise AIServiceError(
        "All configured Gemini models are unavailable.",
        code=error_code,
    ) from last_error
