import logging
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from google import genai
from google.genai import errors, types

from accounts.models import UserAllergy
from menu.models import Dish

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
    if not settings.GEMINI_API_KEY.strip():
        raise ImproperlyConfigured("GEMINI_API_KEY is not configured.")

    return genai.Client(api_key=settings.GEMINI_API_KEY.strip())


def _format_list(values):
    values = [str(value).strip() for value in values if str(value).strip()]
    return ", ".join(values) if values else "not specified"


def _trim_text(value, max_length=240):
    value = " ".join(str(value or "").split())

    if len(value) <= max_length:
        return value

    return f"{value[: max_length - 1].rstrip()}..."


def build_menu_context() -> str:
    dishes = (
        Dish.objects.filter(
            is_active=True,
            is_available=True,
        )
        .select_related("category")
        .prefetch_related(
            "dish_ingredients__ingredient__allergens",
            "may_contain_allergens",
        )
        .order_by("category__name", "name")[: settings.AI_MENU_CONTEXT_LIMIT]
    )

    lines = [
        "Current restaurant menu data. Use only these dishes, prices, ingredients, allergens and availability facts:",
    ]

    for dish in dishes:
        ingredients = []
        allergens = {
            allergen.name
            for allergen in dish.may_contain_allergens.all()
        }

        for dish_ingredient in dish.dish_ingredients.all():
            ingredient = dish_ingredient.ingredient
            label = ingredient.name

            if dish_ingredient.can_be_removed:
                label = f"{label} (can be removed)"

            ingredients.append(label)

            for allergen in ingredient.allergens.all():
                allergens.add(allergen.name)

        facts = [
            f"name: {dish.name}",
            f"category: {dish.category.name if dish.category else 'Other'}",
            f"price: {dish.price}",
            f"description: {_trim_text(dish.description)}",
            f"ingredients: {_format_list(ingredients)}",
            f"allergens: {_format_list(sorted(allergens))}",
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

    allergens = UserAllergy.objects.filter(
        user=session.user,
        status=UserAllergy.Status.CONFIRMED,
    ).select_related("allergen")

    allergen_names = [
        record.allergen.name
        for record in allergens
    ]

    return (
        "Visitor profile: authenticated user. Confirmed allergies: "
        f"{_format_list(allergen_names)}."
    )


def build_system_instruction(session: ChatSession) -> str:
    return "\n\n".join(
        [
            RESTAURANT_ASSISTANT_SYSTEM_PROMPT,
            build_menu_context(),
            build_user_context(session),
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
        temperature=0.35,
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
