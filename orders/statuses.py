from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Order, OrderStatusHistory


class OrderTransitionError(ValueError):
    pass


class OrderVersionConflict(OrderTransitionError):
    pass


def _changed_by(actor):
    if actor is not None and getattr(actor, "is_authenticated", False):
        return actor

    return None


def transition_order(order_or_id, next_status, *, expected_version=None, actor=None, reason=""):
    order_id = order_or_id.pk if isinstance(order_or_id, Order) else order_or_id

    with transaction.atomic():
        order = Order.objects.get(pk=order_id)

        if expected_version is not None and order.version != expected_version:
            raise OrderVersionConflict(
                f"Order #{order.id} version conflict: expected {expected_version}, got {order.version}."
            )

        if not order.can_transition_to(next_status):
            raise OrderTransitionError(
                f"Cannot transition order #{order.id} from {order.status} to {next_status}."
            )

        previous_status = order.status
        next_version = order.version + 1
        now = timezone.now()
        updates = {
            "status": next_status,
            "version": F("version") + 1,
            "updated_at": now,
        }

        if next_status == Order.Status.CONFIRMED and not order.confirmed_at:
            updates["confirmed_at"] = now
        if next_status == Order.Status.COMPLETED and not order.completed_at:
            updates["completed_at"] = now

        updated_rows = (
            Order.objects.filter(pk=order.pk, version=order.version)
            .transition_update(**updates)
        )

        if updated_rows != 1:
            raise OrderVersionConflict(f"Order #{order.id} was changed concurrently.")

        OrderStatusHistory.objects.create(
            order=order,
            from_status=previous_status,
            to_status=next_status,
            changed_by=_changed_by(actor),
            reason=str(reason or "").strip()[:255],
            order_version=next_version,
        )

        order.status = next_status
        order.version = next_version
        order.updated_at = now

        if "confirmed_at" in updates:
            order.confirmed_at = now
        if "completed_at" in updates:
            order.completed_at = now

        return order
