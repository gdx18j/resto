from django import forms

from menu.models import Allergen


class AllergyPreferencesForm(forms.Form):
    allergens = forms.ModelMultipleChoiceField(
        queryset=Allergen.objects.order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Пищевые ограничения",
    )