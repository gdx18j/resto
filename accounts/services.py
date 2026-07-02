from django.contrib.auth import get_user_model
from django.db import transaction

from .models import UserAllergy, UserAllergyStatusChange


MANUAL_PROFILE_UPDATE = "manual_profile_update"


def _record_status_change(
    *,
    allergy,
    actor,
    old_status,
    new_status,
    old_source,
    new_source,
    reason=MANUAL_PROFILE_UPDATE,
):
    UserAllergyStatusChange.objects.create(
        allergy=allergy,
        actor=actor,
        old_status=old_status or "",
        new_status=new_status,
        old_source=old_source or "",
        new_source=new_source,
        reason=reason,
    )


def _set_allergy_state(allergy, *, status, source, actor):
    old_status = allergy.status
    old_source = allergy.source

    if old_status == status and old_source == source:
        return allergy

    allergy.status = status
    allergy.source = source
    allergy.save(update_fields=["status", "source", "updated_at"])
    _record_status_change(
        allergy=allergy,
        actor=actor,
        old_status=old_status,
        new_status=status,
        old_source=old_source,
        new_source=source,
    )
    return allergy


def update_manual_allergy_preferences(user, selected_allergens, share_allergies_with_ai):
    selected_ids = set(selected_allergens.values_list("id", flat=True))
    user_model = get_user_model()

    with transaction.atomic():
        locked_user = user_model.objects.select_for_update().get(pk=user.pk)
        records = {
            record.allergen_id: record
            for record in UserAllergy.objects.select_for_update().filter(
                user=locked_user,
            )
        }

        locked_user.share_allergies_with_ai = share_allergies_with_ai
        locked_user.save(update_fields=["share_allergies_with_ai"])

        for record in records.values():
            if (
                record.status == UserAllergy.Status.CONFIRMED
                and record.allergen_id not in selected_ids
            ):
                _set_allergy_state(
                    record,
                    status=UserAllergy.Status.REJECTED,
                    source=UserAllergy.Source.MANUAL,
                    actor=locked_user,
                )

        for allergen_id in selected_ids:
            record = records.get(allergen_id)

            if record is None:
                record = UserAllergy.objects.create(
                    user=locked_user,
                    allergen_id=allergen_id,
                    source=UserAllergy.Source.MANUAL,
                    status=UserAllergy.Status.CONFIRMED,
                )
                _record_status_change(
                    allergy=record,
                    actor=locked_user,
                    old_status="",
                    new_status=UserAllergy.Status.CONFIRMED,
                    old_source="",
                    new_source=UserAllergy.Source.MANUAL,
                )
                continue

            if record.status != UserAllergy.Status.CONFIRMED:
                _set_allergy_state(
                    record,
                    status=UserAllergy.Status.CONFIRMED,
                    source=UserAllergy.Source.MANUAL,
                    actor=locked_user,
                )

    user.share_allergies_with_ai = share_allergies_with_ai
