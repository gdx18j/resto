from django.urls import path

from . import views


app_name = "ai_assistant"


urlpatterns = [
    path(
        "history/",
        views.history,
        name="history",
    ),
    path(
        "history/export/",
        views.export_history,
        name="export_history",
    ),
    path(
        "history/delete/",
        views.delete_history,
        name="delete_history",
    ),
    path(
        "ask/",
        views.ask,
        name="ask",
    ),
]
