from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .allergen_review import (
    complete_dish_allergen_review,
    invalidate_dish_allergen_review,
    reopen_dish_allergen_link,
    reopen_dish_allergen_review,
    review_dish_allergen_link,
    suppress_recipe_review_signals,
)
from .models import (
    Allergen,
    AllergenTranslation,
    Category,
    CategoryTranslation,
    Dish,
    DishAllergen,
    DishAllergenReviewEvent,
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

    @admin.display(description="Справочные аллергены")
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
    can_delete = False
    show_change_link = True
    fields = (
        "allergen",
        "relation_type",
        "source",
        "verification_status",
        "reviewed_recipe_revision",
        "reviewed_by",
        "reviewed_at",
        "notes",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Dish)
class DishAdmin(StableCodeAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "restaurant",
        "category",
        "price",
        "recipe_revision",
        "allergen_review_status",
        "allergen_reviewed_revision",
        "translation_count",
        "is_available",
        "is_active",
    )

    list_filter = (
        "restaurant",
        "category",
        "allergen_review_status",
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

    readonly_fields = (
        "recipe_revision",
        "allergen_review_status",
        "allergen_reviewed_revision",
        "allergen_reviewed_by",
        "allergen_reviewed_at",
    )

    inlines = (
        DishTranslationInline,
        DishIngredientInline,
        DishAllergenInline,
    )

    actions = (
        "complete_selected_allergen_reviews",
        "reopen_selected_allergen_reviews",
    )

    @admin.display(description="Translations")
    def translation_count(self, obj):
        return obj.translations.count()

    def save_formset(self, request, form, formset, change):
        if formset.model is not DishIngredient:
            return super().save_formset(request, form, formset, change)

        recipe_changed = any(
            item_form.has_changed()
            for item_form in formset.forms
            if hasattr(item_form, "has_changed")
        )
        with suppress_recipe_review_signals():
            result = super().save_formset(request, form, formset, change)

        if recipe_changed and form.instance.pk:
            invalidate_dish_allergen_review(
                form.instance.pk,
                actor=request.user,
                reason="Состав блюда изменён через административную панель.",
            )
        return result

    @admin.action(description="Завершить проверку аллергенов выбранных блюд")
    def complete_selected_allergen_reviews(self, request, queryset):
        completed = 0
        errors = []
        for dish in queryset:
            try:
                complete_dish_allergen_review(
                    dish.pk,
                    actor=request.user,
                    notes="Проверка завершена через массовое действие Django admin.",
                )
                completed += 1
            except ValidationError as error:
                errors.append(f"{dish}: {'; '.join(error.messages)}")

        if completed:
            self.message_user(
                request,
                f"Проверка завершена для блюд: {completed}.",
                level=messages.SUCCESS,
            )
        if errors:
            self.message_user(
                request,
                "Не удалось завершить проверку: " + " | ".join(errors),
                level=messages.ERROR,
            )

    @admin.action(description="Открыть проверку аллергенов повторно")
    def reopen_selected_allergen_reviews(self, request, queryset):
        for dish in queryset:
            reopen_dish_allergen_review(
                dish.pk,
                actor=request.user,
                reason="Проверка повторно открыта через Django admin.",
            )
        self.message_user(
            request,
            f"Повторно открыто проверок: {queryset.count()}.",
            level=messages.WARNING,
        )


@admin.register(DishAllergen)
class DishAllergenAdmin(admin.ModelAdmin):
    list_display = (
        "dish",
        "allergen",
        "relation_type",
        "source",
        "verification_status",
        "reviewed_recipe_revision",
        "reviewed_by",
        "reviewed_at",
    )
    list_filter = (
        "verification_status",
        "relation_type",
        "source",
        "dish__allergen_review_status",
        "dish__restaurant",
    )
    search_fields = (
        "dish__name",
        "dish__code",
        "allergen__name",
        "allergen__code",
        "notes",
    )
    autocomplete_fields = ("dish", "allergen")
    readonly_fields = (
        "verification_status",
        "reviewed_recipe_revision",
        "reviewed_by",
        "reviewed_at",
        "created_at",
        "updated_at",
    )
    actions = (
        "verify_selected",
        "reject_selected",
        "return_selected_to_review",
    )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.verification_status != DishAllergen.VerificationStatus.SUGGESTED:
            fields.extend(("dish", "allergen", "relation_type", "source", "notes"))
        return tuple(dict.fromkeys(fields))

    def save_model(self, request, obj, form, change):
        if not change:
            obj.verification_status = DishAllergen.VerificationStatus.SUGGESTED
            obj.reviewed_recipe_revision = None
            obj.reviewed_by = None
            obj.reviewed_at = None
        super().save_model(request, obj, form, change)
        if not change:
            reopen_dish_allergen_review(
                obj.dish_id,
                actor=request.user,
                reason=f"Добавлено предложение по аллергену «{obj.allergen}».",
            )

    @admin.action(description="Подтвердить выбранные связи для текущего рецепта")
    def verify_selected(self, request, queryset):
        for link in queryset:
            review_dish_allergen_link(
                link.pk,
                decision=DishAllergen.VerificationStatus.VERIFIED,
                actor=request.user,
            )
        self.message_user(
            request,
            f"Подтверждено связей: {queryset.count()}.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Отклонить выбранные предложения")
    def reject_selected(self, request, queryset):
        for link in queryset:
            review_dish_allergen_link(
                link.pk,
                decision=DishAllergen.VerificationStatus.REJECTED,
                actor=request.user,
            )
        self.message_user(
            request,
            f"Отклонено связей: {queryset.count()}.",
            level=messages.WARNING,
        )

    @admin.action(description="Вернуть выбранные связи на повторную проверку")
    def return_selected_to_review(self, request, queryset):
        for link in queryset:
            reopen_dish_allergen_link(
                link.pk,
                actor=request.user,
                reason="Связь возвращена на проверку через Django admin.",
            )
        self.message_user(
            request,
            f"Возвращено на проверку: {queryset.count()}.",
            level=messages.WARNING,
        )


@admin.register(DishAllergenReviewEvent)
class DishAllergenReviewEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "dish",
        "allergen",
        "action",
        "recipe_revision",
        "actor",
    )
    list_filter = ("action", "dish__restaurant", "recipe_revision")
    search_fields = ("dish__name", "allergen__name", "notes")
    readonly_fields = (
        "dish",
        "allergen",
        "action",
        "recipe_revision",
        "relation_type",
        "actor",
        "notes",
        "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
