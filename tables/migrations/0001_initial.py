from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Table",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.CharField(help_text="Например: 12, VIP-1, Терраса-3", max_length=20, unique=True, verbose_name="Номер / название стола")),
                ("qr_token", models.CharField(blank=True, help_text="Генерируется автоматически, если оставить пустым.", max_length=32, unique=True, verbose_name="Токен в URL")),
                ("seats", models.PositiveSmallIntegerField(default=2, verbose_name="Количество мест")),
                ("is_active", models.BooleanField(default=True, help_text="Если выключить — QR перестанет открывать меню.", verbose_name="Активен")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Стол",
                "verbose_name_plural": "Столы",
                "ordering": ["number"],
            },
        ),
    ]
