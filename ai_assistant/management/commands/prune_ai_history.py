from django.core.management.base import BaseCommand

from ai_assistant.privacy import (
    get_ai_history_retention_days,
    prune_expired_ai_history,
)


class Command(BaseCommand):
    help = "Delete AI chat sessions older than AI_HISTORY_RETENTION_DAYS."

    def handle(self, *args, **options):
        deleted_count = prune_expired_ai_history()
        retention_days = get_ai_history_retention_days()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_count} AI chat sessions older than "
                f"{retention_days} days."
            )
        )
