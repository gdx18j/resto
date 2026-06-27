from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class Category(models.Model):
    """
    Категория блюда:
    супы, салаты, горячее, десерты, напитки и т. д.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Название",
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ["name"]

    def __str__(self):
        return self.name


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
                fields=["is_active", "is_available"],
                name="dish_active_available_idx",
            ),
        ]

    def __str__(self):
        return self.name

    def get_allergens(self):
        """
        Возвращает все аллергены блюда:

        1. аллергены, содержащиеся в ингредиентах;
        2. аллергены, следы которых могут присутствовать.
        """

        return Allergen.objects.filter(
            Q(ingredients__dishes=self)
            | Q(may_contain_dishes=self)
        ).distinct()

    def conflicts_with_allergens(self, allergen_ids):
        """
        Проверяет, конфликтует ли блюдо
        с переданным набором аллергенов.
        """

        return self.get_allergens().filter(
            id__in=allergen_ids
        ).exists()


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