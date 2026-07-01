from django import forms
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from allauth.account.forms import (
    LoginForm,
    ResetPasswordForm,
    ResetPasswordKeyForm,
    SignupForm,
)

from menu.models import Allergen
from menu.translations import localized_allergen_html


PASSWORD_PLACEHOLDER = "Пароль"
PASSWORD_CONFIRM_PLACEHOLDER = "Повторите пароль"
EMAIL_PLACEHOLDER = "Email"


class LocalizedAuthFormMixin:
    field_placeholders = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._localize_fields()

    def _localize_fields(self):
        for field_name, placeholder in self.field_placeholders.items():
            field = self.fields.get(field_name)

            if field:
                field.widget.attrs["placeholder"] = placeholder


class LocalizedLoginForm(LocalizedAuthFormMixin, LoginForm):
    field_placeholders = {
        "login": EMAIL_PLACEHOLDER,
        "password": PASSWORD_PLACEHOLDER,
    }


class LocalizedSignupForm(LocalizedAuthFormMixin, SignupForm):
    field_placeholders = {
        "email": EMAIL_PLACEHOLDER,
        "password1": PASSWORD_PLACEHOLDER,
        "password2": PASSWORD_CONFIRM_PLACEHOLDER,
    }


class LocalizedResetPasswordForm(LocalizedAuthFormMixin, ResetPasswordForm):
    field_placeholders = {
        "email": EMAIL_PLACEHOLDER,
    }


class LocalizedResetPasswordKeyForm(LocalizedAuthFormMixin, ResetPasswordKeyForm):
    field_placeholders = {
        "password1": PASSWORD_PLACEHOLDER,
        "password2": PASSWORD_CONFIRM_PLACEHOLDER,
    }


ALLERGEN_ICONS = {
    "gluten": '<path d="M12 20V7"/><path d="M8 10c-2.4 1-3.4 3-3 5 2.4-.2 4-1.7 4.2-4"/><path d="M16 10c2.4 1 3.4 3 3 5-2.4-.2-4-1.7-4.2-4"/><path d="M9 6c0-2 1.3-3.5 3-4 1.7.5 3 2 3 4-1.2.2-2.2.2-3 0-1 .2-2 .2-3 0Z"/>',
    "milk": '<path d="M9 3h6"/><path d="M10 3v4l-2 2v10a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V9l-2-2V3"/><path d="M8 12h8"/>',
    "egg": '<path d="M17 14c0 4.1-2.2 7-5 7s-5-2.9-5-7c0-5 2.3-11 5-11s5 6 5 11Z"/>',
    "peanut": '<path d="M9.5 4.5c2.1-1 4.2.4 4.4 2.7.2 1.4.9 1.8 2 2.6 2 1.5 2.2 4.5.5 6.5-1.7 2.1-4.8 2.4-6.3.6-.8-1-1.1-1.2-2.4-.9-2.4.5-4.4-1.5-4.1-4 .2-2.1 1.5-3.1 3.1-3.8 1.1-.5 1.4-1.1 1.5-2 .1-.8.4-1.3 1.3-1.7Z"/><path d="M8.5 11.5h.1M13.5 13.5h.1"/>',
    "tree-nuts": '<path d="M12 3c3.6 1.6 5.8 4.5 5.8 8.5 0 4.8-2.6 8.5-5.8 8.5s-5.8-3.7-5.8-8.5C6.2 7.5 8.4 4.6 12 3Z"/><path d="M8.5 11.5c1.8 1 5.2 1 7 0"/><path d="M12 3v4"/>',
    "fish": '<path d="M3 12s3.2-5 8.2-5c4.5 0 7.8 5 7.8 5s-3.3 5-7.8 5C6.2 17 3 12 3 12Z"/><path d="m19 12 3-3v6l-3-3Z"/><path d="M9 12h.1"/><path d="M12 8.5c1 1.9 1 5.1 0 7"/>',
    "shellfish": '<path d="M12 5c3 0 5.5 2.4 5.5 5.4 0 4-3.1 7.1-5.5 9.1-2.4-2-5.5-5.1-5.5-9.1C6.5 7.4 9 5 12 5Z"/><path d="M8.5 10.5h7"/><path d="M5 7 3 5M19 7l2-2"/><path d="M10 3v3M14 3v3"/>',
    "soy": '<path d="M8 15c-2.5-2.5-2.6-6.1-.3-8.3 3.4.2 5.6 2.2 5.8 5.7-1.7 1.9-3.6 2.7-5.5 2.6Z"/><path d="M13 18c1.3-3.3 4-4.7 7-4-1 3.6-3.3 5.2-7 4Z"/><path d="M7.5 7.2 16 19"/>',
    "sesame": '<path d="M8.5 13.5c-1.4-2.2-.7-5.1 1.8-7 2.3 1.9 3.1 4.8 1.8 7-1 1.7-2.7 1.7-3.6 0Z"/><path d="M14.8 17.4c-1.1-1.7-.5-4 1.4-5.4 1.8 1.5 2.4 3.7 1.4 5.4-.8 1.3-2.1 1.3-2.8 0Z"/><path d="M5.4 18.1c-1-1.6-.5-3.8 1.3-5.2 1.7 1.4 2.2 3.6 1.3 5.2-.7 1.1-1.9 1.1-2.6 0Z"/>',
    "mustard": '<path d="M9 3h6"/><path d="M10 3v4l-2 2v10a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V9l-2-2V3"/><path d="M8 13h8"/><path d="M11 16h2"/>',
    "celery": '<path d="M12 21V9"/><path d="M12 9c-2.2-2-4.5-3-7-3 .4 3.1 2.3 5 5.7 5.8"/><path d="M12 9c2.2-2 4.5-3 7-3-.4 3.1-2.3 5-5.7 5.8"/><path d="M9 21h6"/>',
    "lupin": '<path d="M12 21V9"/><path d="M12 9c-2.2-.8-3.5-2.5-3.8-5 2.3.3 3.8 1.5 4.5 3.6"/><path d="M12 10c2.2-.8 3.5-2.5 3.8-5-2.3.3-3.8 1.5-4.5 3.6"/><path d="M7 21h10"/>',
    "sulfites": '<path d="M8 3h8"/><path d="M10 3v5l-3.5 8A3.5 3.5 0 0 0 9.7 21h4.6a3.5 3.5 0 0 0 3.2-5L14 8V3"/><path d="M8 16h8"/>',
    "honey": '<path d="M8 4h8l2 4-6 12L6 8l2-4Z"/><path d="M6 8h12"/><path d="M10 4l2 4 2-4"/><path d="M10 14h4"/>',
}
DEFAULT_ALLERGEN_ICON = '<path d="M12 3 21 19H3L12 3Z"/><path d="M12 9v4"/><path d="M12 17h.1"/>'


class LocalizedAllergenMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        icon_paths = mark_safe(ALLERGEN_ICONS.get(obj.code, DEFAULT_ALLERGEN_ICON))
        icon_class = f"allergen-chip__icon--{obj.code}"

        return format_html(
            '<span class="allergen-chip__icon {}" aria-hidden="true">'
            '<svg viewBox="0 0 24 24">{}</svg>'
            '</span>'
            '<span class="allergen-chip__name">{}</span>',
            icon_class,
            icon_paths,
            localized_allergen_html(obj),
        )


class AllergyPreferencesForm(forms.Form):
    allergens = LocalizedAllergenMultipleChoiceField(
        queryset=Allergen.objects.order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Пищевые ограничения",
    )
    share_allergies_with_ai = forms.BooleanField(
        required=False,
        label="Передавать подтвержденные аллергены ИИ-ассистенту",
    )
