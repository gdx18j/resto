import uuid

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class StructuredRecommendationsMigrationTests(TransactionTestCase):
    migrate_from = [
        ("ai_assistant", "0004_chatsession_restaurant"),
        ("orders", "0009_order_mode_and_snapshots"),
    ]
    migrate_to = [
        ("ai_assistant", "0005_structured_recommendations"),
        ("orders", "0009_order_mode_and_snapshots"),
    ]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        Restaurant = old_apps.get_model("orders", "Restaurant")
        ChatSession = old_apps.get_model("ai_assistant", "ChatSession")
        ChatMessage = old_apps.get_model("ai_assistant", "ChatMessage")

        Restaurant.objects.update(is_active=False)
        restaurant = Restaurant.objects.create(
            name="Legacy AI restaurant",
            slug="legacy-ai-restaurant",
            is_active=True,
        )
        session = ChatSession.objects.create(
            restaurant=None,
            session_key="legacy-ai-session",
            title="Legacy AI session",
        )
        message = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content="Legacy response",
            model_name="legacy-model",
        )
        self.restaurant_id = restaurant.pk
        self.session_id = session.pk
        self.message_id = message.pk

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_orphan_session_is_scoped_and_messages_get_empty_structured_ids(self):
        ChatSession = self.apps.get_model("ai_assistant", "ChatSession")
        ChatMessage = self.apps.get_model("ai_assistant", "ChatMessage")

        session = ChatSession.objects.get(pk=self.session_id)
        message = ChatMessage.objects.get(pk=self.message_id)

        self.assertEqual(session.restaurant_id, self.restaurant_id)
        self.assertEqual(message.recommended_dish_ids, [])


class RequestReliabilityMigrationTests(TransactionTestCase):
    migrate_from = [
        ("ai_assistant", "0005_structured_recommendations"),
        ("orders", "0009_order_mode_and_snapshots"),
    ]
    migrate_to = [
        ("ai_assistant", "0006_request_reliability"),
        ("orders", "0009_order_mode_and_snapshots"),
    ]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        Restaurant = old_apps.get_model("orders", "Restaurant")
        ChatSession = old_apps.get_model("ai_assistant", "ChatSession")
        ChatMessage = old_apps.get_model("ai_assistant", "ChatMessage")
        AIUsageEvent = old_apps.get_model("ai_assistant", "AIUsageEvent")

        restaurant = Restaurant.objects.create(
            name="Reliability migration restaurant",
            slug="reliability-migration-restaurant",
        )
        session = ChatSession.objects.create(
            restaurant=restaurant,
            session_key="reliability-migration-session",
            title="Existing AI session",
        )
        message = ChatMessage.objects.create(
            session=session,
            role="user",
            content="Existing request",
        )
        usage = AIUsageEvent.objects.create(
            chat_session=session,
            session_key=session.session_key,
            actor_kind="session",
            estimated_total_tokens=42,
        )
        self.restaurant_id = restaurant.pk
        self.session_id = session.pk
        self.message_id = message.pk
        self.usage_id = usage.pk

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_usage_is_preserved_and_request_records_are_available(self):
        AIRequestRecord = self.apps.get_model(
            "ai_assistant",
            "AIRequestRecord",
        )
        AIUsageEvent = self.apps.get_model("ai_assistant", "AIUsageEvent")

        usage = AIUsageEvent.objects.get(pk=self.usage_id)
        self.assertEqual(usage.estimated_total_tokens, 42)
        self.assertEqual(usage.actual_prompt_tokens, 0)
        self.assertEqual(usage.actual_response_tokens, 0)
        self.assertEqual(usage.actual_total_tokens, 0)
        self.assertEqual(usage.actual_cost_micros, 0)
        self.assertIsNone(usage.request_record_id)

        request_record = AIRequestRecord.objects.create(
            id=uuid.uuid4(),
            session_key="reliability-migration-session",
            restaurant_id=self.restaurant_id,
            chat_session_id=self.session_id,
            user_message_id=self.message_id,
            request_fingerprint="f" * 64,
        )
        self.assertEqual(request_record.status, "processing")
