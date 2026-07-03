import django.db.models.deletion
from django.db import migrations, models


def backfill_restaurant(apps, schema_editor):
    ChatSession = apps.get_model("ai_assistant", "ChatSession")
    Restaurant = apps.get_model("orders", "Restaurant")
    orphan_sessions = ChatSession.objects.filter(restaurant__isnull=True)

    if not orphan_sessions.exists():
        return

    restaurant = (
        Restaurant.objects.filter(is_active=True)
        .order_by("id")
        .first()
        or Restaurant.objects.order_by("id").first()
    )

    if restaurant is None:
        orphan_sessions.delete()
        return

    orphan_sessions.update(restaurant_id=restaurant.id)


class Migration(migrations.Migration):

    dependencies = [
        ("ai_assistant", "0004_chatsession_restaurant"),
        ("orders", "0009_order_mode_and_snapshots"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="recommended_dish_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="Структурированные ID рекомендаций",
            ),
        ),
        migrations.RunPython(
            backfill_restaurant,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="chatsession",
            name="restaurant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ai_chat_sessions",
                to="orders.restaurant",
            ),
        ),
    ]
