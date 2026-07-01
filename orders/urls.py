from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("create/", views.create_order, name="create"),
    path("<int:order_id>/success/", views.order_success, name="success"),
    path("history/", views.order_history, name="history"),
]
