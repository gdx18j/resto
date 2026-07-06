# Generated manually for a focused seasonal menu feature patch.

import django.db.models.deletion
from django.db import migrations, models

import menu.models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0010_table_qr_token_ciphertext"),
        ("menu", "0010_allergen_review_workflow"),
    ]

    operations = [
        migrations.CreateModel(
            name="SeasonalDishFeature",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "label_ru",
                    models.CharField(
                        blank=True,
                        help_text=(
                            "Например: Сезонная история. Если пусто — "
                            "используется стандартный текст."
                        ),
                        max_length=80,
                        verbose_name="Надпись RU",
                    ),
                ),
                (
                    "label_en",
                    models.CharField(
                        blank=True,
                        max_length=80,
                        verbose_name="Надпись EN",
                    ),
                ),
                (
                    "label_tr",
                    models.CharField(
                        blank=True,
                        max_length=80,
                        verbose_name="Надпись TR",
                    ),
                ),
                (
                    "title_ru",
                    models.CharField(
                        blank=True,
                        help_text="Если пусто — берётся название блюда.",
                        max_length=160,
                        verbose_name="Заголовок RU",
                    ),
                ),
                (
                    "title_en",
                    models.CharField(
                        blank=True,
                        max_length=160,
                        verbose_name="Заголовок EN",
                    ),
                ),
                (
                    "title_tr",
                    models.CharField(
                        blank=True,
                        max_length=160,
                        verbose_name="Заголовок TR",
                    ),
                ),
                (
                    "description_ru",
                    models.TextField(
                        blank=True,
                        help_text="Если пусто — берётся описание блюда.",
                        verbose_name="Описание RU",
                    ),
                ),
                ("description_en", models.TextField(blank=True, verbose_name="Описание EN")),
                ("description_tr", models.TextField(blank=True, verbose_name="Описание TR")),
                (
                    "cta_ru",
                    models.CharField(
                        blank=True,
                        help_text="Если пусто — используется стандартный текст.",
                        max_length=80,
                        verbose_name="Кнопка RU",
                    ),
                ),
                ("cta_en", models.CharField(blank=True, max_length=80, verbose_name="Кнопка EN")),
                ("cta_tr", models.CharField(blank=True, max_length=80, verbose_name="Кнопка TR")),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        help_text="Если пусто — используется фотография выбранного блюда.",
                        upload_to="seasonal/%Y/%m/",
                        verbose_name="Промо-изображение",
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveSmallIntegerField(
                        db_index=True,
                        default=0,
                        verbose_name="Порядок",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                        verbose_name="Показывать",
                    ),
                ),
                (
                    "starts_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="Показывать с",
                    ),
                ),
                (
                    "ends_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="Показывать до",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "dish",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="seasonal_features",
                        to="menu.dish",
                        verbose_name="Блюдо",
                    ),
                ),
                (
                    "restaurant",
                    models.ForeignKey(
                        default=menu.models.get_default_restaurant_id,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="seasonal_dish_features",
                        to="orders.restaurant",
                        verbose_name="Ресторан",
                    ),
                ),
            ],
            options={
                "verbose_name": "Сезонное блюдо",
                "verbose_name_plural": "Сезонные блюда",
                "ordering": ["restaurant__name", "sort_order", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="seasonaldishfeature",
            index=models.Index(
                fields=["restaurant", "is_active", "sort_order"],
                name="seasonal_rest_active_sort_idx",
            ),
        ),
    ]
