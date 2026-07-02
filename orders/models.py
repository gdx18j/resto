import hashlib
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxLengthValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


QR_TOKEN_BYTES = 32
QR_TOKEN_HASH_LENGTH = 64
ORDER_COMMENT_MAX_LENGTH = 2000
ORDER_ITEM_NOTE_MAX_LENGTH = 255


def generate_table_qr_token():
    return secrets.token_urlsafe(QR_TOKEN_BYTES)


def hash_table_qr_token(token):
    token = str(token or "").strip()
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class OrderQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if "status" in kwargs:
            raise ValueError("Use orders.statuses.transition_order() to change order status.")

        return super().update(**kwargs)

    def transition_update(self, **kwargs):
        return super().update(**kwargs)


class OrderManager(models.Manager.from_queryset(OrderQuerySet)):
    pass


class Restaurant(models.Model):
    name = models.CharField(max_length=160, verbose_name="Название")
    slug = models.SlugField(max_length=180, unique=True, verbose_name="Код")
    address = models.CharField(max_length=255, blank=True, verbose_name="Адрес")
    phone = models.CharField(max_length=40, blank=True, verbose_name="Телефон")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлен")

    class Meta:
        verbose_name = "Ресторан"
        verbose_name_plural = "Рестораны"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Table(models.Model):
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="tables",
        verbose_name="Ресторан",
    )
    number = models.CharField(max_length=24, verbose_name="Номер")
    title = models.CharField(max_length=80, blank=True, verbose_name="Название")
    qr_token_hash = models.CharField(
        max_length=QR_TOKEN_HASH_LENGTH,
        unique=True,
        blank=True,
        verbose_name="Hash токена QR",
    )
    qr_token_version = models.PositiveIntegerField(default=0, verbose_name="Версия QR")
    qr_token_kind = models.CharField(
        max_length=20,
        choices=(
            ("current", "Новый"),
            ("legacy", "Старый"),
        ),
        default="current",
        verbose_name="Тип QR",
    )
    qr_token_created_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="QR создан",
    )
    qr_token_rotated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="QR перевыпущен",
    )
    qr_token_revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="QR отозван",
    )
    qr_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="QR истекает",
    )
    seats = models.PositiveSmallIntegerField(default=2, verbose_name="Мест")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")

    class Meta:
        verbose_name = "Стол"
        verbose_name_plural = "Столы"
        ordering = ["restaurant__name", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "number"],
                name="unique_table_number_per_restaurant",
            ),
        ]

    def __str__(self):
        label = self.title or self.number
        return f"{self.restaurant}: {label}"

    @property
    def plain_qr_token(self):
        return getattr(self, "_plain_qr_token", "")

    @property
    def is_qr_token_usable(self):
        if not self.qr_token_hash or self.qr_token_revoked_at:
            return False

        return not (
            self.qr_token_expires_at
            and self.qr_token_expires_at <= timezone.now()
        )

    def _assign_qr_token(
        self,
        token,
        *,
        kind="current",
        expires_at=None,
        rotated=False,
    ):
        now = timezone.now()
        self.qr_token_hash = hash_table_qr_token(token)
        self.qr_token_version = (self.qr_token_version or 0) + 1
        self.qr_token_kind = kind
        self.qr_token_created_at = now
        self.qr_token_rotated_at = now if rotated else None
        self.qr_token_revoked_at = None
        self.qr_token_expires_at = expires_at
        self._plain_qr_token = token

    def _new_unique_qr_token(self):
        token = generate_table_qr_token()
        token_hash = hash_table_qr_token(token)

        while type(self).objects.filter(qr_token_hash=token_hash).exclude(pk=self.pk).exists():
            token = generate_table_qr_token()
            token_hash = hash_table_qr_token(token)

        return token

    def save(self, *args, **kwargs):
        issued_token = False

        if not self.qr_token_hash:
            self._assign_qr_token(self._new_unique_qr_token())
            issued_token = True
            update_fields = kwargs.get("update_fields")

            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {
                    "qr_token_hash",
                    "qr_token_version",
                    "qr_token_kind",
                    "qr_token_created_at",
                    "qr_token_rotated_at",
                    "qr_token_revoked_at",
                    "qr_token_expires_at",
                }

        super().save(*args, **kwargs)

        if issued_token:
            TableQrTokenAudit.objects.create(
                table=self,
                action=TableQrTokenAudit.Action.ISSUED,
                token_version=self.qr_token_version,
                token_kind=self.qr_token_kind,
                token_hash=self.qr_token_hash,
                reason="Table created",
            )

    def menu_url_path(self, token=None):
        token = token or self.plain_qr_token

        if not token:
            raise ValueError("Plain QR token is not stored. Rotate the QR token to get a printable URL.")

        return f"/t/{token}/"

    def rotate_qr_token(self, *, actor=None, reason="", expires_at=None):
        old_version = self.qr_token_version
        old_kind = self.qr_token_kind
        old_hash_prefix = self.qr_token_hash[:16] if self.qr_token_hash else ""

        if old_hash_prefix and not self.qr_token_revoked_at:
            self.qr_token_revoked_at = timezone.now()
            TableQrTokenAudit.objects.create(
                table=self,
                actor=actor,
                action=TableQrTokenAudit.Action.REVOKED,
                token_version=old_version,
                token_kind=old_kind,
                token_hash=self.qr_token_hash,
                reason=reason or "QR token rotated",
            )

        token = self._new_unique_qr_token()
        self._assign_qr_token(
            token,
            kind="current",
            expires_at=expires_at,
            rotated=True,
        )
        self.save(
            update_fields=[
                "qr_token_hash",
                "qr_token_version",
                "qr_token_kind",
                "qr_token_created_at",
                "qr_token_rotated_at",
                "qr_token_revoked_at",
                "qr_token_expires_at",
            ]
        )
        TableQrTokenAudit.objects.create(
            table=self,
            actor=actor,
            action=TableQrTokenAudit.Action.ROTATED,
            token_version=self.qr_token_version,
            token_kind=self.qr_token_kind,
            token_hash=self.qr_token_hash,
            reason=reason or "QR token rotated",
        )

        return token

    def revoke_qr_token(self, *, actor=None, reason=""):
        if self.qr_token_revoked_at:
            return

        self.qr_token_revoked_at = timezone.now()
        self.save(update_fields=["qr_token_revoked_at"])
        TableQrTokenAudit.objects.create(
            table=self,
            actor=actor,
            action=TableQrTokenAudit.Action.REVOKED,
            token_version=self.qr_token_version,
            token_kind=self.qr_token_kind,
            token_hash=self.qr_token_hash,
            reason=reason or "QR token revoked",
        )


class TableQrTokenAudit(models.Model):
    class Action(models.TextChoices):
        ISSUED = "issued", "Выпущен"
        MIGRATED = "migrated", "Мигрирован"
        ROTATED = "rotated", "Перевыпущен"
        REVOKED = "revoked", "Отозван"

    table = models.ForeignKey(
        Table,
        on_delete=models.CASCADE,
        related_name="qr_token_audit_events",
        verbose_name="Стол",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qr_token_audit_events",
        verbose_name="Кто изменил",
    )
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        verbose_name="Действие",
    )
    token_version = models.PositiveIntegerField(verbose_name="Версия QR")
    token_kind = models.CharField(max_length=20, blank=True, verbose_name="Тип QR")
    token_hash = models.CharField(max_length=QR_TOKEN_HASH_LENGTH, blank=True, verbose_name="Hash QR")
    reason = models.CharField(max_length=255, blank=True, verbose_name="Причина")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "Аудит QR-токена"
        verbose_name_plural = "Аудит QR-токенов"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["table", "-created_at"], name="table_qr_audit_created_idx"),
            models.Index(fields=["action", "-created_at"], name="table_qr_audit_action_idx"),
            models.Index(fields=["token_hash"], name="table_qr_audit_hash_idx"),
        ]

    def __str__(self):
        return f"{self.table_id}: {self.action} v{self.token_version}"


class Order(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Создан"
        CONFIRMED = "confirmed", "Подтвержден"
        COOKING = "cooking", "Готовится"
        READY = "ready", "Готов"
        SERVED = "served", "Подан"
        COMPLETED = "completed", "Завершен"
        CANCELED = "canceled", "Отменен"

    FLOW = (
        Status.CREATED,
        Status.CONFIRMED,
        Status.COOKING,
        Status.READY,
        Status.SERVED,
        Status.COMPLETED,
    )

    objects = OrderManager()

    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Ресторан",
    )
    table = models.ForeignKey(
        Table,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="Стол",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="Аккаунт",
    )
    session_key = models.CharField(
        max_length=40,
        blank=True,
        verbose_name="Сессия",
    )
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Idempotency key",
    )
    idempotency_actor_scope = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        verbose_name="Idempotency actor scope",
    )
    idempotency_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="Idempotency fingerprint",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
        db_index=True,
        verbose_name="Статус",
    )
    version = models.PositiveIntegerField(default=0, verbose_name="Версия")
    guests_count = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name="Гостей",
    )
    comment = models.TextField(
        blank=True,
        validators=[MaxLengthValidator(ORDER_COMMENT_MAX_LENGTH)],
        verbose_name="Комментарий",
    )
    currency = models.CharField(max_length=3, default="RUB", verbose_name="Валюта")
    subtotal_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Сумма блюд",
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Итого",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлен")
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name="Подтвержден")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Завершен")

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="order_status_created_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_actor_scope", "restaurant", "idempotency_key"],
                condition=Q(idempotency_key__isnull=False),
                name="unique_order_idempotency_per_actor_restaurant",
            ),
            models.CheckConstraint(
                condition=Q(subtotal_amount__gte=0),
                name="order_subtotal_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=0),
                name="order_total_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(total_amount=models.F("subtotal_amount")),
                name="order_total_matches_subtotal",
            ),
        ]

    def __str__(self):
        return f"Заказ #{self.pk or 'новый'}"

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")

        if self.pk and not getattr(self, "_allow_status_save", False):
            should_check_status = update_fields is None or "status" in update_fields

            if should_check_status:
                current_status = (
                    type(self).objects.filter(pk=self.pk)
                    .values_list("status", flat=True)
                    .first()
                )

                if current_status is not None and current_status != self.status:
                    raise ValueError("Use orders.statuses.transition_order() to change order status.")

        super().save(*args, **kwargs)

    def can_transition_to(self, next_status):
        if next_status == self.Status.CANCELED:
            return self.status not in {self.Status.COMPLETED, self.Status.CANCELED}

        if self.status not in self.FLOW or next_status not in self.FLOW:
            return False

        current_index = self.FLOW.index(self.status)
        return current_index + 1 == self.FLOW.index(next_status)

    def transition_to(self, next_status, save=True):
        if not self.can_transition_to(next_status):
            raise ValueError(f"Нельзя перевести заказ из {self.status} в {next_status}")

        if save:
            from .statuses import transition_order

            updated_order = transition_order(self, next_status, expected_version=self.version)
            self.status = updated_order.status
            self.version = updated_order.version
            self.confirmed_at = updated_order.confirmed_at
            self.completed_at = updated_order.completed_at
            self.updated_at = updated_order.updated_at
            return self

        self.status = next_status

        if next_status == self.Status.CONFIRMED and not self.confirmed_at:
            self.confirmed_at = timezone.now()
        if next_status == self.Status.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()

        return self


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="Заказ",
    )
    from_status = models.CharField(
        max_length=20,
        choices=Order.Status.choices,
        blank=True,
        verbose_name="Из статуса",
    )
    to_status = models.CharField(
        max_length=20,
        choices=Order.Status.choices,
        verbose_name="В статус",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_status_changes",
        verbose_name="Кто изменил",
    )
    reason = models.CharField(max_length=255, blank=True, verbose_name="Причина")
    order_version = models.PositiveIntegerField(verbose_name="Версия заказа")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "История статуса заказа"
        verbose_name_plural = "История статусов заказов"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["order", "created_at"], name="order_status_history_idx"),
        ]

    def __str__(self):
        return f"Заказ #{self.order_id}: {self.from_status} -> {self.to_status}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Order status history is append-only.")

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Order status history is append-only.")


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Заказ",
    )
    dish = models.ForeignKey(
        "menu.Dish",
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="Блюдо",
    )
    dish_name = models.CharField(max_length=200, verbose_name="Название блюда")
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Количество",
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Цена за единицу",
    )
    line_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Сумма строки",
    )
    note = models.CharField(
        max_length=ORDER_ITEM_NOTE_MAX_LENGTH,
        blank=True,
        verbose_name="Комментарий",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="order_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="order_item_unit_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(line_total=models.F("unit_price") * models.F("quantity")),
                name="order_item_line_total_matches",
            ),
        ]

    def __str__(self):
        return f"{self.dish_name} x {self.quantity}"

    def recalculate(self):
        self.line_total = self.unit_price * self.quantity


class OrderItemModifier(models.Model):
    class Type(models.TextChoices):
        REMOVE = "remove", "Убрать"
        ADD = "add", "Добавить"
        NOTE = "note", "Пожелание"

    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        related_name="modifiers",
        verbose_name="Позиция",
    )
    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.REMOVE,
        verbose_name="Тип",
    )
    dish_ingredient = models.ForeignKey(
        "menu.DishIngredient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_modifiers",
        verbose_name="Ингредиент блюда",
    )
    name = models.CharField(max_length=160, verbose_name="Название")
    price_delta = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Изменение цены",
    )

    class Meta:
        verbose_name = "Модификатор позиции"
        verbose_name_plural = "Модификаторы позиций"
        ordering = ["id"]

    def __str__(self):
        return f"{self.get_type_display()}: {self.name}"


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Наличные"
        CARD = "card", "Карта"
        ONLINE = "online", "Онлайн"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        AUTHORIZED = "authorized", "Авторизован"
        PAID = "paid", "Оплачен"
        FAILED = "failed", "Ошибка"
        REFUNDED = "refunded", "Возврат"
        CANCELED = "canceled", "Отменен"

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="payments",
        verbose_name="Заказ",
    )
    method = models.CharField(
        max_length=20,
        choices=Method.choices,
        verbose_name="Способ",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Статус",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Сумма",
    )
    currency = models.CharField(max_length=3, default="RUB", verbose_name="Валюта")
    provider = models.CharField(max_length=80, blank=True, verbose_name="Провайдер")
    external_id = models.CharField(max_length=160, blank=True, verbose_name="Внешний ID")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Оплачен")

    class Meta:
        verbose_name = "Платеж"
        verbose_name_plural = "Платежи"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="payment_amount_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.get_method_display()} {self.amount} {self.currency}"
