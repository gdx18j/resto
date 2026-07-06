from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from orders.models import (
    Table,
    TableQrTokenAudit,
    decrypt_table_qr_token,
    encrypt_table_qr_token,
    hash_table_qr_token,
    is_table_qr_token_ciphertext_encrypted_with_primary,
)


class Command(BaseCommand):
    help = "Re-encrypt stored table QR token ciphertext with the primary QR key."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without updating rows.",
        )
        parser.add_argument(
            "--fail-on-unreadable",
            action="store_true",
            help=(
                "Exit with an error if any stored QR token ciphertext cannot be read."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        fail_on_unreadable = options["fail_on_unreadable"]
        stats = {
            "scanned": 0,
            "already_primary": 0,
            "rewritten": 0,
            "would_rewrite": 0,
            "unreadable": 0,
        }

        tables = (
            Table.objects.exclude(qr_token_ciphertext="")
            .select_related("restaurant")
            .order_by("id")
        )

        for table in tables.iterator():
            stats["scanned"] += 1
            token = decrypt_table_qr_token(table.qr_token_ciphertext)
            if not token or hash_table_qr_token(token) != table.qr_token_hash:
                stats["unreadable"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"table={table.pk}: QR ciphertext is unreadable "
                        "or mismatches its hash."
                    )
                )
                continue

            if is_table_qr_token_ciphertext_encrypted_with_primary(
                table.qr_token_ciphertext
            ):
                stats["already_primary"] += 1
                continue

            if dry_run:
                stats["would_rewrite"] += 1
                continue

            with transaction.atomic():
                table.qr_token_ciphertext = encrypt_table_qr_token(token)
                table.save(update_fields=["qr_token_ciphertext"])
                TableQrTokenAudit.objects.create(
                    table=table,
                    action=TableQrTokenAudit.Action.MIGRATED,
                    token_version=table.qr_token_version,
                    token_kind=table.qr_token_kind,
                    token_hash=table.qr_token_hash,
                    reason="Re-encrypted QR token ciphertext with primary encryption key.",
                )

            stats["rewritten"] += 1

        summary = (
            "Scanned {scanned} table QR ciphertext(s): "
            "{already_primary} already used the primary key, "
            "{rewritten} re-encrypted, "
            "{would_rewrite} would be re-encrypted, "
            "{unreadable} unreadable."
        ).format(**stats)

        if stats["unreadable"] and fail_on_unreadable:
            raise CommandError(summary)

        if stats["unreadable"]:
            self.stdout.write(self.style.WARNING(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
