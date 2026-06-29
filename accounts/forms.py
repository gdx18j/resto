from django import forms

from menu.models import Allergen
from menu.translations import localized_allergen_html


class LocalizedAllergenMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return localized_allergen_html(obj)


class AllergyPreferencesForm(forms.Form):
    allergens = LocalizedAllergenMultipleChoiceField(
        queryset=Allergen.objects.order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Пищевые ограничения",
    )
