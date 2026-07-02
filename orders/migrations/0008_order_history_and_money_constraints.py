from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0007_scoped_idempotency"),
    ]

    operations = [
        migrations.AlterField(
            model_name="orderstatushistory",
            name="from_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("created", "Создан"),
                    ("confirmed", "Подтвержден"),
                    ("cooking", "Готовится"),
                    ("ready", "Готов"),
                    ("served", "Подан"),
                    ("completed", "Завершен"),
                    ("canceled", "Отменен"),
                ],
                max_length=20,
                verbose_name="Из статуса",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=Q(subtotal_amount__gte=0),
                name="order_subtotal_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=Q(total_amount__gte=0),
                name="order_total_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=Q(total_amount=F("subtotal_amount")),
                name="order_total_matches_subtotal",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="order_item_quantity_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="order_item_unit_price_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=Q(line_total=F("unit_price") * F("quantity")),
                name="order_item_line_total_matches",
            ),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="payment_amount_nonnegative",
            ),
        ),
    ]
