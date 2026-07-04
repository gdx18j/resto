from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0009_order_mode_and_snapshots"),
    ]

    operations = [
        migrations.AddField(
            model_name="table",
            name="qr_token_ciphertext",
            field=models.TextField(blank=True, default="", verbose_name="Зашифрованный QR-токен"),
        ),
    ]
