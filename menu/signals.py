from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from .allergen_review import (
    invalidate_dish_allergen_review,
    recipe_review_signals_suppressed,
)
from .models import DishIngredient, Ingredient


_RECIPE_FIELDS = (
    "dish_id",
    "ingredient_id",
    "amount",
    "unit",
    "can_be_removed",
    "notes",
)


@receiver(pre_save, sender=DishIngredient)
def remember_dish_ingredient_change(sender, instance, raw=False, **kwargs):
    if raw or recipe_review_signals_suppressed():
        instance._recipe_review_changed = False
        return

    if not instance.pk:
        instance._recipe_review_changed = True
        return

    previous = sender.objects.filter(pk=instance.pk).values(*_RECIPE_FIELDS).first()
    if previous is None:
        instance._recipe_review_changed = True
        return

    instance._recipe_review_changed = any(
        previous[field] != getattr(instance, field)
        for field in _RECIPE_FIELDS
    )
    instance._recipe_review_previous_dish_id = previous["dish_id"]


@receiver(post_save, sender=DishIngredient)
def invalidate_review_after_ingredient_save(
    sender,
    instance,
    created=False,
    raw=False,
    **kwargs,
):
    if raw or recipe_review_signals_suppressed():
        return

    if created or getattr(instance, "_recipe_review_changed", False):
        previous_dish_id = getattr(
            instance,
            "_recipe_review_previous_dish_id",
            None,
        )
        if previous_dish_id and previous_dish_id != instance.dish_id:
            invalidate_dish_allergen_review(
                previous_dish_id,
                reason="Ингредиент перенесён в другое блюдо.",
            )

        invalidate_dish_allergen_review(
            instance.dish_id,
            reason="Изменён состав или параметры ингредиента блюда.",
        )


@receiver(post_delete, sender=DishIngredient)
def invalidate_review_after_ingredient_delete(sender, instance, **kwargs):
    if recipe_review_signals_suppressed():
        return

    invalidate_dish_allergen_review(
        instance.dish_id,
        reason="Ингредиент удалён из рецепта блюда.",
    )


@receiver(m2m_changed, sender=Ingredient.allergens.through)
def invalidate_review_after_reference_allergen_change(
    sender,
    instance,
    action,
    reverse,
    pk_set,
    **kwargs,
):
    if recipe_review_signals_suppressed():
        return

    if action in {"pre_remove", "pre_clear"}:
        if reverse:
            ingredient_ids = (
                set(pk_set)
                if pk_set is not None
                else set(
                    instance.ingredients.values_list("id", flat=True)
                )
            )
            dish_ids = set(
                DishIngredient.objects.filter(
                    ingredient_id__in=ingredient_ids
                ).values_list("dish_id", flat=True)
            )
        else:
            dish_ids = set(
                instance.dish_ingredients.values_list("dish_id", flat=True)
            )
        instance._recipe_review_affected_dish_ids = dish_ids
        return

    if action not in {"post_add", "post_remove", "post_clear"}:
        return

    cached_ids = getattr(instance, "_recipe_review_affected_dish_ids", set())
    if reverse:
        if pk_set:
            current_ids = set(
                DishIngredient.objects.filter(
                    ingredient_id__in=pk_set
                ).values_list("dish_id", flat=True)
            )
        else:
            current_ids = set()
    else:
        current_ids = set(
            instance.dish_ingredients.values_list("dish_id", flat=True)
        )

    dish_ids = cached_ids | current_ids
    if hasattr(instance, "_recipe_review_affected_dish_ids"):
        del instance._recipe_review_affected_dish_ids

    for dish_id in dish_ids:
        invalidate_dish_allergen_review(
            dish_id,
            reason="Изменены справочные аллергены ингредиента рецепта.",
        )

