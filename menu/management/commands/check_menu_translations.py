from django.core.management.base import BaseCommand, CommandError

from menu.models import Allergen, Category, Dish
from menu.translations import LANGUAGES


class Command(BaseCommand):
    help = "Validate that menu objects have complete translation rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--restaurant-slug",
            default="",
            help="Limit category and dish checks to one restaurant.",
        )
        parser.add_argument(
            "--skip-allergens",
            action="store_true",
            help="Do not validate allergen translations.",
        )

    def _translation_map(self, obj):
        return {
            translation.language: translation
            for translation in obj.translations.all()
        }

    def _category_errors(self, restaurant_slug):
        categories = Category.objects.prefetch_related("translations").filter(
            dishes__is_active=True,
        )

        if restaurant_slug:
            categories = categories.filter(restaurant__slug=restaurant_slug)

        errors = []

        for category in categories.distinct():
            translations = self._translation_map(category)

            for language in LANGUAGES:
                translation = translations.get(language)

                if not translation or not translation.name.strip():
                    errors.append(
                        f"category:{category.code}:{language}: missing name"
                    )

        return errors

    def _dish_errors(self, restaurant_slug):
        dishes = Dish.objects.prefetch_related("translations").filter(is_active=True)

        if restaurant_slug:
            dishes = dishes.filter(restaurant__slug=restaurant_slug)

        errors = []

        for dish in dishes:
            translations = self._translation_map(dish)

            for language in LANGUAGES:
                translation = translations.get(language)

                if not translation or not translation.name.strip():
                    errors.append(f"dish:{dish.code}:{language}: missing name")

                if dish.description.strip() and (
                    not translation or not translation.description.strip()
                ):
                    errors.append(
                        f"dish:{dish.code}:{language}: missing description"
                    )

        return errors

    def _allergen_errors(self):
        errors = []

        for allergen in Allergen.objects.prefetch_related("translations"):
            translations = self._translation_map(allergen)

            for language in LANGUAGES:
                translation = translations.get(language)

                if not translation or not translation.name.strip():
                    errors.append(
                        f"allergen:{allergen.code}:{language}: missing name"
                    )

        return errors

    def handle(self, *args, **options):
        errors = []
        restaurant_slug = options["restaurant_slug"].strip()

        errors.extend(self._category_errors(restaurant_slug))
        errors.extend(self._dish_errors(restaurant_slug))

        if not options["skip_allergens"]:
            errors.extend(self._allergen_errors())

        if errors:
            for error in errors:
                self.stderr.write(error)

            raise CommandError(f"Missing menu translations: {len(errors)}")

        self.stdout.write(self.style.SUCCESS("Menu translations are complete."))
