from django.conf import settings
from django.db import models

from tables.models import Table


class Order(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_SENT_TO_KITCHEN = "sent_to_kitchen"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_PENDING, "Ожидает оплаты"),
        (STATUS_PAID, "Оплачен"),
        (STATUS_SENT_TO_KITCHEN, "Передан на кухню"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    PAYMENT_METHOD_CARD = "bank_card"
    PAYMENT_METHOD_SBP = "sbp"
    PAYMENT_METHOD_CASH = "cash"
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_CARD, "Картой"),
        (PAYMENT_METHOD_SBP, "СБП (QR)"),
        (PAYMENT_METHOD_CASH, "Наличными"),
    ]

    table = models.ForeignKey(
        Table,
        verbose_name="Стол",
        on_delete=models.PROTECT,
        related_name="orders",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )

    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    total = models.DecimalField("Сумма", max_digits=10, decimal_places=2, default=0)
    guests_count = models.PositiveSmallIntegerField("Количество персон", default=1)
    comment = models.TextField("Комментарий к заказу", blank=True)

    payment_method = models.CharField(
        "Способ оплаты",
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        blank=True,
    )
    yookassa_payment_id = models.CharField(
        "ID платежа в ЮKassa",
        max_length=64,
        blank=True,
        db_index=True,
    )

    created_at = models.DateTimeField("Создан", auto_now_add=True)
    paid_at = models.DateTimeField("Оплачен", null=True, blank=True)

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["-created_at"]

    def __str__(self):
        table_label = self.table.number if self.table else "—"
        return f"Заказ №{self.pk} (стол {table_label})"

    def recalc_total(self):
        total = sum(item.subtotal() for item in self.items.all())
        self.total = total
        self.save(update_fields=["total"])
        return total


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        verbose_name="Заказ",
        on_delete=models.CASCADE,
        related_name="items",
    )
    dish_name = models.CharField("Название блюда", max_length=200)
    price = models.DecimalField("Цена за штуку", max_digits=10, decimal_places=2)
    qty = models.PositiveIntegerField("Количество", default=1)

    class Meta:
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"

    def __str__(self):
        return f"{self.dish_name} × {self.qty}"

    def subtotal(self):
        return self.price * self.qty
