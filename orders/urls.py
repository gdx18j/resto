from django.urls import path

from . import views


app_name = "orders"


urlpatterns = [
    path("quote/", views.quote, name="quote"),
    path("create/", views.create, name="create"),
    path("history/", views.history, name="history"),
    path("<int:order_id>/success/", views.success, name="success"),
]
