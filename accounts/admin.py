from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, UserAllergy, UserAllergyStatusChange


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    ordering = ("email",)

    list_display = (
        "email",
        "first_name",
        "last_name",
        "share_allergies_with_ai",
        "is_active",
        "is_staff",
    )

    search_fields = (
        "email",
        "first_name",
        "last_name",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "email",
                    "password",
                )
            },
        ),
        (
            "Личные данные",
            {
                "fields": (
                    "first_name",
                    "last_name",
                )
            },
        ),
        (
            "Права",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Приватность ИИ",
            {
                "fields": (
                    "share_allergies_with_ai",
                )
            },
        ),
        (
            "Важные даты",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )

@admin.register(UserAllergy)
class UserAllergyAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "allergen",
        "status",
        "source",
        "created_at",
    )

    list_filter = (
        "status",
        "source",
        "allergen",
    )

    search_fields = (
        "allergen__name",
        "user__email",
    )

    list_select_related = (
        "user",
        "allergen",
    )


@admin.register(UserAllergyStatusChange)
class UserAllergyStatusChangeAdmin(admin.ModelAdmin):
    list_display = (
        "allergy",
        "actor",
        "old_status",
        "new_status",
        "old_source",
        "new_source",
        "reason",
        "created_at",
    )

    list_filter = (
        "old_status",
        "new_status",
        "old_source",
        "new_source",
        "reason",
    )

    search_fields = (
        "allergy__user__email",
        "allergy__allergen__name",
        "actor__email",
        "reason",
    )

    list_select_related = (
        "allergy",
        "allergy__user",
        "allergy__allergen",
        "actor",
    )

    readonly_fields = (
        "allergy",
        "actor",
        "old_status",
        "new_status",
        "old_source",
        "new_source",
        "reason",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
