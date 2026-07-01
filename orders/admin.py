from django.contrib import admin

from .models import (
    Order,
    OrderItem,
    OrderItemModifier,
    Payment,
    Restaurant,
    Table,
)


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


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "restaurant", "table", "status", "total_amount", "created_at")
    list_filter = ("status", "restaurant", "created_at")
    search_fields = ("id", "comment", "user__email", "session_key")
    readonly_fields = (
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
    inlines = (OrderItemInline, PaymentInline)


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "dish_name", "quantity", "unit_price", "line_total")
    search_fields = ("dish_name", "order__id")
    inlines = (OrderItemModifierInline,)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "method", "status", "amount", "currency", "created_at")
    list_filter = ("method", "status", "currency")
