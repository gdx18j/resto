import secrets

from django.db import models


class Table(models.Model):
    """Стол в зале ресторана. Каждому столу соответствует свой QR-код,
    который ведёт на URL вида /t/<qr_token>/ — открывая его, гость
    автоматически "садится" за этот стол (id стола кладётся в сессию).
    """

    number = models.CharField(
        "Номер / название стола",
        max_length=20,
        unique=True,
        help_text="Например: 12, VIP-1, Терраса-3",
    )
    qr_token = models.CharField(
        "Токен в URL",
        max_length=32,
        unique=True,
        blank=True,
        help_text="Генерируется автоматически, если оставить пустым.",
    )
    seats = models.PositiveSmallIntegerField(
        "Количество мест",
        default=2,
    )
    is_active = models.BooleanField(
        "Активен",
        default=True,
        help_text="Если выключить — QR перестанет открывать меню.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Стол"
        verbose_name_plural = "Столы"
        ordering = ["number"]

    def __str__(self):
        return f"Стол {self.number}"

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = secrets.token_urlsafe(8)
        super().save(*args, **kwargs)

    def menu_url_path(self):
        """Относительный путь, который кодируется в QR."""
        return f"/t/{self.qr_token}/"
