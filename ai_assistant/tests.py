import json
import uuid

import httpx
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserAllergy
from menu.allergen_review import review_dish_allergen_link
from menu.models import Allergen, Category, Dish, DishAllergen
from orders.models import Restaurant, Table

from .models import AIRequestRecord, AIUsageEvent, ChatMessage, ChatSession
from .services import (
    AIProviderUsage,
    AIResult,
    AIServiceError,
    AIStreamHandle,
    build_menu_context,
    build_user_context,
    detect_response_language,
    get_configured_model_names,
    generate_ai_answer,
    get_gemini_client,
    parse_ai_response,
)
from .retrieval import retrieve_menu_dishes
from .throttling import (
    AIQuotaReservation,
    AIStreamSlot,
    ReservedCounter,
    _acquire_lease,
    _release_lease,
    acquire_ai_request_slot,
    reconcile_ai_quota_reservation,
    release_ai_request_slot,
)


class GeminiServiceTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(
            name="AI Service Test Restaurant",
            slug="ai-service-test",
        )

    @override_settings(GEMINI_API_KEY="")
    def test_requires_api_key(self):
        get_gemini_client.cache_clear()

        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "GEMINI_API_KEY is not configured.",
        ):
            get_gemini_client()

        get_gemini_client.cache_clear()

    @override_settings(GEMINI_API_KEY="replace-with-new-gemini-api-key")
    def test_rejects_placeholder_api_key(self):
        get_gemini_client.cache_clear()

        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "GEMINI_API_KEY contains a placeholder value.",
        ):
            get_gemini_client()

        get_gemini_client.cache_clear()

    def test_menu_context_handles_empty_menu(self):
        self.assertIn(
            "No active available dishes",
            build_menu_context(self.restaurant.id),
        )

    def test_menu_context_uses_supplied_restaurant_id(self):
        restaurant_b = Restaurant.objects.create(
            name="AI Branch B",
            slug="ai-branch-b",
        )
        category_b = Category.objects.create(
            restaurant=restaurant_b,
            name="AI Menu B",
        )
        Dish.objects.create(
            restaurant=restaurant_b,
            category=category_b,
            name="Only AI Branch B",
            price="250.00",
            is_active=True,
            is_available=True,
        )
        default_category = Category.objects.create(name="Default AI Menu")
        Dish.objects.create(
            category=default_category,
            name="Default AI Dish",
            price="100.00",
            is_active=True,
            is_available=True,
        )

        context = build_menu_context(restaurant_b.id)

        self.assertIn("Only AI Branch B", context)
        self.assertNotIn("Default AI Dish", context)

    def test_menu_context_uses_only_verified_dish_allergens(self):
        category = Category.objects.create(name="AI Allergens")
        dish = Dish.objects.create(
            category=category,
            name="Allergen test dish",
            price="100.00",
            is_active=True,
            is_available=True,
        )
        verified = Allergen.objects.create(
            name="Verified milk",
            code="verified-milk-ai",
        )
        trace = Allergen.objects.create(
            name="Verified trace nuts",
            code="verified-trace-nuts-ai",
        )
        suggested = Allergen.objects.create(
            name="Suggested soy",
            code="suggested-soy-ai",
        )
        verified_link = DishAllergen.objects.create(
            dish=dish,
            allergen=verified,
            relation_type=DishAllergen.RelationType.CONTAINS,
            source=DishAllergen.Source.RECIPE,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )
        trace_link = DishAllergen.objects.create(
            dish=dish,
            allergen=trace,
            relation_type=DishAllergen.RelationType.CROSS_CONTAMINATION,
            source=DishAllergen.Source.MANUAL,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )
        review_dish_allergen_link(
            verified_link.pk,
            decision=DishAllergen.VerificationStatus.VERIFIED,
            actor=None,
        )
        review_dish_allergen_link(
            trace_link.pk,
            decision=DishAllergen.VerificationStatus.VERIFIED,
            actor=None,
        )
        DishAllergen.objects.create(
            dish=dish,
            allergen=suggested,
            relation_type=DishAllergen.RelationType.CONTAINS,
            source=DishAllergen.Source.HEURISTIC,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        )

        context = build_menu_context(dish.restaurant_id)

        self.assertIn("contains_allergens: Verified milk", context)
        self.assertIn("trace_allergens: Verified trace nuts", context)
        self.assertNotIn("Suggested soy", context)

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
        session = ChatSession.objects.create(
            user=user,
            restaurant=self.restaurant,
            session_key="private",
        )

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
        session = ChatSession.objects.create(
            user=user,
            restaurant=self.restaurant,
            session_key="shared",
        )

        context = build_user_context(session)

        self.assertIn("Тестовое молоко shared", context)
        self.assertIn("No other profile fields are included", context)
        self.assertNotIn(user.email, context)

    def test_menu_context_includes_stable_dish_ids(self):
        dish = Dish.objects.create(
            restaurant=self.restaurant,
            name="Structured menu dish",
            price="190.00",
            is_active=True,
            is_available=True,
        )

        context = build_menu_context(
            self.restaurant.id,
            prompt="Structured menu dish",
        )

        self.assertIn(f"dish_id: {dish.id}", context)
        self.assertIn("menu_candidates", context)

    def test_structured_response_filters_unknown_and_duplicate_ids(self):
        result = parse_ai_response(
            json.dumps(
                {
                    "answer": "Try the first option.",
                    "recommended_dish_ids": [11, 999, 11],
                }
            ),
            model_name="gemini-test",
            candidate_dish_ids=(11, 12),
        )

        self.assertEqual(result.text, "Try the first option.")
        self.assertEqual(result.recommended_dish_ids, (11,))

    def test_retrieval_uses_current_menu_data_instead_of_named_rules(self):
        food_category = Category.objects.create(
            restaurant=self.restaurant,
            name="Hot meals",
        )
        drink_category = Category.objects.create(
            restaurant=self.restaurant,
            name="Coffee",
        )
        matching = Dish.objects.create(
            restaurant=self.restaurant,
            category=food_category,
            name="Turkey Fire Wrap",
            description="Spicy turkey sandwich with vegetables",
            price="390.00",
            is_active=True,
            is_available=True,
        )
        Dish.objects.create(
            restaurant=self.restaurant,
            category=drink_category,
            name="Dark Roast",
            description="Hot black coffee",
            price="150.00",
            is_active=True,
            is_available=True,
        )

        result = retrieve_menu_dishes(
            restaurant_id=self.restaurant.id,
            prompt="Recommend a spicy turkey sandwich",
            language="en",
            limit=2,
        )

        self.assertEqual(result.dishes[0].id, matching.id)


    @override_settings(
        GEMINI_MODEL="gemini-primary",
        GEMINI_FALLBACK_MODEL="gemini-fallback",
    )
    @patch("ai_assistant.services._prepare_ai_request", return_value=object())
    @patch(
        "ai_assistant.services.generate_with_model",
        side_effect=httpx.ReadTimeout("provider timed out"),
    )
    def test_provider_timeout_does_not_double_total_deadline_with_fallback(
        self,
        generate_with_model_mock,
        _prepare_request_mock,
    ):
        session = ChatSession(restaurant=self.restaurant)

        with self.assertRaises(AIServiceError) as error_context:
            generate_ai_answer(session)

        self.assertEqual(error_context.exception.code, "provider_timeout")
        self.assertEqual(generate_with_model_mock.call_count, 1)


class AskViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.restaurant, _ = Restaurant.objects.get_or_create(
            slug="caesar-company",
            defaults={"name": "Caesar & Company"},
        )

    def post_prompt(
        self,
        prompt,
        session_id=None,
        language=None,
        restaurant_slug=None,
        table_token=None,
        table_context=None,
        request_id=None,
    ):
        payload = {
            "prompt": prompt,
            "request_id": str(request_id or uuid.uuid4()),
        }

        if session_id:
            payload["session_id"] = str(session_id)

        if language:
            payload["language"] = language

        if restaurant_slug is None:
            restaurant_slug = self.restaurant.slug

        if restaurant_slug:
            payload["restaurant_slug"] = restaurant_slug

        if table_token:
            payload["table_token"] = table_token

        if table_context:
            payload["table_context"] = table_context

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

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(text="Legacy client answer", model_name="gemini-test"),
    )
    def test_missing_request_id_is_generated_for_cached_legacy_client(
        self,
        _generate_ai_answer_mock,
    ):
        response = self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps(
                {
                    "prompt": "Hello from cached JavaScript",
                    "restaurant_slug": self.restaurant.slug,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        generated_request_id = uuid.UUID(response.json()["request_id"])
        self.assertTrue(AIRequestRecord.objects.filter(pk=generated_request_id).exists())

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

    @patch("ai_assistant.views.generate_ai_answer")
    def test_ai_uses_qr_restaurant_context_for_session_and_cards(self, generate_ai_answer_mock):
        restaurant_b = Restaurant.objects.create(
            name="AI Branch B",
            slug="ai-branch-b",
        )
        category_b = Category.objects.create(
            restaurant=restaurant_b,
            name="AI Menu B",
        )
        dish_b = Dish.objects.create(
            restaurant=restaurant_b,
            category=category_b,
            name="Only Branch B AI Dish",
            price="250.00",
            is_active=True,
            is_available=True,
        )
        generate_ai_answer_mock.return_value = AIResult(
            text="I recommend Only Branch B AI Dish.",
            model_name="gemini-test",
            recommended_dish_ids=(dish_b.id,),
        )
        table_b = Table.objects.create(
            restaurant=restaurant_b,
            number="4",
        )
        table_b_token = table_b.plain_qr_token
        default_category = Category.objects.create(name="Default AI Menu")
        Dish.objects.create(
            category=default_category,
            name="Only Default AI Dish",
            price="100.00",
            is_active=True,
            is_available=True,
        )

        response = self.post_prompt(
            "Recommend something",
            table_token=table_b_token,
        )

        self.assertEqual(response.status_code, 200)
        session = generate_ai_answer_mock.call_args.args[0]
        self.assertEqual(session.restaurant_id, restaurant_b.id)
        self.assertEqual(ChatSession.objects.get().restaurant, restaurant_b)
        dishes = response.json()["recommended_dishes"]
        self.assertEqual(dishes[0]["id"], dish_b.id)
        table_context = session.ordering_context.table_context
        self.assertTrue(table_context)
        self.assertNotIn(table_b_token, dishes[0]["url"])
        self.assertIn(
            reverse("menu:table_context_menu", args=[table_context]),
            dishes[0]["url"],
        )

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
            data=json.dumps({"prompt": "Stream please", "restaurant_slug": self.restaurant.slug, "request_id": str(uuid.uuid4())}),
            content_type="application/json",
            HTTP_ACCEPT="application/x-ndjson",
            HTTP_X_AI_STREAM="1",
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "180")
        acquire_ai_stream_slot_mock.assert_called_once()
        generate_ai_answer_stream_mock.assert_not_called()
        self.assertEqual(ChatSession.objects.count(), 0)
        usage_event = AIUsageEvent.objects.get()
        self.assertEqual(usage_event.status, AIUsageEvent.Status.THROTTLED)
        self.assertEqual(usage_event.limit_reason, "actor_stream_concurrency")
        self.assertTrue(usage_event.is_stream)

    @patch(
        "ai_assistant.views.acquire_ai_session_slot",
        return_value=AIStreamSlot(
            allowed=False,
            reason="session_in_progress",
            message=(
                "Ассистент уже отвечает в этом диалоге. "
                "Дождитесь ответа и попробуйте еще раз."
            ),
            retry_after=30,
        ),
    )
    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Should not be called",
            model_name="gemini-test",
        ),
    )
    def test_busy_session_blocks_before_message(
        self,
        generate_ai_answer_mock,
        acquire_ai_session_slot_mock,
    ):
        response = self.post_prompt("Hello")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response["Retry-After"], "30")
        self.assertEqual(response.json()["code"], "ai_session_busy")
        acquire_ai_session_slot_mock.assert_called_once()
        generate_ai_answer_mock.assert_not_called()

        self.assertEqual(ChatSession.objects.count(), 0)
        usage_event = AIUsageEvent.objects.get()
        self.assertEqual(usage_event.status, AIUsageEvent.Status.THROTTLED)
        self.assertEqual(usage_event.limit_reason, "session_in_progress")

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
            restaurant=self.restaurant,
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
            restaurant=self.restaurant,
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

        response = self.client.get(
            reverse("ai_assistant:history"),
            {"restaurant_slug": self.restaurant.slug},
        )

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
            restaurant=self.restaurant,
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
            restaurant=self.restaurant,
            user=user,
            session_key="latest-session",
            title="Latest chat",
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("ai_assistant:history"),
            {
                "session_id": str(requested_session.id),
                "restaurant_slug": self.restaurant.slug,
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
            restaurant=self.restaurant,
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
            restaurant=self.restaurant,
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
            restaurant=self.restaurant,
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
            restaurant=self.restaurant,
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

    @patch("ai_assistant.views.generate_ai_answer")
    def test_answer_includes_recommended_dish_cards(self, generate_ai_answer_mock):
        dish = Dish.objects.create(
            name="Caesar Salad",
            description="Салат с курицей, соусом и хрустящими гренками.",
            price="590.00",
            is_active=True,
            is_available=True,
        )

        generate_ai_answer_mock.return_value = AIResult(
            text="Советую Caesar Salad: легкий салат с понятным составом.",
            model_name="gemini-test",
            recommended_dish_ids=(dish.id,),
        )
        response = self.post_prompt("Посоветуй салат")

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["recommended_dishes"][0]["name"], dish.name)
        self.assertEqual(
            payload["recommended_dishes"][0]["url"],
            f"{reverse('menu:dish_list')}?restaurant={dish.restaurant.slug}#dish-{dish.id}",
        )
        generate_ai_answer_mock.assert_called_once()

    @patch("ai_assistant.views.generate_ai_answer")
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

        generate_ai_answer_mock.return_value = AIResult(
            text="Пиццы сейчас нет, но есть похожие варианты.",
            model_name="gemini-test",
            recommended_dish_ids=(dish.id,),
        )
        response = self.post_prompt("Хочу пиццу")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommended_dishes"][0]["name"], dish.name)
        generate_ai_answer_mock.assert_called_once()

    @patch("ai_assistant.views.generate_ai_answer")
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

        generate_ai_answer_mock.return_value = AIResult(
            text="Могу предложить сэндвич Crassus.",
            model_name="gemini-test",
            recommended_dish_ids=(sandwich.id,),
        )
        response = self.post_prompt("Хочу шаурму")

        self.assertEqual(response.status_code, 200)
        names = [dish["name"] for dish in response.json()["recommended_dishes"]]
        self.assertIn(sandwich.name, names)
        self.assertNotIn("Americano", names)
        generate_ai_answer_mock.assert_called_once()

    @patch("ai_assistant.views.generate_ai_answer")
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

        generate_ai_answer_mock.side_effect = [
            AIResult(
                text="Попробуйте Focaccia.",
                model_name="gemini-test",
                recommended_dish_ids=(previous_dish.id,),
            ),
            AIResult(
                text="Можно взять Crassus.",
                model_name="gemini-test",
                recommended_dish_ids=(new_dish.id,),
            ),
        ]
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
        generate_ai_answer_stream_mock.return_value = AIStreamHandle(
            model_name="gemini-test",
            stream=broken_stream(),
            candidate_dish_ids=(),
        )

        response = self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps({"prompt": "Хочу пиццу", "restaurant_slug": self.restaurant.slug, "request_id": str(uuid.uuid4())}),
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
        self.assertEqual(assistant_message.model_name, "local-menu-fallback")

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

    def test_ai_request_requires_explicit_restaurant_context(self):
        response = self.post_prompt(
            "Hello",
            restaurant_slug="",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "restaurant_required")
        self.assertFalse(ChatSession.objects.exists())

    def test_chat_session_requires_restaurant_at_database_level(self):
        with self.assertRaises(IntegrityError):
            ChatSession.objects.create(
                session_key="missing-restaurant",
                title="Invalid session",
            )

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="The answer mentions Caesar Salad but does not recommend it.",
            model_name="gemini-test",
            recommended_dish_ids=(),
        ),
    )
    def test_text_mention_does_not_attach_dish_card(self, generate_ai_answer_mock):
        Dish.objects.create(
            restaurant=self.restaurant,
            name="Caesar Salad",
            price="590.00",
            is_active=True,
            is_available=True,
        )

        response = self.post_prompt("Tell me about the menu")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommended_dishes"], [])
        assistant_message = ChatMessage.objects.get(
            role=ChatMessage.Role.ASSISTANT,
        )
        self.assertEqual(assistant_message.recommended_dish_ids, [])
        generate_ai_answer_mock.assert_called_once()

    def test_history_uses_persisted_recommendation_ids(self):
        dish = Dish.objects.create(
            restaurant=self.restaurant,
            name="Persistent card dish",
            price="320.00",
            is_active=True,
            is_available=True,
        )
        session = ChatSession.objects.create(
            restaurant=self.restaurant,
            session_key="persistent-card-session",
            title="Persistent cards",
        )
        ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.ASSISTANT,
            content="This text does not contain the dish name.",
            model_name="gemini-test",
            recommended_dish_ids=[dish.id],
        )
        self.client.cookies.clear()
        session.session_key = self.client.session.session_key or ""
        if not session.session_key:
            browser_session = self.client.session
            browser_session.save()
            session.session_key = browser_session.session_key
        session.save(update_fields=["session_key", "updated_at"])

        response = self.client.get(
            reverse("ai_assistant:history"),
            {
                "restaurant_slug": self.restaurant.slug,
                "session_id": str(session.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        cards = response.json()["messages"][0]["dishes"]
        self.assertEqual([card["id"] for card in cards], [dish.id])



    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Idempotent answer",
            model_name="gemini-test",
        ),
    )
    def test_completed_request_is_replayed_without_second_provider_call(
        self,
        generate_ai_answer_mock,
    ):
        request_id = uuid.uuid4()

        first = self.post_prompt("Hello", request_id=request_id)
        second = self.post_prompt("Hello", request_id=request_id)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()["replayed"])
        self.assertTrue(second.json()["replayed"])
        self.assertEqual(first.json()["message_id"], second.json()["message_id"])
        self.assertEqual(generate_ai_answer_mock.call_count, 1)
        self.assertEqual(ChatMessage.objects.count(), 2)
        request_record = AIRequestRecord.objects.get(pk=request_id)
        self.assertEqual(request_record.status, AIRequestRecord.Status.COMPLETED)

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="First answer",
            model_name="gemini-test",
        ),
    )
    def test_request_id_cannot_be_reused_for_different_payload(
        self,
        generate_ai_answer_mock,
    ):
        request_id = uuid.uuid4()
        first = self.post_prompt("Hello", request_id=request_id)
        second = self.post_prompt("Different", request_id=request_id)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["code"], "ai_request_payload_conflict")
        self.assertEqual(generate_ai_answer_mock.call_count, 1)

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
        return_value=AIResult(text="Valid answer", model_name="gemini-test"),
    )
    def test_invalid_session_is_rejected_before_quota_reservation(
        self,
        generate_ai_answer_mock,
    ):
        invalid = self.post_prompt("Invalid", session_id=uuid.uuid4())
        valid = self.post_prompt("Valid")

        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(generate_ai_answer_mock.call_count, 1)
        self.assertEqual(AIUsageEvent.objects.count(), 1)

    @override_settings(
        AI_DAILY_TOKEN_BUDGET_GUEST=1,
        AI_DAILY_TOKEN_BUDGET_IP=999999,
        AI_DAILY_QUOTA_GUEST=100,
        AI_DAILY_QUOTA_IP=100,
        AI_RATE_LIMIT_GUEST_PER_MINUTE=1,
        AI_RATE_LIMIT_IP_PER_MINUTE=100,
    )
    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(text="Allowed", model_name="gemini-test"),
    )
    def test_failed_budget_check_does_not_partially_consume_minute_limit(
        self,
        generate_ai_answer_mock,
    ):
        denied = self.post_prompt("Hello")
        self.assertEqual(denied.status_code, 429)

        with self.settings(AI_DAILY_TOKEN_BUDGET_GUEST=999999):
            allowed = self.post_prompt("Hello again")

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(generate_ai_answer_mock.call_count, 1)

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(
            text="Measured answer",
            model_name="gemini-test",
            provider_usage=AIProviderUsage(
                prompt_tokens=12,
                response_tokens=7,
                total_tokens=19,
                response_id="provider-response-1",
            ),
        ),
    )
    def test_provider_usage_is_saved_separately_from_estimate(
        self,
        generate_ai_answer_mock,
    ):
        response = self.post_prompt("Measure this")

        self.assertEqual(response.status_code, 200)
        event = AIUsageEvent.objects.get()
        self.assertEqual(event.actual_prompt_tokens, 12)
        self.assertEqual(event.actual_response_tokens, 7)
        self.assertEqual(event.actual_total_tokens, 19)
        self.assertEqual(event.provider_response_id, "provider-response-1")
        self.assertGreater(event.estimated_total_tokens, 0)

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(text="Initial answer", model_name="gemini-test"),
    )
    def test_processing_duplicate_returns_conflict_without_provider_call(
        self,
        generate_ai_answer_mock,
    ):
        request_id = uuid.uuid4()
        first = self.post_prompt("Hello", request_id=request_id)
        self.assertEqual(first.status_code, 200)
        AIRequestRecord.objects.filter(pk=request_id).update(
            status=AIRequestRecord.Status.PROCESSING,
            assistant_message=None,
            completed_at=None,
        )

        duplicate = self.post_prompt("Hello", request_id=request_id)

        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["code"], "ai_request_in_progress")
        self.assertEqual(generate_ai_answer_mock.call_count, 1)

    def test_missing_provider_usage_keeps_conservative_token_reservation(self):
        key = "ai-test-token-reservation"
        cache.set(key, 25, timeout=60)
        reservation = AIQuotaReservation(
            allowed=True,
            counters=[
                ReservedCounter(
                    key=key,
                    amount=25,
                    timeout=60,
                    kind="tokens",
                )
            ],
        )

        reconcile_ai_quota_reservation(reservation, None)

        self.assertEqual(cache.get(key), 25)
        self.assertTrue(reservation.reconciled)

    def test_old_lease_cannot_release_new_owner(self):
        key = "ai-test-owned-lease"
        old_lease = _acquire_lease(key, 60)
        self.assertIsNotNone(old_lease)
        cache.delete(key)
        new_lease = _acquire_lease(key, 60)
        self.assertIsNotNone(new_lease)

        _release_lease(old_lease)

        self.assertEqual(cache.get(key), new_lease.token)
        _release_lease(new_lease)


    def test_request_lease_is_held_until_non_stream_provider_finishes(self):
        request_id = uuid.uuid4()

        def generate_answer(_session):
            competing_slot = acquire_ai_request_slot(request_id)
            self.assertFalse(competing_slot.allowed)
            release_ai_request_slot(competing_slot)
            return AIResult(text="Lease-protected answer", model_name="gemini-test")

        with patch(
            "ai_assistant.views.generate_ai_answer",
            side_effect=generate_answer,
        ):
            response = self.post_prompt("Hello", request_id=request_id)

        self.assertEqual(response.status_code, 200)
        available_after_completion = acquire_ai_request_slot(request_id)
        self.assertTrue(available_after_completion.allowed)
        release_ai_request_slot(available_after_completion)

    @patch(
        "ai_assistant.views.generate_ai_answer",
        return_value=AIResult(text="Constraint answer", model_name="gemini-test"),
    )
    def test_database_rejects_terminal_request_without_completion_time(
        self,
        _generate_ai_answer_mock,
    ):
        request_id = uuid.uuid4()
        response = self.post_prompt("Hello", request_id=request_id)
        self.assertEqual(response.status_code, 200)

        with self.assertRaises(IntegrityError), transaction.atomic():
            AIRequestRecord.objects.filter(pk=request_id).update(
                status=AIRequestRecord.Status.FAILED,
                assistant_message=None,
                completed_at=None,
            )

    @patch("ai_assistant.views.generate_ai_answer_stream")
    def test_closing_stream_marks_request_as_canceled(
        self,
        generate_ai_answer_stream_mock,
    ):
        generate_ai_answer_stream_mock.return_value = AIStreamHandle(
            model_name="gemini-test",
            stream=iter(()),
            candidate_dish_ids=(),
        )
        request_id = uuid.uuid4()
        response = self.client.post(
            reverse("ai_assistant:ask"),
            data=json.dumps(
                {
                    "prompt": "Stream please",
                    "restaurant_slug": self.restaurant.slug,
                    "request_id": str(request_id),
                }
            ),
            content_type="application/json",
            HTTP_ACCEPT="application/x-ndjson",
            HTTP_X_AI_STREAM="1",
        )
        iterator = iter(response.streaming_content)
        next(iterator)
        response.close()

        request_record = AIRequestRecord.objects.get(pk=request_id)
        usage_event = AIUsageEvent.objects.get(request_record=request_record)
        self.assertEqual(request_record.status, AIRequestRecord.Status.CANCELED)
        self.assertEqual(request_record.error_code, "client_disconnected")
        self.assertEqual(usage_event.status, AIUsageEvent.Status.CANCELED)



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

    def test_non_menu_page_without_restaurant_context_hides_ai_widget(self):
        response = self.client.get(reverse("account_login"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-ai-assistant")

    def test_standalone_ai_page_is_removed(self):
        response = self.client.get("/ai/")

        self.assertEqual(response.status_code, 404)
