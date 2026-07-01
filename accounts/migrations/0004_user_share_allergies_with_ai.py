from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_alter_userallergy_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="share_allergies_with_ai",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Разрешает добавлять только названия подтвержденных аллергенов "
                    "в запрос к внешнему AI-провайдеру."
                ),
                verbose_name="Передавать аллергии ИИ",
            ),
        ),
    ]
