from django.contrib import admin

from .models import AIRequestRecord, AIUsageEvent, ChatMessage, ChatSession


class ChatMessageInline(admin.TabularInline):
    """
    Показывает сообщения прямо внутри страницы диалога.
    """

    model = ChatMessage
    extra = 0

    fields = (
        "role",
        "content",
        "model_name",
        "recommended_dish_ids",
        "created_at",
    )

    readonly_fields = (
        "role",
        "content",
        "model_name",
        "recommended_dish_ids",
        "created_at",
    )

    can_delete = False
    show_change_link = True


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "restaurant",
        "title",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "restaurant",
        "created_at",
        "updated_at",
    )

    search_fields = (
        "title",
        "user__email",
        "session_key",
    )

    readonly_fields = (
        "id",
        "session_key",
        "created_at",
        "updated_at",
    )

    inlines = (
        ChatMessageInline,
    )

    @admin.display(description="Владелец")
    def owner(self, obj):
        return obj.user or "Гость"


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "session",
        "role",
        "short_content",
        "model_name",
        "recommended_dish_ids",
        "created_at",
    )

    list_filter = (
        "role",
        "model_name",
        "created_at",
    )

    search_fields = (
        "content",
        "session__title",
        "session__user__email",
    )

    readonly_fields = (
        "recommended_dish_ids",
        "created_at",
    )

    @admin.display(description="Сообщение")
    def short_content(self, obj):
        return obj.content[:80]


@admin.register(AIRequestRecord)
class AIRequestRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "restaurant",
        "user",
        "chat_session",
        "is_stream",
        "created_at",
        "completed_at",
    )
    list_filter = (
        "status",
        "restaurant",
        "is_stream",
        "created_at",
    )
    search_fields = (
        "id",
        "user__email",
        "session_key",
        "request_fingerprint",
        "error_code",
    )
    readonly_fields = (
        "id",
        "user",
        "session_key",
        "restaurant",
        "chat_session",
        "user_message",
        "assistant_message",
        "request_fingerprint",
        "status",
        "error_code",
        "is_stream",
        "created_at",
        "updated_at",
        "completed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIUsageEvent)
class AIUsageEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "user",
        "actor_kind",
        "model_name",
        "estimated_total_tokens",
        "actual_total_tokens",
        "actual_cost_micros",
        "is_stream",
        "created_at",
    )

    list_filter = (
        "status",
        "actor_kind",
        "is_stream",
        "model_name",
        "created_at",
    )

    search_fields = (
        "user__email",
        "session_key",
        "ip_address_hash",
        "limit_reason",
    )

    readonly_fields = (
        "user",
        "chat_session",
        "session_key",
        "actor_kind",
        "ip_address_hash",
        "prompt_chars",
        "response_chars",
        "estimated_prompt_tokens",
        "estimated_response_tokens",
        "estimated_total_tokens",
        "estimated_cost_micros",
        "actual_prompt_tokens",
        "actual_response_tokens",
        "actual_total_tokens",
        "actual_cost_micros",
        "provider_response_id",
        "request_record",
        "model_name",
        "status",
        "limit_reason",
        "is_stream",
        "created_at",
        "updated_at",
    )
