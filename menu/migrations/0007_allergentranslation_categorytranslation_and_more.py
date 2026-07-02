import django.db.models.deletion
import hashlib
from django.db import migrations, models
from django.utils.text import slugify


def build_stable_code(value, prefix="item"):
    base = slugify(str(value or "").strip(), allow_unicode=False)

    if base:
        return base[:180]

    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def unique_code(model, base_code, restaurant_id, max_length):
    code = base_code[:max_length]
    suffix = 2

    while model.objects.filter(restaurant_id=restaurant_id, code=code).exists():
        suffix_text = f"-{suffix}"
        code = f"{base_code[: max_length - len(suffix_text)]}{suffix_text}"
        suffix += 1

    return code


def fill_stable_codes(apps, _schema_editor):
    category_model = apps.get_model("menu", "Category")
    dish_model = apps.get_model("menu", "Dish")

    for category in category_model.objects.order_by("restaurant_id", "id"):
        if category.code:
            continue

        base_code = build_stable_code(category.name, prefix="category")
        category.code = unique_code(
            category_model,
            base_code,
            category.restaurant_id,
            200,
        )
        category.save(update_fields=["code"])

    for dish in dish_model.objects.order_by("restaurant_id", "id"):
        if dish.code:
            continue

        base_code = build_stable_code(dish.name, prefix="dish")
        dish.code = unique_code(
            dish_model,
            base_code,
            dish.restaurant_id,
            220,
        )
        dish.save(update_fields=["code"])


def seed_existing_translations(apps, _schema_editor):
    from menu.translation_seed import (
        ALLERGEN_TRANSLATIONS,
        CATEGORY_TRANSLATIONS,
        DISH_TRANSLATIONS,
    )

    allergen_model = apps.get_model("menu", "Allergen")
    allergen_translation_model = apps.get_model("menu", "AllergenTranslation")
    category_model = apps.get_model("menu", "Category")
    category_translation_model = apps.get_model("menu", "CategoryTranslation")
    dish_model = apps.get_model("menu", "Dish")
    dish_translation_model = apps.get_model("menu", "DishTranslation")

    for source_name, translations in CATEGORY_TRANSLATIONS.items():
        code = build_stable_code(source_name, prefix="category")

        for category in category_model.objects.filter(code=code):
            for language, name in translations.items():
                category_translation_model.objects.update_or_create(
                    category=category,
                    language=language,
                    defaults={"name": name},
                )

    for source_name, translations in DISH_TRANSLATIONS.items():
        code = build_stable_code(source_name, prefix="dish")
        names = translations.get("name", {})
        descriptions = translations.get("description", {})

        for dish in dish_model.objects.filter(code=code):
            for language in set(names) | set(descriptions):
                dish_translation_model.objects.update_or_create(
                    dish=dish,
                    language=language,
                    defaults={
                        "name": names.get(language) or dish.name,
                        "description": descriptions.get(language) or dish.description,
                    },
                )

    for code, translations in ALLERGEN_TRANSLATIONS.items():
        for allergen in allergen_model.objects.filter(code=code):
            for language, name in translations.items():
                allergen_translation_model.objects.update_or_create(
                    allergen=allergen,
                    language=language,
                    defaults={"name": name},
                )


class Migration(migrations.Migration):

    dependencies = [
        ('menu', '0006_alter_category_options_and_more'),
        ('orders', '0004_table_qr_token'),
    ]

    operations = [
        migrations.CreateModel(
            name='AllergenTranslation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('language', models.CharField(choices=[('ru', 'Russian'), ('en', 'English'), ('tr', 'Turkish')], max_length=8, verbose_name='Language')),
                ('name', models.CharField(max_length=100, verbose_name='Name')),
            ],
            options={
                'verbose_name': 'Allergen translation',
                'verbose_name_plural': 'Allergen translations',
                'ordering': ['allergen__name', 'language'],
            },
        ),
        migrations.CreateModel(
            name='CategoryTranslation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('language', models.CharField(choices=[('ru', 'Russian'), ('en', 'English'), ('tr', 'Turkish')], max_length=8, verbose_name='Language')),
                ('name', models.CharField(max_length=100, verbose_name='Name')),
            ],
            options={
                'verbose_name': 'Category translation',
                'verbose_name_plural': 'Category translations',
                'ordering': ['category__name', 'language'],
            },
        ),
        migrations.CreateModel(
            name='DishTranslation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('language', models.CharField(choices=[('ru', 'Russian'), ('en', 'English'), ('tr', 'Turkish')], max_length=8, verbose_name='Language')),
                ('name', models.CharField(max_length=200, verbose_name='Name')),
                ('description', models.TextField(blank=True, verbose_name='Description')),
            ],
            options={
                'verbose_name': 'Dish translation',
                'verbose_name_plural': 'Dish translations',
                'ordering': ['dish__name', 'language'],
            },
        ),
        migrations.AddField(
            model_name='category',
            name='code',
            field=models.SlugField(blank=True, help_text='Stable translation key. It is not changed when the name is renamed.', max_length=200, verbose_name='Code'),
        ),
        migrations.AddField(
            model_name='dish',
            name='code',
            field=models.SlugField(blank=True, help_text='Stable translation key. It is not changed when the name is renamed.', max_length=220, verbose_name='Code'),
        ),
        migrations.RunPython(fill_stable_codes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='category',
            constraint=models.UniqueConstraint(fields=('restaurant', 'code'), name='unique_category_code_per_restaurant'),
        ),
        migrations.AddConstraint(
            model_name='dish',
            constraint=models.UniqueConstraint(fields=('restaurant', 'code'), name='unique_dish_code_per_restaurant'),
        ),
        migrations.AddField(
            model_name='allergentranslation',
            name='allergen',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='translations', to='menu.allergen', verbose_name='Allergen'),
        ),
        migrations.AddField(
            model_name='categorytranslation',
            name='category',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='translations', to='menu.category', verbose_name='Category'),
        ),
        migrations.AddField(
            model_name='dishtranslation',
            name='dish',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='translations', to='menu.dish', verbose_name='Dish'),
        ),
        migrations.RunPython(seed_existing_translations, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='allergentranslation',
            constraint=models.UniqueConstraint(fields=('allergen', 'language'), name='unique_allergen_translation_language'),
        ),
        migrations.AddConstraint(
            model_name='categorytranslation',
            constraint=models.UniqueConstraint(fields=('category', 'language'), name='unique_category_translation_language'),
        ),
        migrations.AddConstraint(
            model_name='dishtranslation',
            constraint=models.UniqueConstraint(fields=('dish', 'language'), name='unique_dish_translation_language'),
        ),
    ]
