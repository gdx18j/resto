from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, UserAllergy


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    ordering = ("email",)

    list_display = (
        "email",
        "first_name",
        "last_name",
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