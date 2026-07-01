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
        "dishes/<int:dish_id>/hide/",
        views.hide_dish,
        name="hide_dish",
    ),
]
