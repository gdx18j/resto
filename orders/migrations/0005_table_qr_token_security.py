import hashlib
import secrets

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def hash_qr_token(token):
    return hashlib.sha256(str(token or "").strip().encode("utf-8")).hexdigest()


def migrate_qr_tokens(apps, schema_editor):
    table_model = apps.get_model("orders", "Table")
    audit_model = apps.get_model("orders", "TableQrTokenAudit")

    seen_hashes = set()
    now = timezone.now()

    for table in table_model.objects.all().order_by("id"):
        raw_token = str(getattr(table, "qr_token", "") or "").strip()
        token_kind = "legacy" if raw_token else "current"

        if not raw_token:
            raw_token = secrets.token_urlsafe(32)

        token_hash = hash_qr_token(raw_token)

        while token_hash in seen_hashes:
            raw_token = secrets.token_urlsafe(32)
            token_hash = hash_qr_token(raw_token)
            token_kind = "current"

        seen_hashes.add(token_hash)
        token_created_at = table.created_at or now
        table.qr_token_hash = token_hash
        table.qr_token_version = 1
        table.qr_token_kind = token_kind
        table.qr_token_created_at = token_created_at
        table.qr_token_rotated_at = None
        table.qr_token_revoked_at = None
        table.qr_token_expires_at = None
        table.save(
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
        audit_model.objects.create(
            table_id=table.id,
            action="migrated" if token_kind == "legacy" else "issued",
            token_version=1,
            token_kind=token_kind,
            token_hash=token_hash,
            reason="Migrated from raw qr_token field.",
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orders", "0004_table_qr_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="table",
            name="qr_token_hash",
            field=models.CharField(
                blank=True,
                max_length=64,
                null=True,
                verbose_name="Hash токена QR",
            ),
        ),
        migrations.AddField(
            model_name="table",
            name="qr_token_version",
            field=models.PositiveIntegerField(default=0, verbose_name="Версия QR"),
        ),
        migrations.AddField(
            model_name="table",
            name="qr_token_kind",
            field=models.CharField(
                choices=[("current", "Новый"), ("legacy", "Старый")],
                default="current",
                max_length=20,
                verbose_name="Тип QR",
            ),
        ),
        migrations.AddField(
            model_name="table",
            name="qr_token_created_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="QR создан"),
        ),
        migrations.AddField(
            model_name="table",
            name="qr_token_rotated_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="QR перевыпущен"),
        ),
        migrations.AddField(
            model_name="table",
            name="qr_token_revoked_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="QR отозван"),
        ),
        migrations.AddField(
            model_name="table",
            name="qr_token_expires_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="QR истекает"),
        ),
        migrations.CreateModel(
            name="TableQrTokenAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("issued", "Выпущен"),
                            ("migrated", "Мигрирован"),
                            ("rotated", "Перевыпущен"),
                            ("revoked", "Отозван"),
                        ],
                        max_length=20,
                        verbose_name="Действие",
                    ),
                ),
                ("token_version", models.PositiveIntegerField(verbose_name="Версия QR")),
                ("token_kind", models.CharField(blank=True, max_length=20, verbose_name="Тип QR")),
                ("token_hash", models.CharField(blank=True, max_length=64, verbose_name="Hash QR")),
                ("reason", models.CharField(blank=True, max_length=255, verbose_name="Причина")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="qr_token_audit_events",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Кто изменил",
                    ),
                ),
                (
                    "table",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="qr_token_audit_events",
                        to="orders.table",
                        verbose_name="Стол",
                    ),
                ),
            ],
            options={
                "verbose_name": "Аудит QR-токена",
                "verbose_name_plural": "Аудит QR-токенов",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.RunPython(migrate_qr_tokens, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="table",
            name="qr_token",
        ),
        migrations.AlterField(
            model_name="table",
            name="qr_token_hash",
            field=models.CharField(
                blank=True,
                max_length=64,
                unique=True,
                verbose_name="Hash токена QR",
            ),
        ),
        migrations.AddIndex(
            model_name="tableqrtokenaudit",
            index=models.Index(fields=["table", "-created_at"], name="table_qr_audit_created_idx"),
        ),
        migrations.AddIndex(
            model_name="tableqrtokenaudit",
            index=models.Index(fields=["action", "-created_at"], name="table_qr_audit_action_idx"),
        ),
        migrations.AddIndex(
            model_name="tableqrtokenaudit",
            index=models.Index(fields=["token_hash"], name="table_qr_audit_hash_idx"),
        ),
    ]
