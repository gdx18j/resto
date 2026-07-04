from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F, Prefetch, Q

from menu.models import (
    Allergen,
    Category,
    CategoryTranslation,
    Dish,
    DishAllergen,
    DishTranslation,
)
from menu.translations import LANGUAGE_CHOICES
from orders.models import Restaurant


LANGUAGE_CODES = tuple(code for code, _label in LANGUAGE_CHOICES)
SUSPICIOUS_CATEGORY_PREFIXES = ("menu", "category-menu")
SUSPICIOUS_NAME_MIN_DIGITS = 6


def is_suspicious_category_name(value):
    text = str(value or "").strip().lower()
    if not text:
        return True

    digit_count = sum(character.isdigit() for character in text)
    compact = text.replace("-", "").replace("_", "").replace(" ", "")

    return (
        digit_count >= SUSPICIOUS_NAME_MIN_DIGITS
        and compact.startswith(SUSPICIOUS_CATEGORY_PREFIXES)
    )


class IssueCollector:
    def __init__(self):
        self._items = []

    def add(self, code, message):
        self._items.append((code, message))

    @property
    def has_items(self):
        return bool(self._items)

    def __len__(self):
        return len(self._items)

    def grouped(self):
        grouped = defaultdict(list)
        for code, message in self._items:
            grouped[code].append(message)
        return dict(grouped)


class Command(BaseCommand):
    help = (
        "Проверяет данные меню ресторана и выводит потенциальные проблемы "
        "без изменения базы."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--restaurant-slug",
            default="caesar-company",
            help="Slug ресторана для проверки.",
        )
        parser.add_argument(
            "--fail-on-problems",
            action="store_true",
            help="Завершить команду с ошибкой, если найдены проблемы.",
        )

    def handle(self, *args, **options):
        slug = str(options["restaurant_slug"] or "").strip()
        if not slug:
            raise CommandError("--restaurant-slug не может быть пустым.")

        restaurant = Restaurant.objects.filter(slug=slug).first()
        if restaurant is None:
            raise CommandError(f"Ресторан не найден: {slug}")

        issues = IssueCollector()
        self._inspect_categories(restaurant, issues)
        self._inspect_dishes(restaurant, issues)
        self._inspect_allergens(restaurant, issues)

        self._write_summary(restaurant, issues)

        if options["fail_on_problems"] and issues.has_items:
            raise CommandError(
                f"Найдены проблемы в данных меню: {len(issues)}"
            )

    def _inspect_categories(self, restaurant, issues):
        categories = list(
            Category.objects.filter(restaurant=restaurant)
            .annotate(dish_count=Count("dishes"))
            .prefetch_related(
                Prefetch(
                    "translations",
                    queryset=CategoryTranslation.objects.only(
                        "category_id",
                        "language",
                        "name",
                    ),
                )
            )
            .order_by("name", "id")
        )

        seen_lower_names = defaultdict(list)
        for category in categories:
            seen_lower_names[category.name.strip().casefold()].append(category)

            if is_suspicious_category_name(category.name):
                issues.add(
                    "suspicious_category_name",
                    f"Category #{category.pk}: {category.name!r}",
                )

            if category.dish_count == 0:
                issues.add(
                    "empty_category",
                    f"Category #{category.pk}: {category.name!r}",
                )

            existing_languages = {
                translation.language
                for translation in category.translations.all()
                if translation.name.strip()
            }
            missing_languages = sorted(set(LANGUAGE_CODES) - existing_languages)
            if missing_languages:
                issues.add(
                    "category_missing_translations",
                    (
                        f"Category #{category.pk}: {category.name!r}; "
                        f"missing={', '.join(missing_languages)}"
                    ),
                )

        for normalized_name, duplicates in seen_lower_names.items():
            if normalized_name and len(duplicates) > 1:
                ids = ", ".join(str(category.pk) for category in duplicates)
                issues.add(
                    "case_duplicate_category_names",
                    f"Name {normalized_name!r}: category ids {ids}",
                )

    def _inspect_dishes(self, restaurant, issues):
        dishes = list(
            Dish.objects.filter(restaurant=restaurant)
            .select_related("category")
            .prefetch_related("translations", "dish_ingredients")
            .order_by("name", "id")
        )

        seen_lower_codes = defaultdict(list)
        for dish in dishes:
            if dish.code:
                seen_lower_codes[dish.code.casefold()].append(dish)

            if dish.category_id is None:
                issues.add(
                    "dish_without_category",
                    f"Dish #{dish.pk}: {dish.name!r}",
                )
            elif dish.category.restaurant_id != restaurant.pk:
                issues.add(
                    "dish_category_restaurant_mismatch",
                    (
                        f"Dish #{dish.pk}: {dish.name!r}; "
                        f"category #{dish.category_id} belongs to "
                        f"restaurant #{dish.category.restaurant_id}"
                    ),
                )

            if dish.is_active and not dish.image:
                issues.add(
                    "active_dish_without_image",
                    f"Dish #{dish.pk}: {dish.name!r}",
                )

            if dish.is_active and dish.is_available and dish.price <= 0:
                issues.add(
                    "orderable_dish_non_positive_price",
                    f"Dish #{dish.pk}: {dish.name!r}; price={dish.price}",
                )

            if not dish.dish_ingredients.all():
                issues.add(
                    "dish_without_ingredients",
                    f"Dish #{dish.pk}: {dish.name!r}",
                )

            existing_languages = {
                translation.language
                for translation in dish.translations.all()
                if translation.name.strip()
            }
            missing_languages = sorted(set(LANGUAGE_CODES) - existing_languages)
            if missing_languages:
                issues.add(
                    "dish_missing_translations",
                    (
                        f"Dish #{dish.pk}: {dish.name!r}; "
                        f"missing={', '.join(missing_languages)}"
                    ),
                )

        for normalized_code, duplicates in seen_lower_codes.items():
            if normalized_code and len(duplicates) > 1:
                ids = ", ".join(str(dish.pk) for dish in duplicates)
                issues.add(
                    "case_duplicate_dish_codes",
                    f"Code {normalized_code!r}: dish ids {ids}",
                )

    def _inspect_allergens(self, restaurant, issues):
        active_orderable_dishes = Dish.objects.filter(
            restaurant=restaurant,
            is_active=True,
            is_available=True,
        )
        stale_verified_links = DishAllergen.objects.filter(
            dish__in=active_orderable_dishes,
            verification_status=DishAllergen.VerificationStatus.VERIFIED,
        ).exclude(reviewed_recipe_revision=F("dish__recipe_revision"))

        for link in stale_verified_links.select_related("dish", "allergen")[:50]:
            issues.add(
                "stale_verified_allergen_link",
                (
                    f"Dish #{link.dish_id}: {link.dish.name!r}; "
                    f"allergen={link.allergen.name!r}; "
                    f"reviewed_revision={link.reviewed_recipe_revision}; "
                    f"current_revision={link.dish.recipe_revision}"
                ),
            )

        used_allergens = Allergen.objects.filter(
            Q(dish_links__dish__restaurant=restaurant)
            | Q(ingredients__dish_ingredients__dish__restaurant=restaurant)
        ).distinct()
        allergens_missing_translations = used_allergens.annotate(
            translation_count=Count(
                "translations",
                filter=Q(translations__language__in=LANGUAGE_CODES),
                distinct=True,
            )
        ).filter(translation_count__lt=len(LANGUAGE_CODES))

        for allergen in allergens_missing_translations.order_by("name", "id")[:50]:
            existing_languages = set(
                allergen.translations.filter(
                    language__in=LANGUAGE_CODES,
                ).values_list("language", flat=True)
            )
            missing_languages = sorted(set(LANGUAGE_CODES) - existing_languages)
            issues.add(
                "allergen_missing_translations",
                (
                    f"Allergen #{allergen.pk}: {allergen.name!r}; "
                    f"missing={', '.join(missing_languages)}"
                ),
            )

    def _write_summary(self, restaurant, issues):
        counts = {
            "categories": Category.objects.filter(restaurant=restaurant).count(),
            "dishes": Dish.objects.filter(restaurant=restaurant).count(),
            "active_dishes": Dish.objects.filter(
                restaurant=restaurant,
                is_active=True,
            ).count(),
            "orderable_dishes": Dish.objects.filter(
                restaurant=restaurant,
                is_active=True,
                is_available=True,
            ).count(),
        }

        self.stdout.write(f"Restaurant: {restaurant.name} ({restaurant.slug})")
        self.stdout.write(
            "Counts: "
            + ", ".join(
                f"{name}={value}" for name, value in counts.items()
            )
        )

        if not issues.has_items:
            self.stdout.write(self.style.SUCCESS("Menu data inspection passed."))
            return

        self.stdout.write(self.style.WARNING(f"Problems found: {len(issues)}"))
        for code, messages in sorted(issues.grouped().items()):
            self.stdout.write(self.style.WARNING(f"[{code}] {len(messages)}"))
            for message in messages[:10]:
                self.stdout.write(f"  - {message}")
            if len(messages) > 10:
                self.stdout.write(f"  ... and {len(messages) - 10} more")
