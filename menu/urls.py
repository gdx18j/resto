from django.urls import path

from . import views


app_name = "menu"


urlpatterns = [
    path(
        "",
        views.dish_list,
        name="dish_list",
    ),
    path(
        "t/<str:qr_token>/",
        views.dish_list,
        name="table_menu",
    ),
]
