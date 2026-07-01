import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_assistant", "0002_chatsession_session_key_alter_chatsession_user_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIUsageEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(blank=True, db_index=True, max_length=64)),
                ("actor_kind", models.CharField(blank=True, max_length=20)),
                ("ip_address_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                ("prompt_chars", models.PositiveIntegerField(default=0)),
                ("response_chars", models.PositiveIntegerField(default=0)),
                ("estimated_prompt_tokens", models.PositiveIntegerField(default=0)),
                ("estimated_response_tokens", models.PositiveIntegerField(default=0)),
                ("estimated_total_tokens", models.PositiveIntegerField(default=0)),
                ("estimated_cost_micros", models.PositiveBigIntegerField(default=0)),
                ("model_name", models.CharField(blank=True, max_length=100)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("started", "Начат"),
                            ("completed", "Завершен"),
                            ("failed", "Ошибка"),
                            ("throttled", "Ограничен"),
                            ("fallback", "Локальный fallback"),
                        ],
                        db_index=True,
                        default="started",
                        max_length=20,
                    ),
                ),
                ("limit_reason", models.CharField(blank=True, max_length=120)),
                ("is_stream", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "chat_session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="usage_events",
                        to="ai_assistant.chatsession",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_usage_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="aiusageevent",
            index=models.Index(fields=["status", "created_at"], name="ai_usage_status_created_idx"),
        ),
        migrations.AddIndex(
            model_name="aiusageevent",
            index=models.Index(fields=["user", "created_at"], name="ai_usage_user_created_idx"),
        ),
        migrations.AddIndex(
            model_name="aiusageevent",
            index=models.Index(fields=["ip_address_hash", "created_at"], name="ai_usage_ip_created_idx"),
        ),
    ]
