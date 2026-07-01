import base64
import io

from django.conf import settings
from django.contrib import admin
from django.utils.html import format_html

from .models import Table

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ["number", "seats", "is_active", "qr_token", "qr_thumb"]
    list_filter = ["is_active"]
    search_fields = ["number", "qr_token"]
    readonly_fields = ["qr_token", "qr_preview", "qr_link"]
    fields = ["number", "seats", "is_active", "qr_token", "qr_link", "qr_preview"]

    def _full_url(self, obj):
        site_url = getattr(settings, "SITE_URL", "http://localhost:8000")
        return f"{site_url.rstrip('/')}{obj.menu_url_path()}"

    def qr_link(self, obj):
        if not obj.pk:
            return "—"
        url = self._full_url(obj)
        return format_html('<a href="{0}" target="_blank">{0}</a>', url)
    qr_link.short_description = "Ссылка для QR"

    def _qr_base64(self, obj, box_size=6):
        if not QRCODE_AVAILABLE or not obj.pk:
            return None
        img = qrcode.make(self._full_url(obj), box_size=box_size, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def qr_thumb(self, obj):
        b64 = self._qr_base64(obj, box_size=3)
        if not b64:
            return "—"
        return format_html(
            '<img src="data:image/png;base64,{}" width="60" height="60"/>', b64
        )
    qr_thumb.short_description = "QR"

    def qr_preview(self, obj):
        if not obj.pk:
            return "Сохраните стол, чтобы увидеть QR-код."
        if not QRCODE_AVAILABLE:
            return "Установите пакет qrcode: pip install qrcode[pil]"
        b64 = self._qr_base64(obj, box_size=8)
        return format_html(
            '<div style="margin-top:8px">'
            '<img src="data:image/png;base64,{}" width="220" height="220"/>'
            '<p style="margin-top:6px;color:#888;font-size:12px">'
            "Распечатайте и положите на стол. Сканирование откроет меню "
            "и автоматически привяжет заказ к этому столу."
            "</p></div>",
            b64,
        )
    qr_preview.short_description = "QR-код для печати"
