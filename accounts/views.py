from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from ai_assistant.models import AIUsageEvent, ChatSession
from ai_assistant.privacy import (
    get_ai_history_retention_days,
    prune_expired_ai_history,
)
from menu.translations import localized_allergen_html
from orders.models import Order
from orders.presentation import decorate_orders

from .forms import AllergyPreferencesForm
from .models import UserAllergy


def _serialize_timestamp(value):
    return timezone.localtime(value).isoformat()


def _serialize_ai_session(session):
    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": _serialize_timestamp(session.created_at),
        "updated_at": _serialize_timestamp(session.updated_at),
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "text": message.content,
                "model": message.model_name,
                "created_at": _serialize_timestamp(message.created_at),
            }
            for message in session.messages.order_by("created_at", "id")
        ],
    }


def _serialize_ai_usage_event(event):
    return {
        "id": event.id,
        "status": event.status,
        "model": event.model_name,
        "limit_reason": event.limit_reason,
        "is_stream": event.is_stream,
        "prompt_chars": event.prompt_chars,
        "response_chars": event.response_chars,
        "estimated_prompt_tokens": event.estimated_prompt_tokens,
        "estimated_response_tokens": event.estimated_response_tokens,
        "estimated_total_tokens": event.estimated_total_tokens,
        "estimated_cost_micros": event.estimated_cost_micros,
        "created_at": _serialize_timestamp(event.created_at),
    }


@login_required
def profile(request):
    prune_expired_ai_history(user=request.user)

    allergy_records = (
        request.user.allergy_records
        .filter(status=UserAllergy.Status.CONFIRMED)
        .select_related("allergen")
        .order_by("allergen__name")
    )
    allergy_records = list(allergy_records)

    for record in allergy_records:
        record.allergen.localized_name_html = localized_allergen_html(
            record.allergen
        )

    recent_orders = list(
        Order.objects.filter(user=request.user)
        .select_related("table")
        .prefetch_related("items__dish", "payments")
        .order_by("-created_at")[:2]
    )

    context = {
        "allergy_records": allergy_records,
        "recent_orders": decorate_orders(recent_orders),
        "ai_chat_count": request.user.ai_chat_sessions.count(),
        "ai_history_retention_days": get_ai_history_retention_days(),
    }

    return render(
        request,
        "accounts/profile.html",
        context,
    )


@login_required
def export_data(request):
    prune_expired_ai_history(user=request.user)

    allergy_records = (
        request.user.allergy_records
        .select_related("allergen")
        .order_by("allergen__name")
    )
    ai_sessions = (
        ChatSession.objects.filter(user=request.user)
        .prefetch_related("messages")
        .order_by("created_at", "id")
    )
    ai_usage_events = AIUsageEvent.objects.filter(user=request.user).order_by(
        "created_at",
        "id",
    )
    payload = {
        "exported_at": _serialize_timestamp(timezone.now()),
        "account": {
            "email": request.user.email,
            "date_joined": _serialize_timestamp(request.user.date_joined),
            "share_allergies_with_ai": request.user.share_allergies_with_ai,
        },
        "allergy_profile": [
            {
                "allergen": record.allergen.name,
                "allergen_code": record.allergen.code,
                "status": record.status,
                "source": record.source,
                "created_at": _serialize_timestamp(record.created_at),
                "updated_at": _serialize_timestamp(record.updated_at),
            }
            for record in allergy_records
        ],
        "ai_history": {
            "provider": "Gemini",
            "retention_days": get_ai_history_retention_days(),
            "sessions": [
                _serialize_ai_session(session)
                for session in ai_sessions
            ],
            "usage_events": [
                _serialize_ai_usage_event(event)
                for event in ai_usage_events
            ],
        },
    }
    response = JsonResponse(
        payload,
        json_dumps_params={
            "ensure_ascii": False,
            "indent": 2,
        },
    )
    response["Content-Disposition"] = 'attachment; filename="caesar-account-data.json"'
    return response


@login_required
def edit_allergies(request):
    confirmed_records = UserAllergy.objects.filter(
        user=request.user,
        status=UserAllergy.Status.CONFIRMED,
    )
    current_allergen_ids = confirmed_records.values_list(
        "allergen_id",
        flat=True,
    )

    if request.method == "POST":
        form = AllergyPreferencesForm(request.POST)

        if form.is_valid():
            selected_allergens = form.cleaned_data["allergens"]
            request.user.share_allergies_with_ai = form.cleaned_data[
                "share_allergies_with_ai"
            ]
            request.user.save(update_fields=["share_allergies_with_ai"])
            selected_ids = set(
                selected_allergens.values_list("id", flat=True)
            )

            if selected_ids:
                confirmed_records.exclude(
                    allergen_id__in=selected_ids
                ).delete()
            else:
                confirmed_records.delete()

            for allergen in selected_allergens:
                UserAllergy.objects.update_or_create(
                    user=request.user,
                    allergen=allergen,
                    defaults={
                        "source": UserAllergy.Source.MANUAL,
                        "status": UserAllergy.Status.CONFIRMED,
                    },
                )

            messages.success(
                request,
                "Пищевые ограничения сохранены.",
            )

            return redirect("accounts:profile")

    else:
        form = AllergyPreferencesForm(
            initial={
                "allergens": current_allergen_ids,
                "share_allergies_with_ai": request.user.share_allergies_with_ai,
            }
        )

    context = {
        "form": form,
    }

    return render(
        request,
        "accounts/edit_allergies.html",
        context,
    )
