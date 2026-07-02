import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserAllergy
from menu.models import Allergen, Category, Dish

from .models import AIUsageEvent, ChatMessage, ChatSession
from .services import (
    AIResult,
    AIServiceError,
    build_menu_context,
    build_user_context,
    detect_response_language,
    get_configured_model_names,
    get_gemini_client,
)
from .throttling import AIStreamSlot


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

    def test_detect_response_language_from_latest_message(self):
        self.assertEqual(
            detect_response_language("Can you recommend a sandwich?", fallback="ru"),
            "en",
        )
        self.assertEqual(
            detect_response_language("Bana tatlı önerir misin?", fallback="ru"),
            "tr",
        )
        self.assertEqual(
            detect_response_language("Посоветуй десерт", fallback="en"),
            "ru",
        )
        self.assertEqual(
            detect_response_language("Хочу Focaccia", fallback="en"),
            "ru",
        )

    def test_user_context_does_not_share_allergies_without_consent(self):
        user = get_user_model().objects.create_user(
            email="private-allergy@example.com",
            password="strong-pass-123",
        )
        allergen = Allergen.objects.create(
            name="Тестовое молоко private",
            code="test-milk-private",
        )
        UserAllergy.objects.create(
            user=user,
            allergen=allergen,
            status=UserAllergy.Status.CONFIRMED,
        )
        session = ChatSession.objects.create(user=user, session_key="private")

        context = build_user_context(session)

        self.assertIn("sharing with the external AI provider is disabled", context)
        self.assertNotIn("Тестовое молоко private", context)
        self.assertNotIn(user.email, context)

    def test_user_context_shares_minimized_allergies_with_consent(self):
        user = get_user_model().objects.create_user(
            email="shared-allergy@example.com",
            password="strong-pass-123",
            share_allergies_with_ai=True,
        )
        allergen = Allergen.objects.create(
            name="Тестовое молоко shared",
            code="test-milk-shared",
        )
        UserAllergy.objects.create(
            user=user,
            allergen=allergen,
            status=UserAllergy.Status.CONFIRMED,
        )
        session = ChatSession.objects.create(user=user, session_key="shared")

        context = build_user_context(session)

        self.assertIn("Тестовое молоко shared", context)
        self.assertIn("No other profile fields are included", context)
        self.assertNotIn(user.email, context)


class AskViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def post_prompt(self, prompt, session_id=None, language=None):
        payload = {
            "prompt": prompt,
        }

        if session_id:
            payload["session_id"] = session_id

        if language:
            payload["language"] = language

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

    @override_settings(
        RATE_LIMIT_RULES={
            "ai_assistant:ask": {
                "methods": ["POST"],
                "identity": "ip",
                "limits": [
                    {
                        "name": "test",
                        "limit": 1,
                        "window": 60,
                    }
                ],
            }
        }
    )
    def test_app_rate_limit_blocks_ai_ask_endpoint(self):
        payload = {
            "prompt": "",
        }

        first_response = self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        second_response = self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(first_response.status_code, 400)
        self.assertEqual(second_response.status_code, 429)
        self.assertEqual(second_response["Retry-After"], "60")
        self.assertEqual(second_response.json()["code"], "rate_limited")

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
        usage_event = AIUsageEvent.objects.get()
        self.assertEqual(usage_event.status, AIUsageEvent.Status.COMPLETED)
        self.assertEqual(usage_event.model_name, "gemini-test")
        self.assertGreater(usage_event.estimated_total_tokens, 0)

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="I recommend Focaccia.",
            model_name="gemini-test",
        ),
    )
    def test_response_language_follows_prompt_language(self, generate_ai_answer_mock):
        response = self.post_prompt(
            "Can you recommend something savory?",
            language="ru",
        )

        self.assertEqual(response.status_code, 200)

        session = generate_ai_answer_mock.call_args.args[0]
        self.assertEqual(session.interface_language, "ru")
        self.assertEqual(session.response_language, "en")

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

    @override_settings(
        AI_DAILY_QUOTA_GUEST=1,
        AI_DAILY_QUOTA_IP=100,
        AI_DAILY_TOKEN_BUDGET_GUEST=999999,
        AI_DAILY_TOKEN_BUDGET_IP=999999,
        AI_RATE_LIMIT_GUEST_PER_MINUTE=100,
        AI_RATE_LIMIT_IP_PER_MINUTE=100,
    )
    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="First answer",
            model_name="gemini-test",
        ),
    )
    def test_guest_daily_quota_blocks_second_request(self, generate_ai_answer_mock):
        first_response = self.post_prompt("Hello")
        second_response = self.post_prompt("Again")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 429)
        self.assertGreater(int(second_response["Retry-After"]), 0)
        self.assertEqual(generate_ai_answer_mock.call_count, 1)
        self.assertEqual(ChatSession.objects.count(), 1)
        self.assertEqual(
            AIUsageEvent.objects.filter(
                status=AIUsageEvent.Status.THROTTLED,
                limit_reason="actor_daily_quota",
            ).count(),
            1,
        )

    @override_settings(
        AI_DAILY_TOKEN_BUDGET_GUEST=1,
        AI_DAILY_TOKEN_BUDGET_IP=999999,
        AI_DAILY_QUOTA_GUEST=100,
        AI_DAILY_QUOTA_IP=100,
        AI_RATE_LIMIT_GUEST_PER_MINUTE=100,
        AI_RATE_LIMIT_IP_PER_MINUTE=100,
    )
    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Should not be called",
            model_name="gemini-test",
        ),
    )
    def test_guest_token_budget_blocks_before_gemini(self, generate_ai_answer_mock):
        response = self.post_prompt("Hello")

        self.assertEqual(response.status_code, 429)
        generate_ai_answer_mock.assert_not_called()
        self.assertEqual(ChatSession.objects.count(), 0)
        usage_event = AIUsageEvent.objects.get()
        self.assertEqual(usage_event.status, AIUsageEvent.Status.THROTTLED)
        self.assertEqual(usage_event.limit_reason, "actor_daily_token_budget")

    @override_settings(
        AI_DAILY_COST_BUDGET_MICROS_GUEST=1,
        AI_DAILY_COST_BUDGET_MICROS_IP=0,
        AI_ESTIMATED_COST_MICROS_PER_1000_TOKENS=1000,
        AI_DAILY_TOKEN_BUDGET_GUEST=999999,
        AI_DAILY_TOKEN_BUDGET_IP=999999,
        AI_DAILY_QUOTA_GUEST=100,
        AI_DAILY_QUOTA_IP=100,
        AI_RATE_LIMIT_GUEST_PER_MINUTE=100,
        AI_RATE_LIMIT_IP_PER_MINUTE=100,
    )
    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Should not be called",
            model_name="gemini-test",
        ),
    )
    def test_guest_cost_budget_blocks_before_gemini(self, generate_ai_answer_mock):
        response = self.post_prompt("Hello")

        self.assertEqual(response.status_code, 429)
        generate_ai_answer_mock.assert_not_called()
        usage_event = AIUsageEvent.objects.get()
        self.assertEqual(usage_event.status, AIUsageEvent.Status.THROTTLED)
        self.assertEqual(usage_event.limit_reason, "actor_daily_cost_budget")
        self.assertGreater(usage_event.estimated_cost_micros, 0)

    @patch(
        "ai_assistant.views.acquire_ai_stream_slot",
        return_value=AIStreamSlot(
            allowed=False,
            reason="actor_stream_concurrency",
            message="Слишком много запросов к ИИ. Попробуйте отправить сообщение позже.",
            retry_after=180,
        ),
    )
    @patch("ai_assistant.views.generate_ai_answer_stream")
    def test_stream_concurrency_limit_blocks_before_message(
        self,
        generate_ai_answer_stream_mock,
        acquire_ai_stream_slot_mock,
    ):
        response = self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps({"prompt": "Stream please"}),
            content_type="application/json",
            HTTP_ACCEPT="application/x-ndjson",
            HTTP_X_AI_STREAM="1",
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "180")
        acquire_ai_stream_slot_mock.assert_called_once()
        generate_ai_answer_stream_mock.assert_not_called()
        session = ChatSession.objects.get()
        self.assertEqual(session.messages.count(), 0)
        usage_event = AIUsageEvent.objects.get()
        self.assertEqual(usage_event.status, AIUsageEvent.Status.THROTTLED)
        self.assertEqual(usage_event.limit_reason, "actor_stream_concurrency")
        self.assertTrue(usage_event.is_stream)

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

    def test_authenticated_history_returns_latest_account_dialog(self):
        user = get_user_model().objects.create_user(
            email="history@example.com",
            password="strong-pass-123",
        )
        old_session = ChatSession.objects.create(
            user=user,
            session_key="old-session",
            title="Old chat",
        )
        ChatMessage.objects.create(
            session=old_session,
            role=ChatMessage.Role.USER,
            content="Старый вопрос",
        )
        latest_session = ChatSession.objects.create(
            user=user,
            session_key="latest-session",
            title="Latest chat",
        )
        user_message = ChatMessage.objects.create(
            session=latest_session,
            role=ChatMessage.Role.USER,
            content="Что посоветуешь?",
        )
        assistant_message = ChatMessage.objects.create(
            session=latest_session,
            role=ChatMessage.Role.ASSISTANT,
            content="Советую Focaccia.",
            model_name="gemini-test",
        )
        now = timezone.now()
        ChatSession.objects.filter(id=old_session.id).update(
            updated_at=now - timedelta(minutes=1),
        )
        ChatSession.objects.filter(id=latest_session.id).update(updated_at=now)
        self.client.force_login(user)

        response = self.client.get(reverse("ai_assistant:history"))

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["session_id"], str(latest_session.id))
        self.assertEqual(
            [message["text"] for message in payload["messages"]],
            [
                user_message.content,
                assistant_message.content,
            ],
        )
        self.assertTrue(payload["messages"][0]["created_at"])
        self.assertTrue(payload["messages"][1]["created_at"])

    def test_authenticated_history_can_load_requested_owned_session(self):
        user = get_user_model().objects.create_user(
            email="owned-history@example.com",
            password="strong-pass-123",
        )
        requested_session = ChatSession.objects.create(
            user=user,
            session_key="requested-session",
            title="Requested chat",
        )
        ChatMessage.objects.create(
            session=requested_session,
            role=ChatMessage.Role.USER,
            content="Верни этот диалог",
        )
        ChatSession.objects.create(
            user=user,
            session_key="latest-session",
            title="Latest chat",
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("ai_assistant:history"),
            {
                "session_id": str(requested_session.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], str(requested_session.id))

    def test_export_history_returns_only_owned_dialogs(self):
        user = get_user_model().objects.create_user(
            email="export-history@example.com",
            password="strong-pass-123",
        )
        other_user = get_user_model().objects.create_user(
            email="other-export-history@example.com",
            password="strong-pass-123",
        )
        owned_session = ChatSession.objects.create(
            user=user,
            session_key="owned-export",
            title="Owned export",
        )
        ChatMessage.objects.create(
            session=owned_session,
            role=ChatMessage.Role.USER,
            content="Мой вопрос",
        )
        other_session = ChatSession.objects.create(
            user=other_user,
            session_key="other-export",
            title="Other export",
        )
        ChatMessage.objects.create(
            session=other_session,
            role=ChatMessage.Role.USER,
            content="Чужой вопрос",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("ai_assistant:export_history"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'attachment; filename="caesar-ai-history.json"',
            response["Content-Disposition"],
        )
        payload = response.json()
        self.assertEqual(len(payload["sessions"]), 1)
        self.assertEqual(payload["sessions"][0]["id"], str(owned_session.id))
        self.assertEqual(
            payload["sessions"][0]["messages"][0]["text"],
            "Мой вопрос",
        )
        self.assertNotIn(str(other_session.id), response.content.decode("utf-8"))

    def test_delete_history_removes_only_owned_dialogs(self):
        user = get_user_model().objects.create_user(
            email="delete-history@example.com",
            password="strong-pass-123",
        )
        other_user = get_user_model().objects.create_user(
            email="other-delete-history@example.com",
            password="strong-pass-123",
        )
        owned_session = ChatSession.objects.create(
            user=user,
            session_key="owned-delete",
            title="Owned delete",
        )
        ChatMessage.objects.create(
            session=owned_session,
            role=ChatMessage.Role.USER,
            content="Удалить",
        )
        owned_event = AIUsageEvent.objects.create(
            user=user,
            chat_session=owned_session,
            status=AIUsageEvent.Status.COMPLETED,
        )
        other_session = ChatSession.objects.create(
            user=other_user,
            session_key="other-delete",
            title="Other delete",
        )
        other_event = AIUsageEvent.objects.create(
            user=other_user,
            chat_session=other_session,
            status=AIUsageEvent.Status.COMPLETED,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("ai_assistant:delete_history"),
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted"], 1)
        self.assertFalse(ChatSession.objects.filter(id=owned_session.id).exists())
        self.assertTrue(ChatSession.objects.filter(id=other_session.id).exists())
        self.assertFalse(AIUsageEvent.objects.filter(id=owned_event.id).exists())
        self.assertTrue(AIUsageEvent.objects.filter(id=other_event.id).exists())

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
        return_value=AIResult(
            text="Пиццы сейчас нет, но есть похожие варианты.",
            model_name="gemini-test",
        ),
    )
    def test_pizza_request_includes_closest_food_alternative_cards(self, generate_ai_answer_mock):
        category = Category.objects.create(name="Другие блюда")
        dish = Dish.objects.create(
            category=category,
            name="Focaccia",
            description="Итальянская фокачча с розмарином, оливками и вялеными томатами.",
            price="150.00",
            is_active=True,
            is_available=True,
        )

        response = self.post_prompt("Хочу пиццу")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommended_dishes"][0]["name"], dish.name)
        generate_ai_answer_mock.assert_called_once()

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Могу предложить Americano.",
            model_name="gemini-test",
        ),
    )
    def test_savory_request_does_not_recommend_coffee_cards(self, generate_ai_answer_mock):
        sandwich_category = Category.objects.create(name="Сэндвичи")
        coffee_category = Category.objects.create(name="Горячий кофе")
        sandwich = Dish.objects.create(
            category=sandwich_category,
            name="Crassus",
            description="Сэндвич на чиабатте с индейкой, соусами, сыром и овощами.",
            price="428.00",
            is_active=True,
            is_available=True,
        )
        Dish.objects.create(
            category=coffee_category,
            name="Americano",
            description="Горячий американо.",
            price="120.00",
            is_active=True,
            is_available=True,
        )

        response = self.post_prompt("Хочу шаурму")

        self.assertEqual(response.status_code, 200)
        names = [dish["name"] for dish in response.json()["recommended_dishes"]]
        self.assertIn(sandwich.name, names)
        self.assertNotIn("Americano", names)
        generate_ai_answer_mock.assert_called_once()

    @patch(
        "ai_assistant.views.generate_ai_answer",
        side_effect=[
            AIResult(
                text="Попробуйте Focaccia, Pompei Magnus и Octavian.",
                model_name="gemini-test",
            ),
            AIResult(
                text="Можно взять Crassus или Focaccia.",
                model_name="gemini-test",
            ),
        ],
    )
    def test_other_options_request_excludes_previous_suggestions(self, generate_ai_answer_mock):
        category = Category.objects.create(name="Сэндвичи")
        previous_dish = Dish.objects.create(
            category=category,
            name="Focaccia",
            description="Фокачча с розмарином.",
            price="150.00",
            is_active=True,
            is_available=True,
        )
        new_dish = Dish.objects.create(
            category=category,
            name="Crassus",
            description="Сэндвич на чиабатте с индейкой, соусами, сыром и овощами.",
            price="428.00",
            is_active=True,
            is_available=True,
        )

        first_response = self.post_prompt("Посоветуй что-нибудь")
        session_id = first_response.json()["session_id"]
        second_response = self.post_prompt("Дай другие варианты", session_id=session_id)

        self.assertEqual(second_response.status_code, 200)
        names = [dish["name"] for dish in second_response.json()["recommended_dishes"]]
        self.assertIn(new_dish.name, names)
        self.assertNotIn(previous_dish.name, names)
        self.assertEqual(generate_ai_answer_mock.call_count, 2)

    @patch("ai_assistant.views.generate_ai_answer_stream")
    def test_streaming_quota_error_returns_local_fallback(self, generate_ai_answer_stream_mock):
        class QuotaError(Exception):
            code = 429

        def broken_stream():
            if False:
                yield ""

            raise QuotaError("RESOURCE_EXHAUSTED quota exceeded")

        category = Category.objects.create(name="Другие блюда")
        Dish.objects.create(
            category=category,
            name="Focaccia",
            description="Фокачча с розмарином.",
            price="150.00",
            is_active=True,
            is_available=True,
        )
        generate_ai_answer_stream_mock.return_value = ("gemini-test", broken_stream())

        response = self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps({"prompt": "Хочу пиццу"}),
            content_type="application/json",
            HTTP_ACCEPT="application/x-ndjson",
            HTTP_X_AI_STREAM="1",
        )

        self.assertEqual(response.status_code, 200)
        content = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn('"type": "delta"', content)
        self.assertIn('"type": "done"', content)
        self.assertIn("Focaccia", content)
        self.assertNotIn('"type": "error"', content)

        assistant_message = ChatMessage.objects.filter(
            role=ChatMessage.Role.ASSISTANT,
        ).get()
        self.assertEqual(assistant_message.model_name, "local-quota-fallback")

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
        self.assertContains(response, "data-history-endpoint")
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
