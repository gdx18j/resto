import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from menu.allergen_rules import (
    ALLERGEN_NAME_TO_CODE,
    get_allergen_codes_for_ingredient,
)
from menu.models import (
    Allergen,
    Category,
    Dish,
    DishIngredient,
    Ingredient,
)
from orders.models import Restaurant


def parse_decimal(value):
    if value in (None, ""):
        return None

    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise CommandError(
            f"Невозможно преобразовать в число: {value}"
        ) from error


def get_or_create_allergen(name):
    """
    Находит аллерген по системному коду или названию.
    Если его нет, создаёт новую запись.
    """

    normalized_name = name.strip().lower()
    code = ALLERGEN_NAME_TO_CODE.get(normalized_name)

    if not code:
        return None

    display_name = normalized_name.capitalize()

    allergen = Allergen.objects.filter(code=code).first()

    if allergen:
        return allergen

    allergen = Allergen.objects.filter(
        name__iexact=display_name,
    ).first()

    if allergen:
        return allergen

    return Allergen.objects.create(
        name=display_name,
        code=code,
    )


def assign_detected_allergens_to_ingredient(ingredient):
    allergen_codes = get_allergen_codes_for_ingredient(
        ingredient.name,
    )

    if not allergen_codes:
        return

    allergens = Allergen.objects.filter(
        code__in=allergen_codes,
    )

    if allergens:
        ingredient.allergens.add(*allergens)


class Command(BaseCommand):
    help = "Импортирует меню Caesar And Company из JSON"

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            type=str,
            help="Путь к JSON-файлу внутри контейнера",
        )

        parser.add_argument(
            "--clear",
            action="store_true",
            help=(
                "Удалить старые блюда, категории и ингредиенты "
                "перед импортом"
            ),
        )

        parser.add_argument(
            "--with-allergens",
            action="store_true",
            help=(
                "Импортировать предварительные аллергены "
                "в may_contain_allergens"
            ),
        )
        parser.add_argument(
            "--restaurant-slug",
            default="caesar-company",
            help="Slug ресторана, в меню которого импортируются блюда.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        json_path = Path(options["json_path"])

        if not json_path.exists():
            raise CommandError(
                f"JSON-файл не найден: {json_path}"
            )

        try:
            data = json.loads(
                json_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as error:
            raise CommandError(
                f"Некорректный JSON: {error}"
            ) from error

        dishes_data = data.get("dishes")

        if not isinstance(dishes_data, list):
            raise CommandError(
                "В JSON отсутствует список dishes."
            )

        restaurant, _ = Restaurant.objects.get_or_create(
            slug=options["restaurant_slug"] or "caesar-company",
            defaults={"name": "Caesar & Company"},
        )

        if not restaurant.is_active:
            restaurant.is_active = True
            restaurant.save(update_fields=["is_active"])

        if options["clear"]:
            Dish.objects.filter(restaurant=restaurant).delete()
            Category.objects.filter(restaurant=restaurant).delete()

            self.stdout.write(
                self.style.WARNING(
                    "Старые блюда и категории выбранного ресторана удалены."
                )
            )

        created_dishes = 0
        updated_dishes = 0
        skipped_dishes = 0

        for item in dishes_data:
            category_name = str(
                item.get("category", "")
            ).strip()
            dish_name = str(
                item.get("name", "")
            ).strip()

            if not category_name or not dish_name:
                skipped_dishes += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Пропущена некорректная позиция: {item}"
                    )
                )
                continue

            category, _ = Category.objects.get_or_create(
                restaurant=restaurant,
                name=category_name,
            )
            dish, created = Dish.objects.update_or_create(
                restaurant=restaurant,
                category=category,
                name=dish_name,
                defaults={
                    "description": str(
                        item.get("description_ru", "")
                    ).strip(),
                    "price": (
                        parse_decimal(
                            item.get("price_current_try")
                        )
                        or Decimal("0.00")
                    ),
                    "serving_weight_g": item.get(
                        "serving_weight_g"
                    ),
                    "calories_kcal_per_serving": item.get(
                        "calories_kcal_per_serving"
                    ),
                    "proteins_g_per_serving": parse_decimal(
                        item.get("proteins_g_per_serving")
                    ),
                    "fats_g_per_serving": parse_decimal(
                        item.get("fats_g_per_serving")
                    ),
                    "carbohydrates_g_per_serving": (
                        parse_decimal(
                            item.get(
                                "carbohydrates_g_per_serving"
                            )
                        )
                    ),
                    "is_active": item.get(
                        "is_active",
                        True,
                    ),
                    "is_available": item.get(
                        "is_available",
                        True,
                    ),
                },
            )

            if created:
                created_dishes += 1
            else:
                updated_dishes += 1

            dish.dish_ingredients.all().delete()

            ingredients_text = str(
                item.get("ingredients_text_ru", "")
            )
            ingredient_names = []

            for raw_name in ingredients_text.split(";"):
                ingredient_name = raw_name.strip()

                if (
                    ingredient_name
                    and ingredient_name not in ingredient_names
                ):
                    ingredient_names.append(ingredient_name)

            for ingredient_name in ingredient_names:
                ingredient, _ = Ingredient.objects.get_or_create(
                    name=ingredient_name,
                    defaults={
                        "is_active": True,
                    },
                )
                assign_detected_allergens_to_ingredient(ingredient)

                DishIngredient.objects.create(
                    dish=dish,
                    ingredient=ingredient,
                    amount=None,
                    unit="",
                    can_be_removed=False,
                    notes="Количество не указано в источнике",
                )

            dish.may_contain_allergens.clear()

            if options["with_allergens"]:
                suggested_allergens = item.get(
                    "suggested_allergens",
                    [],
                )

                for allergen_name in suggested_allergens:
                    allergen = get_or_create_allergen(
                        allergen_name
                    )

                    if allergen is None:
                        self.stdout.write(
                            self.style.WARNING(
                                "Неизвестный аллерген пропущен: "
                                f"{allergen_name}"
                            )
                        )
                        continue

                    dish.may_contain_allergens.add(allergen)

        self.stdout.write(
            self.style.SUCCESS(
                "Импорт завершён.\n"
                f"Создано блюд: {created_dishes}\n"
                f"Обновлено блюд: {updated_dishes}\n"
                f"Пропущено: {skipped_dishes}"
            )
        )
