from django.urls import path

from . import views


app_name = "ai_assistant"


urlpatterns = [
    path(
        "ask/",
        views.ask,
        name="ask",
    ),
]
