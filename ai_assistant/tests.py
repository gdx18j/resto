import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import reverse

from menu.models import Dish

from .models import ChatMessage, ChatSession
from .services import (
    AIResult,
    AIServiceError,
    build_menu_context,
    get_configured_model_names,
    get_gemini_client,
)


class GeminiServiceTests(TestCase):
    @override_settings(GEMINI_API_KEY="")
    def test_requires_api_key(self):
        get_gemini_client.cache_clear()

        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "GEMINI_API_KEY is not configured.",
        ):
            get_gemini_client()

        get_gemini_client.cache_clear()

    def test_menu_context_handles_empty_menu(self):
        self.assertIn(
            "No active available dishes",
            build_menu_context(),
        )

    @override_settings(
        GEMINI_MODEL=" gemini-primary ",
        GEMINI_FALLBACK_MODEL="gemini-primary",
    )
    def test_configured_models_are_trimmed_and_deduplicated(self):
        self.assertEqual(
            get_configured_model_names(),
            ["gemini-primary"],
        )

    @override_settings(
        GEMINI_MODEL="",
        GEMINI_FALLBACK_MODEL="  ",
    )
    def test_configured_models_skip_empty_values(self):
        self.assertEqual(get_configured_model_names(), [])


class AskViewTests(TestCase):
    def post_prompt(self, prompt, session_id=None):
        payload = {
            "prompt": prompt,
        }

        if session_id:
            payload["session_id"] = session_id

        return self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_rejects_empty_prompt(self):
        response = self.post_prompt("")

        self.assertEqual(response.status_code, 400)

    def test_rejects_invalid_json(self):
        response = self.client.post(
            reverse("ai_assistant:ask"),
            data="{",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("JSON", response.json()["error"])

    def test_rejects_non_object_json(self):
        response = self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps([]),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_rejects_non_string_prompt(self):
        response = self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps({"prompt": 123}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Hello from Gemini",
            model_name="gemini-test",
        ),
    )
    def test_anonymous_user_can_get_answer(self, generate_ai_answer_mock):
        response = self.post_prompt("Hello")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Hello from Gemini")

        session = ChatSession.objects.get()
        self.assertIsNone(session.user)
        self.assertTrue(session.session_key)
        self.assertEqual(session.messages.count(), 2)
        generate_ai_answer_mock.assert_called_once_with(session)

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Second answer",
            model_name="gemini-test",
        ),
    )
    def test_anonymous_user_can_continue_session(self, generate_ai_answer_mock):
        first_response = self.post_prompt("Hello")
        session_id = first_response.json()["session_id"]

        second_response = self.post_prompt(
            "Continue",
            session_id=session_id,
        )

        self.assertEqual(second_response.status_code, 200)

        session = ChatSession.objects.get(id=session_id)
        self.assertEqual(session.messages.count(), 4)
        self.assertEqual(generate_ai_answer_mock.call_count, 2)

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Private answer",
            model_name="gemini-test",
        ),
    )
    def test_authenticated_user_session_is_saved_to_user(self, generate_ai_answer_mock):
        user = get_user_model().objects.create_user(
            email="guest@example.com",
            password="strong-pass-123",
        )
        self.client.force_login(user)

        response = self.post_prompt("Hello")

        self.assertEqual(response.status_code, 200)

        session = ChatSession.objects.get()
        self.assertEqual(session.user, user)
        self.assertEqual(
            session.messages.filter(role=ChatMessage.Role.ASSISTANT).count(),
            1,
        )
        generate_ai_answer_mock.assert_called_once_with(session)

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Советую Caesar Salad: легкий салат с понятным составом.",
            model_name="gemini-test",
        ),
    )
    def test_answer_includes_recommended_dish_cards(self, generate_ai_answer_mock):
        dish = Dish.objects.create(
            name="Caesar Salad",
            description="Салат с курицей, соусом и хрустящими гренками.",
            price="590.00",
            is_active=True,
            is_available=True,
        )

        response = self.post_prompt("Посоветуй салат")

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["recommended_dishes"][0]["name"], dish.name)
        self.assertEqual(
            payload["recommended_dishes"][0]["url"],
            f"{reverse('menu:dish_list')}#dish-{dish.id}",
        )
        generate_ai_answer_mock.assert_called_once()

    @patch(
        "ai_assistant.views.generate_ai_answer",
        side_effect=AIServiceError("Gemini is unavailable"),
    )
    def test_ai_failure_returns_session_id(self, generate_ai_answer_mock):
        with self.assertLogs("ai_assistant.views", level="ERROR"):
            response = self.post_prompt("Hello")

        self.assertEqual(response.status_code, 503)

        payload = response.json()
        self.assertIn("session_id", payload)

        session = ChatSession.objects.get(id=payload["session_id"])
        self.assertEqual(session.messages.count(), 1)
        self.assertEqual(session.messages.get().role, ChatMessage.Role.USER)
        generate_ai_answer_mock.assert_called_once_with(session)


class AssistantWidgetTests(TestCase):
    def test_menu_page_includes_ai_widget(self):
        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-ai-assistant")
        self.assertContains(response, "ai-assistant.css")
        self.assertContains(response, "ai-assistant.js")

    def test_menu_dish_cards_have_stable_ai_links(self):
        dish = Dish.objects.create(
            name="Caesar Salad",
            description="Салат с курицей.",
            price="590.00",
            is_active=True,
            is_available=True,
        )

        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="dish-{dish.id}"')

    def test_standalone_ai_page_is_removed(self):
        response = self.client.get("/ai/")

        self.assertEqual(response.status_code, 404)
