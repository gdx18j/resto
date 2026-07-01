from django.contrib import admin

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["dish_name", "price", "qty"]
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "table", "status", "total", "payment_method", "created_at", "paid_at"]
    list_filter = ["status", "payment_method", "created_at"]
    search_fields = ["id", "table__number", "yookassa_payment_id"]
    readonly_fields = ["created_at", "paid_at", "yookassa_payment_id"]
    inlines = [OrderItemInline]
