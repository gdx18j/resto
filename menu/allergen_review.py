from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Allergen, Dish, DishAllergen, DishAllergenReviewEvent


_recipe_signal_suppression = ContextVar(
    "menu_recipe_signal_suppression",
    default=0,
)


@contextmanager
def suppress_recipe_review_signals():
    """Temporarily suppress automatic recipe invalidation signals.

    Bulk operations such as menu import use this context and perform one explicit
    revision update after the complete recipe has been replaced.
    """

    current = _recipe_signal_suppression.get()
    token = _recipe_signal_suppression.set(current + 1)
    try:
        yield
    finally:
        _recipe_signal_suppression.reset(token)


def recipe_review_signals_suppressed():
    return _recipe_signal_suppression.get() > 0


def _actor_or_none(actor):
    if actor is None or not getattr(actor, "is_authenticated", False):
        return None
    return actor


def _create_event(
    *,
    dish,
    action,
    actor=None,
    allergen=None,
    relation_type="",
    notes="",
):
    return DishAllergenReviewEvent.objects.create(
        dish=dish,
        allergen=allergen,
        action=action,
        recipe_revision=dish.recipe_revision,
        relation_type=relation_type or "",
        actor=_actor_or_none(actor),
        notes=(notes or "")[:500],
    )


def recipe_signature_for_dish(dish):
    """Return a stable signature of the recipe-affecting dish ingredient rows."""

    return tuple(
        dish.dish_ingredients.order_by("ingredient_id").values_list(
            "ingredient_id",
            "amount",
            "unit",
            "can_be_removed",
            "notes",
        )
    )


def _sync_reference_suggestions_locked(dish, actor=None):
    reference_allergens = {
        allergen.id: allergen
        for allergen in (
            Allergen.objects.filter(
                ingredients__dish_ingredients__dish=dish,
                ingredients__is_active=True,
            )
            .distinct()
        )
    }
    existing_ids = set(
        dish.allergen_links.values_list("allergen_id", flat=True)
    )

    created = []
    for allergen_id, allergen in reference_allergens.items():
        if allergen_id in existing_ids:
            continue

        link = DishAllergen.objects.create(
            dish=dish,
            allergen=allergen,
            relation_type=DishAllergen.RelationType.CONTAINS,
            source=DishAllergen.Source.RECIPE,
            verification_status=DishAllergen.VerificationStatus.SUGGESTED,
            notes="Предложено по справочным аллергенам ингредиентов рецепта.",
        )
        created.append(link)
        _create_event(
            dish=dish,
            allergen=allergen,
            action=DishAllergenReviewEvent.Action.SUGGESTED,
            relation_type=link.relation_type,
            actor=actor,
            notes=link.notes,
        )

    return created


@transaction.atomic
def sync_recipe_allergen_suggestions(dish_id, *, actor=None):
    dish = Dish.objects.select_for_update().get(pk=dish_id)
    created = _sync_reference_suggestions_locked(dish, actor=actor)

    if created and dish.allergen_review_status != Dish.AllergenReviewStatus.NEEDS_REVIEW:
        dish.allergen_review_status = Dish.AllergenReviewStatus.NEEDS_REVIEW
        dish.allergen_reviewed_revision = None
        dish.allergen_reviewed_by = None
        dish.allergen_reviewed_at = None
        dish.save(
            update_fields=[
                "allergen_review_status",
                "allergen_reviewed_revision",
                "allergen_reviewed_by",
                "allergen_reviewed_at",
                "updated_at",
            ]
        )

    return created


@transaction.atomic
def initialize_dish_allergen_review(dish_id, *, reason="", actor=None):
    """Initialize review state for a newly created dish without bumping revision."""

    dish = Dish.objects.select_for_update().get(pk=dish_id)
    created = _sync_reference_suggestions_locked(dish, actor=actor)
    has_suggestions = dish.allergen_links.filter(
        verification_status=DishAllergen.VerificationStatus.SUGGESTED
    ).exists()
    status = (
        Dish.AllergenReviewStatus.NEEDS_REVIEW
        if has_suggestions
        else Dish.AllergenReviewStatus.UNKNOWN
    )

    Dish.objects.filter(pk=dish.pk).update(
        allergen_review_status=status,
        allergen_reviewed_revision=None,
        allergen_reviewed_by=None,
        allergen_reviewed_at=None,
    )
    dish.allergen_review_status = status

    if reason:
        _create_event(
            dish=dish,
            action=DishAllergenReviewEvent.Action.REVIEW_REOPENED,
            actor=actor,
            notes=reason,
        )

    return created


@transaction.atomic
def invalidate_dish_allergen_review(dish_id, *, reason, actor=None):
    """Bump recipe revision and make all previous decisions non-public."""

    try:
        dish = Dish.objects.select_for_update().get(pk=dish_id)
    except Dish.DoesNotExist:
        return None

    previous_revision = dish.recipe_revision
    dish.recipe_revision = previous_revision + 1
    dish.allergen_review_status = Dish.AllergenReviewStatus.NEEDS_REVIEW
    dish.allergen_reviewed_revision = None
    dish.allergen_reviewed_by = None
    dish.allergen_reviewed_at = None
    dish.save(
        update_fields=[
            "recipe_revision",
            "allergen_review_status",
            "allergen_reviewed_revision",
            "allergen_reviewed_by",
            "allergen_reviewed_at",
            "updated_at",
        ]
    )

    dish.allergen_links.exclude(
        verification_status=DishAllergen.VerificationStatus.SUGGESTED
    ).update(
        verification_status=DishAllergen.VerificationStatus.SUGGESTED,
        reviewed_recipe_revision=None,
        reviewed_by=None,
        reviewed_at=None,
        updated_at=timezone.now(),
    )

    _create_event(
        dish=dish,
        action=DishAllergenReviewEvent.Action.INVALIDATED,
        actor=actor,
        notes=(
            f"Версия рецепта изменена с {previous_revision} на "
            f"{dish.recipe_revision}. {reason}"
        ).strip(),
    )
    _sync_reference_suggestions_locked(dish, actor=actor)
    return dish


def _status_after_link_decision(dish):
    if dish.allergen_links.filter(
        verification_status=DishAllergen.VerificationStatus.SUGGESTED
    ).exists():
        return Dish.AllergenReviewStatus.NEEDS_REVIEW

    if dish.allergen_links.filter(
        verification_status__in=[
            DishAllergen.VerificationStatus.VERIFIED,
            DishAllergen.VerificationStatus.REJECTED,
        ],
        reviewed_recipe_revision=dish.recipe_revision,
    ).exists():
        return Dish.AllergenReviewStatus.PARTIAL

    return Dish.AllergenReviewStatus.UNKNOWN


@transaction.atomic
def review_dish_allergen_link(
    link_id,
    *,
    decision,
    actor,
    relation_type=None,
    notes=None,
):
    if decision not in {
        DishAllergen.VerificationStatus.VERIFIED,
        DishAllergen.VerificationStatus.REJECTED,
    }:
        raise ValidationError("Допустимо только подтверждение или отклонение связи.")

    link = (
        DishAllergen.objects.select_for_update()
        .select_related("dish", "allergen")
        .get(pk=link_id)
    )
    dish = Dish.objects.select_for_update().get(pk=link.dish_id)
    now = timezone.now()

    if relation_type is not None:
        valid_relations = {value for value, _label in DishAllergen.RelationType.choices}
        if relation_type not in valid_relations:
            raise ValidationError("Неизвестный тип аллергенной связи.")
        link.relation_type = relation_type

    if notes is not None:
        link.notes = str(notes)[:255]

    link.verification_status = decision
    link.reviewed_recipe_revision = dish.recipe_revision
    link.reviewed_by = _actor_or_none(actor)
    link.reviewed_at = now
    link.save(
        update_fields=[
            "relation_type",
            "verification_status",
            "reviewed_recipe_revision",
            "reviewed_by",
            "reviewed_at",
            "notes",
            "updated_at",
        ]
    )

    dish.allergen_review_status = _status_after_link_decision(dish)
    dish.allergen_reviewed_revision = None
    dish.allergen_reviewed_by = None
    dish.allergen_reviewed_at = None
    dish.save(
        update_fields=[
            "allergen_review_status",
            "allergen_reviewed_revision",
            "allergen_reviewed_by",
            "allergen_reviewed_at",
            "updated_at",
        ]
    )

    action = (
        DishAllergenReviewEvent.Action.VERIFIED
        if decision == DishAllergen.VerificationStatus.VERIFIED
        else DishAllergenReviewEvent.Action.REJECTED
    )
    _create_event(
        dish=dish,
        allergen=link.allergen,
        action=action,
        relation_type=link.relation_type,
        actor=actor,
        notes=link.notes,
    )
    return link


@transaction.atomic
def complete_dish_allergen_review(dish_id, *, actor, notes=""):
    dish = Dish.objects.select_for_update().get(pk=dish_id)
    links = list(dish.allergen_links.select_for_update())

    unresolved = [
        link
        for link in links
        if link.verification_status == DishAllergen.VerificationStatus.SUGGESTED
    ]
    if unresolved:
        raise ValidationError(
            "Нельзя завершить проверку: остались неподтверждённые предложения."
        )

    stale = [
        link
        for link in links
        if link.verification_status
        in {
            DishAllergen.VerificationStatus.VERIFIED,
            DishAllergen.VerificationStatus.REJECTED,
        }
        and link.reviewed_recipe_revision != dish.recipe_revision
    ]
    if stale:
        raise ValidationError(
            "Нельзя завершить проверку: часть решений относится к старой версии рецепта."
        )

    now = timezone.now()
    dish.allergen_review_status = Dish.AllergenReviewStatus.COMPLETE
    dish.allergen_reviewed_revision = dish.recipe_revision
    dish.allergen_reviewed_by = _actor_or_none(actor)
    dish.allergen_reviewed_at = now
    dish.allergen_review_notes = str(notes or "")[:500]
    dish.save(
        update_fields=[
            "allergen_review_status",
            "allergen_reviewed_revision",
            "allergen_reviewed_by",
            "allergen_reviewed_at",
            "allergen_review_notes",
            "updated_at",
        ]
    )
    _create_event(
        dish=dish,
        action=DishAllergenReviewEvent.Action.REVIEW_COMPLETED,
        actor=actor,
        notes=dish.allergen_review_notes,
    )
    return dish


@transaction.atomic
def reopen_dish_allergen_review(dish_id, *, actor, reason=""):
    dish = Dish.objects.select_for_update().get(pk=dish_id)
    dish.allergen_review_status = Dish.AllergenReviewStatus.NEEDS_REVIEW
    dish.allergen_reviewed_revision = None
    dish.allergen_reviewed_by = None
    dish.allergen_reviewed_at = None
    dish.allergen_review_notes = str(reason or "")[:500]
    dish.save(
        update_fields=[
            "allergen_review_status",
            "allergen_reviewed_revision",
            "allergen_reviewed_by",
            "allergen_reviewed_at",
            "allergen_review_notes",
            "updated_at",
        ]
    )
    _create_event(
        dish=dish,
        action=DishAllergenReviewEvent.Action.REVIEW_REOPENED,
        actor=actor,
        notes=dish.allergen_review_notes,
    )
    return dish

@transaction.atomic
def reopen_dish_allergen_link(link_id, *, actor, reason=""):
    link = (
        DishAllergen.objects.select_for_update()
        .select_related("dish", "allergen")
        .get(pk=link_id)
    )
    dish = Dish.objects.select_for_update().get(pk=link.dish_id)
    link.verification_status = DishAllergen.VerificationStatus.SUGGESTED
    link.reviewed_recipe_revision = None
    link.reviewed_by = None
    link.reviewed_at = None
    if reason:
        link.notes = str(reason)[:255]
    link.save(
        update_fields=[
            "verification_status",
            "reviewed_recipe_revision",
            "reviewed_by",
            "reviewed_at",
            "notes",
            "updated_at",
        ]
    )
    dish.allergen_review_status = Dish.AllergenReviewStatus.NEEDS_REVIEW
    dish.allergen_reviewed_revision = None
    dish.allergen_reviewed_by = None
    dish.allergen_reviewed_at = None
    dish.save(
        update_fields=[
            "allergen_review_status",
            "allergen_reviewed_revision",
            "allergen_reviewed_by",
            "allergen_reviewed_at",
            "updated_at",
        ]
    )
    _create_event(
        dish=dish,
        allergen=link.allergen,
        action=DishAllergenReviewEvent.Action.REVIEW_REOPENED,
        relation_type=link.relation_type,
        actor=actor,
        notes=link.notes or "Связь возвращена на повторную проверку.",
    )
    return link
