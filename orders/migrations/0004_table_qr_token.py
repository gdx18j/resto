import secrets

from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def fill_qr_tokens(apps, schema_editor):
    table_model = apps.get_model("orders", "Table")

    for table in table_model.objects.filter(Q(qr_token="") | Q(qr_token__isnull=True)):
        token = secrets.token_urlsafe(8)
        while table_model.objects.filter(qr_token=token).exists():
            token = secrets.token_urlsafe(8)
        table.qr_token = token
        table.save(update_fields=["qr_token"])


def fill_created_at(apps, schema_editor):
    table_model = apps.get_model("orders", "Table")
    table_model.objects.filter(created_at__isnull=True).update(created_at=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0003_order_version_orderstatushistory"),
    ]

    operations = [
        migrations.AddField(
            model_name="table",
            name="created_at",
            field=models.DateTimeField(
                null=True,
                verbose_name="Создан",
            ),
        ),
        migrations.AddField(
            model_name="table",
            name="qr_token",
            field=models.CharField(
                blank=True,
                max_length=32,
                null=True,
                unique=True,
                verbose_name="Токен QR",
            ),
        ),
        migrations.RunPython(fill_qr_tokens, migrations.RunPython.noop),
        migrations.RunPython(fill_created_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="table",
            name="qr_token",
            field=models.CharField(
                blank=True,
                max_length=32,
                unique=True,
                verbose_name="Токен QR",
            ),
        ),
        migrations.AlterField(
            model_name="table",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                verbose_name="Создан",
            ),
        ),
    ]
