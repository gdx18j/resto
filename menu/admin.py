from django.contrib import admin

from .models import (
    Allergen,
    AllergenTranslation,
    Category,
    CategoryTranslation,
    Dish,
    DishAllergen,
    DishIngredient,
    DishTranslation,
    Ingredient,
)


class CategoryTranslationInline(admin.TabularInline):
    model = CategoryTranslation
    extra = 0


class StableCodeAdminMixin:
    def get_readonly_fields(self, request, obj=None):
        readonly_fields = super().get_readonly_fields(request, obj)
        if obj is None:
            return readonly_fields

        return (*readonly_fields, "code")


@admin.register(Category)
class CategoryAdmin(StableCodeAdminMixin, admin.ModelAdmin):
    list_display = ("name", "code", "restaurant", "translation_count")
    list_filter = ("restaurant",)
    search_fields = ("name", "code", "translations__name")
    inlines = (CategoryTranslationInline,)

    @admin.display(description="Translations")
    def translation_count(self, obj):
        return obj.translations.count()


class AllergenTranslationInline(admin.TabularInline):
    model = AllergenTranslation
    extra = 0


@admin.register(Allergen)
class AllergenAdmin(StableCodeAdminMixin, admin.ModelAdmin):
    list_display = ("name", "code", "translation_count")
    search_fields = ("name", "code", "translations__name")
    inlines = (AllergenTranslationInline,)

    @admin.display(description="Translations")
    def translation_count(self, obj):
        return obj.translations.count()


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


class DishTranslationInline(admin.TabularInline):
    model = DishTranslation
    extra = 0


class DishAllergenInline(admin.TabularInline):
    model = DishAllergen
    extra = 0
    autocomplete_fields = ("allergen",)
    fields = (
        "allergen",
        "relation_type",
        "source",
        "verification_status",
        "notes",
    )


@admin.register(Dish)
class DishAdmin(StableCodeAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "restaurant",
        "category",
        "price",
        "translation_count",
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
        "code",
        "description",
        "translations__name",
        "translations__description",
    )

    filter_horizontal = (
        "may_contain_allergens",
    )

    inlines = (
        DishTranslationInline,
        DishIngredientInline,
        DishAllergenInline,
    )

    @admin.display(description="Translations")
    def translation_count(self, obj):
        return obj.translations.count()


@admin.register(DishAllergen)
class DishAllergenAdmin(admin.ModelAdmin):
    list_display = (
        "dish",
        "allergen",
        "relation_type",
        "source",
        "verification_status",
    )
    list_filter = ("relation_type", "source", "verification_status")
    search_fields = ("dish__name", "allergen__name", "notes")
    autocomplete_fields = ("dish", "allergen")
