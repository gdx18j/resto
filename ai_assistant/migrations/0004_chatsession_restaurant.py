import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_assistant", "0003_aiusageevent"),
        ("orders", "0004_table_qr_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="restaurant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ai_chat_sessions",
                to="orders.restaurant",
            ),
        ),
    ]
