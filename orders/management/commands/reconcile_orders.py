from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from orders.models import Order


class Command(BaseCommand):
    help = "Find order, line-item, and payment money mismatches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-mismatch",
            action="store_true",
            help="Exit with an error when any mismatch is found.",
        )

    def handle(self, *args, **options):
        mismatches = []
        orders = Order.objects.prefetch_related("items", "payments").order_by("id")

        for order in orders:
            item_sum = Decimal("0.00")

            for item in order.items.all():
                expected_line_total = item.unit_price * item.quantity
                item_sum += item.line_total

                if item.line_total != expected_line_total:
                    mismatches.append(
                        (
                            order.id,
                            f"item {item.id} line_total={item.line_total} "
                            f"expected={expected_line_total}"
                        )
                    )

            if order.subtotal_amount != item_sum:
                mismatches.append(
                    (
                        order.id,
                        f"subtotal={order.subtotal_amount} expected={item_sum}",
                    )
                )

            if order.total_amount != order.subtotal_amount:
                mismatches.append(
                    (
                        order.id,
                        f"total={order.total_amount} expected={order.subtotal_amount}",
                    )
                )

            for payment in order.payments.all():
                if payment.amount != order.total_amount:
                    mismatches.append(
                        (
                            order.id,
                            f"payment {payment.id} amount={payment.amount} "
                            f"expected={order.total_amount}",
                        )
                    )

                if payment.currency != order.currency:
                    mismatches.append(
                        (
                            order.id,
                            f"payment {payment.id} currency={payment.currency} "
                            f"expected={order.currency}",
                        )
                    )

        if not mismatches:
            self.stdout.write(self.style.SUCCESS("No order money mismatches found."))
            return

        for order_id, message in mismatches:
            self.stdout.write(f"order={order_id}: {message}")

        summary = f"Found {len(mismatches)} order money mismatch(es)."
        if options["fail_on_mismatch"]:
            raise CommandError(summary)

        self.stdout.write(self.style.WARNING(summary))
