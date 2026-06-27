from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings

from .managers import UserManager


class User(AbstractUser):
    username = None

    email = models.EmailField(
        verbose_name="Email",
        unique=True,
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email

class UserAllergy(models.Model):
    """
    Аллерген, указанный пользователем.

    Запись может быть добавлена вручную
    или получена из диалога с гостем.
    """

    class Source(models.TextChoices):
        MANUAL = "manual", "Добавлено пользователем"
        DIALOG = "ai_chat", "Получено из диалога"
        ADMIN = "admin", "Добавлено администратором"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает подтверждения"
        CONFIRMED = "confirmed", "Подтверждено"
        REJECTED = "rejected", "Отклонено"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="allergy_records",
        verbose_name="Пользователь",
    )

    allergen = models.ForeignKey(
        "menu.Allergen",
        on_delete=models.CASCADE,
        related_name="user_allergy_records",
        verbose_name="Аллерген",
    )

    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
        verbose_name="Источник",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
        verbose_name="Статус",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Добавлено",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Аллергия пользователя"
        verbose_name_plural = "Аллергии пользователей"
        ordering = ["user", "allergen__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "allergen"],
                name="unique_allergen_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user} — {self.allergen}"
