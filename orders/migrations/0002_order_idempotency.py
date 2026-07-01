from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="idempotency_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=128,
                null=True,
                unique=True,
                verbose_name="Idempotency key",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="idempotency_fingerprint",
            field=models.CharField(
                blank=True,
                max_length=64,
                verbose_name="Idempotency fingerprint",
            ),
        ),
    ]
