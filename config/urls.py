from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

from .health import health_live, health_ready



urlpatterns = [
    path("health/live/", health_live, name="health_live"),
    path("health/ready/", health_ready, name="health_ready"),
    path("healthz/", health_live, name="healthz"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("menu.urls")),
    path("account/", include("accounts.urls")),
    path("ai/", include("ai_assistant.urls")),
    path("orders/", include("orders.urls")),
]


if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
