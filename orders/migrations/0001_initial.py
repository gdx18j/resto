from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tables", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("draft","Черновик"),("pending","Ожидает оплаты"),("paid","Оплачен"),("sent_to_kitchen","Передан на кухню"),("cancelled","Отменён")], default="draft", max_length=20, verbose_name="Статус")),
                ("total", models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Сумма")),
                ("guests_count", models.PositiveSmallIntegerField(default=1, verbose_name="Количество персон")),
                ("comment", models.TextField(blank=True, verbose_name="Комментарий к заказу")),
                ("payment_method", models.CharField(blank=True, choices=[("bank_card","Картой"),("sbp","СБП (QR)")], max_length=20, verbose_name="Способ оплаты")),
                ("yookassa_payment_id", models.CharField(blank=True, db_index=True, max_length=64, verbose_name="ID платежа в ЮKassa")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("paid_at", models.DateTimeField(blank=True, null=True, verbose_name="Оплачен")),
                ("table", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="orders", to="tables.table", verbose_name="Стол")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="orders", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={"verbose_name": "Заказ", "verbose_name_plural": "Заказы", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dish_name", models.CharField(max_length=200, verbose_name="Название блюда")),
                ("price", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Цена за штуку")),
                ("qty", models.PositiveIntegerField(default=1, verbose_name="Количество")),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="orders.order", verbose_name="Заказ")),
            ],
            options={"verbose_name": "Позиция заказа", "verbose_name_plural": "Позиции заказа"},
        ),
    ]
