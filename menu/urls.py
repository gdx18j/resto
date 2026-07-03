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
        views.table_menu_entry,
        name="table_menu",
    ),
    path(
        "table/<str:table_context>/",
        views.dish_list,
        name="table_context_menu",
    ),
    path(
        "api/restaurants/<slug:restaurant_slug>/dishes/<int:dish_id>/",
        views.dish_detail,
        name="dish_detail",
    ),
]
