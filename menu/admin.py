from django.contrib import admin

from .models import (
    Allergen,
    Category,
    Dish,
    DishIngredient,
    Ingredient,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "restaurant")
    list_filter = ("restaurant",)
    search_fields = ("name",)


@admin.register(Allergen)
class AllergenAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ("name", "allergen_names", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    filter_horizontal = ("allergens",)

    @admin.display(description="Аллергены")
    def allergen_names(self, obj):
        return ", ".join(
            obj.allergens.order_by("name").values_list(
                "name",
                flat=True,
            )
        )


class DishIngredientInline(admin.TabularInline):
    model = DishIngredient
    extra = 1
    autocomplete_fields = ("ingredient",)


@admin.register(Dish)
class DishAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "restaurant",
        "category",
        "price",
        "is_available",
        "is_active",
    )

    list_filter = (
        "restaurant",
        "category",
        "is_available",
        "is_active",
    )

    search_fields = (
        "name",
        "description",
    )

    filter_horizontal = (
        "may_contain_allergens",
    )

    inlines = (
        DishIngredientInline,
    )
