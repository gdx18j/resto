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

    share_allergies_with_ai = models.BooleanField(
        default=False,
        verbose_name="Передавать аллергии ИИ",
        help_text=(
            "Разрешает добавлять только названия подтвержденных аллергенов "
            "в запрос к внешнему AI-провайдеру."
        ),
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


class UserAllergyStatusChange(models.Model):
    allergy = models.ForeignKey(
        UserAllergy,
        on_delete=models.CASCADE,
        related_name="status_changes",
        verbose_name="Allergy record",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="allergy_status_changes",
        verbose_name="Actor",
    )

    old_status = models.CharField(
        max_length=20,
        choices=UserAllergy.Status.choices,
        blank=True,
        verbose_name="Old status",
    )

    new_status = models.CharField(
        max_length=20,
        choices=UserAllergy.Status.choices,
        verbose_name="New status",
    )

    old_source = models.CharField(
        max_length=20,
        choices=UserAllergy.Source.choices,
        blank=True,
        verbose_name="Old source",
    )

    new_source = models.CharField(
        max_length=20,
        choices=UserAllergy.Source.choices,
        verbose_name="New source",
    )

    reason = models.CharField(
        max_length=80,
        verbose_name="Reason",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created at",
    )

    class Meta:
        verbose_name = "User allergy status change"
        verbose_name_plural = "User allergy status changes"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.allergy} {self.old_status or 'new'} -> {self.new_status}"
