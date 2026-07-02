from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from .codes import build_stable_code
from .translations import LANGUAGE_CHOICES


def build_unique_model_code(model, base_code, filters, instance_pk=None, max_length=220):
    code = base_code[:max_length]
    suffix = 2

    while (
        model.objects.filter(**filters, code=code)
        .exclude(pk=instance_pk)
        .exists()
    ):
        suffix_text = f"-{suffix}"
        code = f"{base_code[: max_length - len(suffix_text)]}{suffix_text}"
        suffix += 1

    return code


def get_default_restaurant_id():
    from orders.models import Restaurant

    restaurant, _ = Restaurant.objects.get_or_create(
        slug="caesar-company",
        defaults={"name": "Caesar & Company"},
    )

    if not restaurant.is_active:
        restaurant.is_active = True
        restaurant.save(update_fields=["is_active"])

    return restaurant.id


class Category(models.Model):
    """
    Категория блюда:
    супы, салаты, горячее, десерты, напитки и т. д.
    """

    restaurant = models.ForeignKey(
        "orders.Restaurant",
        on_delete=models.CASCADE,
        related_name="menu_categories",
        default=get_default_restaurant_id,
        verbose_name="Ресторан",
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Название",
    )

    code = models.SlugField(
        max_length=200,
        blank=True,
        db_index=True,
        verbose_name="Code",
        help_text="Stable translation key. It is not changed when the name is renamed.",
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ["restaurant__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "name"],
                name="unique_category_name_per_restaurant",
            ),
            models.UniqueConstraint(
                fields=["restaurant", "code"],
                name="unique_category_code_per_restaurant",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            base_code = build_stable_code(self.name, prefix="category")
            self.code = build_unique_model_code(
                Category,
                base_code,
                {"restaurant_id": self.restaurant_id},
                instance_pk=self.pk,
                max_length=200,
            )

        super().save(*args, **kwargs)


class Allergen(models.Model):
    """
    Аллерген:
    молоко, яйца, арахис, рыба, глютен и т. д.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Название",
    )

    code = models.SlugField(
        max_length=100,
        unique=True,
        verbose_name="Системный код",
        help_text="Например: milk, egg, peanut, gluten",
    )

    class Meta:
        verbose_name = "Аллерген"
        verbose_name_plural = "Аллергены"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Ingredient(models.Model):
    """
    Отдельный ингредиент.

    Один ингредиент может содержать несколько аллергенов.
    Например, майонез может содержать яйца и горчицу.
    """

    name = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Название",
    )

    allergens = models.ManyToManyField(
        Allergen,
        blank=True,
        related_name="ingredients",
        verbose_name="Аллергены",
    )

    description = models.TextField(
        blank=True,
        verbose_name="Описание",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Используется",
    )

    class Meta:
        verbose_name = "Ингредиент"
        verbose_name_plural = "Ингредиенты"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Dish(models.Model):
    """
    Блюдо ресторана.
    Все значения КБЖУ указываются на одну порцию.
    """

    restaurant = models.ForeignKey(
        "orders.Restaurant",
        on_delete=models.CASCADE,
        related_name="dishes",
        default=get_default_restaurant_id,
        verbose_name="Ресторан",
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dishes",
        verbose_name="Категория",
    )

    name = models.CharField(
        max_length=200,
        verbose_name="Название",
    )

    code = models.SlugField(
        max_length=220,
        blank=True,
        db_index=True,
        verbose_name="Code",
        help_text="Stable translation key. It is not changed when the name is renamed.",
    )

    description = models.TextField(
        blank=True,
        verbose_name="Описание",
    )

    image = models.ImageField(
        upload_to="dishes/%Y/%m/",
        blank=True,
        verbose_name="Фотография",
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Цена",
    )

    serving_weight_g = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Вес порции, г",
    )

    calories_kcal_per_serving = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Калории на порцию, ккал",
    )

    proteins_g_per_serving = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Белки на порцию, г",
    )

    fats_g_per_serving = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Жиры на порцию, г",
    )

    carbohydrates_g_per_serving = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Углеводы на порцию, г",
    )

    preparation_time_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Время приготовления, мин",
    )

    ingredients = models.ManyToManyField(
        Ingredient,
        through="DishIngredient",
        related_name="dishes",
        verbose_name="Ингредиенты",
    )

    may_contain_allergens = models.ManyToManyField(
        Allergen,
        blank=True,
        related_name="may_contain_dishes",
        verbose_name="Может содержать следы аллергенов",
    )

    is_available = models.BooleanField(
        default=True,
        verbose_name="Доступно для заказа",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Показывать в меню",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Создано",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Блюдо"
        verbose_name_plural = "Блюда"
        ordering = ["name"]
        indexes = [
            models.Index(
                fields=["restaurant", "is_active", "is_available"],
                name="dish_rest_active_avail_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "code"],
                name="unique_dish_code_per_restaurant",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            base_code = build_stable_code(self.name, prefix="dish")
            self.code = build_unique_model_code(
                Dish,
                base_code,
                {"restaurant_id": self.restaurant_id},
                instance_pk=self.pk,
                max_length=220,
            )

        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        if (
            self.category_id
            and self.restaurant_id
            and self.category.restaurant_id != self.restaurant_id
        ):
            raise ValidationError(
                {"category": "Категория должна принадлежать тому же ресторану, что и блюдо."}
            )

    def get_allergens(self):
        """
        Возвращает все аллергены блюда:

        1. аллергены, содержащиеся в ингредиентах;
        2. аллергены, следы которых могут присутствовать.
        """

        return Allergen.objects.filter(
            Q(ingredients__dishes=self)
            | Q(may_contain_dishes=self)
            | Q(
                dish_links__dish=self,
                dish_links__verification_status=DishAllergen.VerificationStatus.VERIFIED,
            )
        ).distinct()

    def conflicts_with_allergens(self, allergen_ids):
        """
        Проверяет, конфликтует ли блюдо
        с переданным набором аллергенов.
        """

        return self.get_allergens().filter(
            id__in=allergen_ids
        ).exists()


class DishAllergen(models.Model):
    class RelationType(models.TextChoices):
        CONTAINS = "contains", "Содержит"
        MAY_CONTAIN = "may_contain", "Может содержать"
        CROSS_CONTAMINATION = "cross_contamination", "Может содержать следы"

    class Source(models.TextChoices):
        RECIPE = "recipe", "Рецепт"
        MANUAL = "manual", "Вручную"
        IMPORT = "import", "Импорт"
        HEURISTIC = "heuristic", "Эвристика"

    class VerificationStatus(models.TextChoices):
        VERIFIED = "verified", "Подтверждено"
        SUGGESTED = "suggested", "Предложено"
        REJECTED = "rejected", "Отклонено"

    dish = models.ForeignKey(
        Dish,
        on_delete=models.CASCADE,
        related_name="allergen_links",
        verbose_name="Блюдо",
    )

    allergen = models.ForeignKey(
        Allergen,
        on_delete=models.CASCADE,
        related_name="dish_links",
        verbose_name="Аллерген",
    )

    relation_type = models.CharField(
        max_length=32,
        choices=RelationType.choices,
        default=RelationType.CONTAINS,
        verbose_name="Тип связи",
    )

    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
        verbose_name="Источник",
    )

    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.SUGGESTED,
        db_index=True,
        verbose_name="Статус проверки",
    )

    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Примечание",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Аллерген блюда"
        verbose_name_plural = "Аллергены блюд"
        ordering = ["dish__name", "allergen__name", "relation_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["dish", "allergen", "relation_type"],
                name="unique_dish_allergen_relation",
            ),
        ]
        indexes = [
            models.Index(
                fields=["dish", "verification_status", "relation_type"],
                name="dish_allergen_status_type_idx",
            ),
        ]

    def __str__(self):
        return f"{self.dish}: {self.allergen} ({self.get_relation_type_display()})"


class CategoryTranslation(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="translations",
        verbose_name="Category",
    )
    language = models.CharField(
        max_length=8,
        choices=LANGUAGE_CHOICES,
        verbose_name="Language",
    )
    name = models.CharField(max_length=100, verbose_name="Name")

    class Meta:
        verbose_name = "Category translation"
        verbose_name_plural = "Category translations"
        ordering = ["category__name", "language"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "language"],
                name="unique_category_translation_language",
            ),
        ]

    def __str__(self):
        return f"{self.category} [{self.language}]"


class DishTranslation(models.Model):
    dish = models.ForeignKey(
        Dish,
        on_delete=models.CASCADE,
        related_name="translations",
        verbose_name="Dish",
    )
    language = models.CharField(
        max_length=8,
        choices=LANGUAGE_CHOICES,
        verbose_name="Language",
    )
    name = models.CharField(max_length=200, verbose_name="Name")
    description = models.TextField(blank=True, verbose_name="Description")

    class Meta:
        verbose_name = "Dish translation"
        verbose_name_plural = "Dish translations"
        ordering = ["dish__name", "language"]
        constraints = [
            models.UniqueConstraint(
                fields=["dish", "language"],
                name="unique_dish_translation_language",
            ),
        ]

    def __str__(self):
        return f"{self.dish} [{self.language}]"


class AllergenTranslation(models.Model):
    allergen = models.ForeignKey(
        Allergen,
        on_delete=models.CASCADE,
        related_name="translations",
        verbose_name="Allergen",
    )
    language = models.CharField(
        max_length=8,
        choices=LANGUAGE_CHOICES,
        verbose_name="Language",
    )
    name = models.CharField(max_length=100, verbose_name="Name")

    class Meta:
        verbose_name = "Allergen translation"
        verbose_name_plural = "Allergen translations"
        ordering = ["allergen__name", "language"]
        constraints = [
            models.UniqueConstraint(
                fields=["allergen", "language"],
                name="unique_allergen_translation_language",
            ),
        ]

    def __str__(self):
        return f"{self.allergen} [{self.language}]"


class DishIngredient(models.Model):
    """
    Промежуточная модель между блюдом и ингредиентом.

    Здесь хранится не сам ингредиент, а информация
    о том, как он используется в конкретном блюде.
    """

    class Unit(models.TextChoices):
        GRAM = "g", "г"
        MILLILITER = "ml", "мл"
        PIECE = "piece", "шт."
        TABLESPOON = "tbsp", "ст. ложка"
        TEASPOON = "tsp", "ч. ложка"
        PORTION = "portion", "порция"
        TO_TASTE = "to_taste", "по вкусу"

    dish = models.ForeignKey(
        Dish,
        on_delete=models.CASCADE,
        related_name="dish_ingredients",
        verbose_name="Блюдо",
    )

    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.PROTECT,
        related_name="dish_ingredients",
        verbose_name="Ингредиент",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.000"))],
        verbose_name="Количество",
    )

    unit = models.CharField(
        max_length=20,
        choices=Unit.choices,
        blank=True,
        verbose_name="Единица измерения",
    )

    can_be_removed = models.BooleanField(
        default=False,
        verbose_name="Можно убрать из блюда",
    )

    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Примечание",
        help_text="Например: добавляется при подаче",
    )

    class Meta:
        verbose_name = "Ингредиент блюда"
        verbose_name_plural = "Ингредиенты блюда"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["dish", "ingredient"],
                name="unique_ingredient_per_dish",
            ),
        ]

    def __str__(self):
        if self.amount is not None:
            return (
                f"{self.dish}: {self.ingredient} — "
                f"{self.amount} {self.get_unit_display()}"
            )

        return f"{self.dish}: {self.ingredient}"
