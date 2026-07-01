from django.contrib import admin, messages

from .models import (
    Order,
    OrderItem,
    OrderItemModifier,
    OrderStatusHistory,
    Payment,
    Restaurant,
    Table,
)
from .statuses import OrderTransitionError, transition_order


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "address")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("restaurant", "number", "title", "seats", "is_active")
    list_filter = ("restaurant", "is_active")
    search_fields = ("number", "title", "restaurant__name")


class OrderItemModifierInline(admin.TabularInline):
    model = OrderItemModifier
    extra = 0
    readonly_fields = ("type", "dish_ingredient", "name", "price_delta")
    can_delete = False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("dish", "dish_name", "quantity", "unit_price", "line_total")
    can_delete = False
    show_change_link = True


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("method", "status", "amount", "currency", "provider", "external_id", "created_at", "paid_at")
    can_delete = False


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    readonly_fields = (
        "from_status",
        "to_status",
        "changed_by",
        "reason",
        "order_version",
        "created_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "restaurant", "table", "status", "version", "total_amount", "created_at")
    list_filter = ("status", "restaurant", "created_at")
    search_fields = ("id", "comment", "user__email", "session_key")
    readonly_fields = (
        "status",
        "version",
        "restaurant",
        "table",
        "user",
        "session_key",
        "guests_count",
        "comment",
        "currency",
        "subtotal_amount",
        "total_amount",
        "created_at",
        "updated_at",
        "confirmed_at",
        "completed_at",
    )
    inlines = (OrderItemInline, PaymentInline, OrderStatusHistoryInline)
    actions = (
        "mark_confirmed",
        "mark_cooking",
        "mark_ready",
        "mark_served",
        "mark_completed",
        "mark_canceled",
    )

    def _transition_queryset(self, request, queryset, next_status):
        transitioned = 0

        for order in queryset:
            try:
                transition_order(
                    order,
                    next_status,
                    actor=request.user,
                    reason="Django admin action",
                )
            except OrderTransitionError as error:
                self.message_user(request, str(error), level=messages.ERROR)
            else:
                transitioned += 1

        if transitioned:
            self.message_user(
                request,
                f"Updated {transitioned} order(s).",
                level=messages.SUCCESS,
            )

    @admin.action(description="Перевести в Подтвержден")
    def mark_confirmed(self, request, queryset):
        self._transition_queryset(request, queryset, Order.Status.CONFIRMED)

    @admin.action(description="Перевести в Готовится")
    def mark_cooking(self, request, queryset):
        self._transition_queryset(request, queryset, Order.Status.COOKING)

    @admin.action(description="Перевести в Готов")
    def mark_ready(self, request, queryset):
        self._transition_queryset(request, queryset, Order.Status.READY)

    @admin.action(description="Перевести в Подан")
    def mark_served(self, request, queryset):
        self._transition_queryset(request, queryset, Order.Status.SERVED)

    @admin.action(description="Перевести в Завершен")
    def mark_completed(self, request, queryset):
        self._transition_queryset(request, queryset, Order.Status.COMPLETED)

    @admin.action(description="Отменить")
    def mark_canceled(self, request, queryset):
        self._transition_queryset(request, queryset, Order.Status.CANCELED)


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "dish_name", "quantity", "unit_price", "line_total")
    search_fields = ("dish_name", "order__id")
    inlines = (OrderItemModifierInline,)


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("order", "from_status", "to_status", "changed_by", "order_version", "created_at")
    list_filter = ("from_status", "to_status", "created_at")
    search_fields = ("order__id", "reason", "changed_by__email")
    readonly_fields = (
        "order",
        "from_status",
        "to_status",
        "changed_by",
        "reason",
        "order_version",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "method", "status", "amount", "currency", "created_at")
    list_filter = ("method", "status", "currency")
