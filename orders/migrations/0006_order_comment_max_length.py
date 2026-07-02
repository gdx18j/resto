from django.core.validators import MaxLengthValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_table_qr_token_security"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="comment",
            field=models.TextField(
                blank=True,
                validators=[MaxLengthValidator(2000)],
                verbose_name="Комментарий",
            ),
        ),
        migrations.AlterField(
            model_name="orderitem",
            name="note",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Комментарий",
            ),
        ),
    ]
