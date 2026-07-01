from django.urls import path

from . import views


app_name = "orders"


urlpatterns = [
    path("quote/", views.quote, name="quote"),
    path("create/", views.create, name="create"),
]
