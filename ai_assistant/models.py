import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ChatSession(models.Model):
    """
    Один отдельный диалог пользователя с ИИ-ассистентом.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ai_chat_sessions",
        null=True,
        blank=True,
    )

    restaurant = models.ForeignKey(
        "orders.Restaurant",
        on_delete=models.CASCADE,
        related_name="ai_chat_sessions",
    )

    session_key = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    title = models.CharField(
        max_length=150,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(
                fields=["session_key", "updated_at"],
                name="ai_session_key_updated_idx",
            ),
        ]

    def __str__(self):
        return self.title or f"Диалог {self.id}"


class ChatMessage(models.Model):
    """
    Одно сообщение пользователя или ассистента внутри диалога.
    """

    class Role(models.TextChoices):
        USER = "user", "Пользователь"
        ASSISTANT = "assistant", "Ассистент"

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )

    content = models.TextField()

    model_name = models.CharField(
        max_length=100,
        blank=True,
    )

    recommended_dish_ids = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Структурированные ID рекомендаций",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_role_display()}: {self.content[:50]}"


class AIRequestRecord(models.Model):
    """
    Идемпотентная запись одного клиентского запроса к ресторанному ассистенту.

    Первичный ключ генерируется браузером. Повтор с тем же UUID никогда не
    запускает модель второй раз: завершенный ответ воспроизводится из БД, а
    выполняющийся или завершившийся ошибкой запрос получает явный конфликт.
    """

    class Status(models.TextChoices):
        PROCESSING = "processing", "Выполняется"
        COMPLETED = "completed", "Завершен"
        FALLBACK = "fallback", "Локальный fallback"
        FAILED = "failed", "Ошибка"
        CANCELED = "canceled", "Отменен клиентом"

    id = models.UUIDField(
        primary_key=True,
        editable=False,
        verbose_name="Client request ID",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ai_request_records",
        null=True,
        blank=True,
    )

    session_key = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    restaurant = models.ForeignKey(
        "orders.Restaurant",
        on_delete=models.CASCADE,
        related_name="ai_request_records",
    )

    chat_session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="request_records",
    )

    user_message = models.OneToOneField(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="originating_request",
    )

    assistant_message = models.OneToOneField(
        ChatMessage,
        on_delete=models.SET_NULL,
        related_name="completed_request",
        null=True,
        blank=True,
    )

    request_fingerprint = models.CharField(
        max_length=64,
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
        db_index=True,
    )

    error_code = models.CharField(
        max_length=120,
        blank=True,
    )

    is_stream = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(user__isnull=False) | ~Q(session_key=""),
                name="ai_request_owner_present",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status__in=[
                            "completed",
                            "fallback",
                        ],
                        assistant_message__isnull=False,
                        completed_at__isnull=False,
                    )
                    | Q(
                        status="processing",
                        assistant_message__isnull=True,
                        completed_at__isnull=True,
                    )
                    | Q(
                        status__in=[
                            "failed",
                            "canceled",
                        ],
                        assistant_message__isnull=True,
                        completed_at__isnull=False,
                    )
                ),
                name="ai_request_completion_consistent",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "updated_at"],
                name="ai_req_status_updated_idx",
            ),
            models.Index(
                fields=["user", "created_at"],
                name="ai_req_user_created_idx",
            ),
            models.Index(
                fields=["session_key", "created_at"],
                name="ai_req_session_created_idx",
            ),
        ]

    def __str__(self):
        return f"{self.id}: {self.status}"


class AIUsageEvent(models.Model):
    """
    Audit trail for AI budget, throttling and abuse analysis.
    """

    class Status(models.TextChoices):
        STARTED = "started", "Начат"
        COMPLETED = "completed", "Завершен"
        FAILED = "failed", "Ошибка"
        CANCELED = "canceled", "Отменен клиентом"
        THROTTLED = "throttled", "Ограничен"
        FALLBACK = "fallback", "Локальный fallback"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ai_usage_events",
        null=True,
        blank=True,
    )

    chat_session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        related_name="usage_events",
        null=True,
        blank=True,
    )

    request_record = models.OneToOneField(
        AIRequestRecord,
        on_delete=models.SET_NULL,
        related_name="usage_event",
        null=True,
        blank=True,
    )

    session_key = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    actor_kind = models.CharField(
        max_length=20,
        blank=True,
    )

    ip_address_hash = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    prompt_chars = models.PositiveIntegerField(default=0)
    response_chars = models.PositiveIntegerField(default=0)
    estimated_prompt_tokens = models.PositiveIntegerField(default=0)
    estimated_response_tokens = models.PositiveIntegerField(default=0)
    estimated_total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_micros = models.PositiveBigIntegerField(default=0)

    actual_prompt_tokens = models.PositiveIntegerField(default=0)
    actual_response_tokens = models.PositiveIntegerField(default=0)
    actual_total_tokens = models.PositiveIntegerField(default=0)
    actual_cost_micros = models.PositiveBigIntegerField(default=0)
    provider_response_id = models.CharField(max_length=160, blank=True)

    model_name = models.CharField(
        max_length=100,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.STARTED,
        db_index=True,
    )

    limit_reason = models.CharField(
        max_length=120,
        blank=True,
    )

    is_stream = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="ai_usage_status_created_idx",
            ),
            models.Index(
                fields=["user", "created_at"],
                name="ai_usage_user_created_idx",
            ),
            models.Index(
                fields=["ip_address_hash", "created_at"],
                name="ai_usage_ip_created_idx",
            ),
        ]

    def __str__(self):
        token_count = self.actual_total_tokens or self.estimated_total_tokens
        return f"{self.status}: {token_count} tokens"
