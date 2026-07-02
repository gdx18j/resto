from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_order_comment_max_length"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="idempotency_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=128,
                null=True,
                verbose_name="Idempotency key",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="idempotency_actor_scope",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=255,
                verbose_name="Idempotency actor scope",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(
                fields=("idempotency_actor_scope", "restaurant", "idempotency_key"),
                condition=Q(idempotency_key__isnull=False),
                name="unique_order_idempotency_per_actor_restaurant",
            ),
        ),
    ]
