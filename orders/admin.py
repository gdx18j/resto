import base64
import io

from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from .models import (
    Order,
    OrderItem,
    OrderItemModifier,
    OrderStatusHistory,
    Payment,
    Restaurant,
    Table,
    TableQrTokenAudit,
)
from .statuses import OrderTransitionError, transition_order

try:
    import qrcode

    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "address")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = (
        "restaurant",
        "number",
        "title",
        "seats",
        "is_active",
        "qr_token_version",
        "qr_token_kind",
        "qr_token_status",
        "qr_thumb",
    )
    list_filter = ("restaurant", "is_active")
    search_fields = ("number", "title", "qr_token_hash", "restaurant__name")
    readonly_fields = (
        "qr_token_hash_short",
        "qr_token_version",
        "qr_token_kind",
        "qr_token_status",
        "qr_token_created_at",
        "qr_token_rotated_at",
        "qr_token_revoked_at",
        "qr_token_expires_at",
        "qr_link",
        "qr_preview",
        "created_at",
    )
    fields = (
        "restaurant",
        "number",
        "title",
        "seats",
        "is_active",
        "qr_token_hash_short",
        "qr_token_version",
        "qr_token_kind",
        "qr_token_status",
        "qr_token_created_at",
        "qr_token_rotated_at",
        "qr_token_revoked_at",
        "qr_token_expires_at",
        "qr_link",
        "qr_preview",
        "created_at",
    )
    actions = ("rotate_qr_tokens", "revoke_qr_tokens")
    inlines = ()

    def _full_url(self, obj, token=None):
        site_url = getattr(settings, "SITE_URL", "http://localhost:8000")
        token = token or obj.plain_qr_token

        if not token:
            return ""

        return f"{site_url.rstrip('/')}{obj.menu_url_path(token)}"

    def qr_token_hash_short(self, obj):
        if not obj.qr_token_hash:
            return "—"

        return f"{obj.qr_token_hash[:16]}…"

    qr_token_hash_short.short_description = "Hash QR"

    def qr_token_status(self, obj):
        if not obj.qr_token_hash:
            return "Нет токена"
        if obj.qr_token_revoked_at:
            return "Отозван"
        if obj.qr_token_expires_at and obj.qr_token_expires_at <= timezone.now():
            return "Истёк"
        if not obj.is_active:
            return "Стол неактивен"

        return "Активен"

    qr_token_status.short_description = "Статус QR"

    def qr_link(self, obj):
        if not obj.pk:
            return "—"

        url = self._full_url(obj)
        if not url:
            return "Plaintext QR-токен не хранится. Перевыпустите QR, чтобы получить новую ссылку для печати."

        return format_html('<a href="{0}" target="_blank" rel="noopener">{0}</a>', url)

    qr_link.short_description = "Ссылка для QR"

    def _qr_base64(self, obj, box_size=6):
        if not QRCODE_AVAILABLE or not obj.pk:
            return None

        url = self._full_url(obj)

        if not url:
            return None

        image = qrcode.make(url, box_size=box_size, border=2)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def qr_thumb(self, obj):
        b64 = self._qr_base64(obj, box_size=3)
        if not b64:
            return "—"

        return format_html(
            '<img src="data:image/png;base64,{}" width="60" height="60" alt="QR">',
            b64,
        )

    qr_thumb.short_description = "QR"

    def qr_preview(self, obj):
        if not obj.pk:
            return "Сохраните стол, чтобы увидеть QR-код."
        if not QRCODE_AVAILABLE:
            return "Установите пакет qrcode[pil]."

        b64 = self._qr_base64(obj, box_size=8)
        if not b64:
            return "Plaintext QR-токен не хранится. Используйте действие «Перевыпустить QR» и распечатайте новую ссылку сразу."

        return format_html(
            '<div style="margin-top:8px">'
            '<img src="data:image/png;base64,{}" width="220" height="220" alt="QR">'
            '<p style="margin-top:6px;color:#777;font-size:12px">'
            "Сканирование откроет меню и привяжет заказ к этому столу."
            "</p></div>",
            b64,
        )

    qr_preview.short_description = "QR-код для печати"

    def _show_plain_qr_token_message(self, request, obj, verb):
        url = self._full_url(obj)

        if not url:
            return

        self.message_user(
            request,
            format_html(
                "{}. Ссылка доступна только сейчас: <a href=\"{}\" target=\"_blank\" rel=\"noopener\">{}</a>",
                verb,
                url,
                url,
            ),
            level=messages.WARNING,
        )

    def response_add(self, request, obj, post_url_continue=None):
        response = super().response_add(request, obj, post_url_continue=post_url_continue)
        self._show_plain_qr_token_message(request, obj, "QR-токен выпущен")
        return response

    def response_change(self, request, obj):
        response = super().response_change(request, obj)
        self._show_plain_qr_token_message(request, obj, "QR-токен выпущен")
        return response

    @admin.action(description="Перевыпустить QR")
    def rotate_qr_tokens(self, request, queryset):
        links = []

        for table in queryset.select_related("restaurant"):
            token = table.rotate_qr_token(
                actor=request.user,
                reason="Django admin action",
            )
            url = self._full_url(table, token)
            links.append((str(table), url, url))

        if not links:
            return

        self.message_user(
            request,
            format_html(
                "QR перевыпущен. Plaintext-ссылки доступны только сейчас:<br>{}",
                format_html_join(
                    "<br>",
                    "{}: <a href=\"{}\" target=\"_blank\" rel=\"noopener\">{}</a>",
                    links,
                ),
            ),
            level=messages.WARNING,
        )

    @admin.action(description="Отозвать QR")
    def revoke_qr_tokens(self, request, queryset):
        count = 0

        for table in queryset:
            if not table.qr_token_revoked_at:
                table.revoke_qr_token(
                    actor=request.user,
                    reason="Django admin action",
                )
                count += 1

        if count:
            self.message_user(request, f"Отозвано QR-токенов: {count}.", level=messages.SUCCESS)


class TableQrTokenAuditInline(admin.TabularInline):
    model = TableQrTokenAudit
    extra = 0
    readonly_fields = (
        "action",
        "token_version",
        "token_kind",
        "token_hash_short",
        "actor",
        "reason",
        "created_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def token_hash_short(self, obj):
        if not obj.token_hash:
            return "—"

        return f"{obj.token_hash[:16]}…"

    token_hash_short.short_description = "Hash QR"


TableAdmin.inlines = (TableQrTokenAuditInline,)


class OrderItemModifierInline(admin.TabularInline):
    model = OrderItemModifier
    extra = 0
    readonly_fields = ("type", "dish_ingredient", "name", "price_delta")
    can_delete = False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = (
        "dish",
        "dish_name",
        "dish_code_snapshot",
        "category_name_snapshot",
        "category_code_snapshot",
        "quantity",
        "unit_price",
        "line_total",
    )
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
    list_display = (
        "id",
        "restaurant",
        "order_mode",
        "table",
        "status",
        "version",
        "total_amount",
        "created_at",
    )
    list_filter = ("order_mode", "status", "restaurant", "created_at")
    search_fields = ("id", "comment", "user__email", "session_key")
    readonly_fields = (
        "status",
        "version",
        "restaurant",
        "table",
        "order_mode",
        "restaurant_name_snapshot",
        "restaurant_slug_snapshot",
        "table_number_snapshot",
        "table_title_snapshot",
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
    list_display = (
        "order",
        "dish_name",
        "category_name_snapshot",
        "quantity",
        "unit_price",
        "line_total",
    )
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


@admin.register(TableQrTokenAudit)
class TableQrTokenAuditAdmin(admin.ModelAdmin):
    list_display = ("table", "action", "token_version", "token_kind", "token_hash_short", "actor", "created_at")
    list_filter = ("action", "token_kind", "created_at")
    search_fields = ("table__number", "table__restaurant__name", "token_hash", "reason", "actor__email")
    readonly_fields = (
        "table",
        "action",
        "token_version",
        "token_kind",
        "token_hash",
        "actor",
        "reason",
        "created_at",
    )

    def token_hash_short(self, obj):
        if not obj.token_hash:
            return "—"

        return f"{obj.token_hash[:16]}…"

    token_hash_short.short_description = "Hash QR"

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
