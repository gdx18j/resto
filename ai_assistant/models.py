import uuid

from django.conf import settings
from django.db import models


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

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_role_display()}: {self.content[:50]}"
