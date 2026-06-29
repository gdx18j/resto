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
        "ask/",
        views.ask,
        name="ask",
    ),
]
