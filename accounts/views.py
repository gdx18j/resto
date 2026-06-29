from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from menu.translations import localized_allergen_html

from .forms import AllergyPreferencesForm
from .models import UserAllergy


@login_required
def profile(request):
    allergy_records = (
        request.user.allergy_records
        .filter(status=UserAllergy.Status.CONFIRMED)
        .select_related("allergen")
        .order_by("allergen__name")
    )
    allergy_records = list(allergy_records)

    for record in allergy_records:
        record.allergen.localized_name_html = localized_allergen_html(
            record.allergen
        )

    context = {
        "allergy_records": allergy_records,
    }

    return render(
        request,
        "accounts/profile.html",
        context,
    )


@login_required
def edit_allergies(request):
    confirmed_records = UserAllergy.objects.filter(
        user=request.user,
        status=UserAllergy.Status.CONFIRMED,
    )
    current_allergen_ids = confirmed_records.values_list(
        "allergen_id",
        flat=True,
    )

    if request.method == "POST":
        form = AllergyPreferencesForm(request.POST)

        if form.is_valid():
            selected_allergens = form.cleaned_data["allergens"]
            selected_ids = set(
                selected_allergens.values_list("id", flat=True)
            )

            if selected_ids:
                confirmed_records.exclude(
                    allergen_id__in=selected_ids
                ).delete()
            else:
                confirmed_records.delete()

            for allergen in selected_allergens:
                UserAllergy.objects.update_or_create(
                    user=request.user,
                    allergen=allergen,
                    defaults={
                        "source": UserAllergy.Source.MANUAL,
                        "status": UserAllergy.Status.CONFIRMED,
                    },
                )

            messages.success(
                request,
                "Пищевые ограничения сохранены.",
            )

            return redirect("accounts:profile")

    else:
        form = AllergyPreferencesForm(
            initial={
                "allergens": current_allergen_ids,
            }
        )

    context = {
        "form": form,
    }

    return render(
        request,
        "accounts/edit_allergies.html",
        context,
    )
