from django.contrib import admin

from .models import AIUsageEvent, ChatMessage, ChatSession


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
        "created_at",
    )

    readonly_fields = (
        "role",
        "content",
        "model_name",
        "created_at",
    )

    can_delete = False
    show_change_link = True


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "title",
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
        "created_at",
    )

    @admin.display(description="Сообщение")
    def short_content(self, obj):
        return obj.content[:80]


@admin.register(AIUsageEvent)
class AIUsageEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "user",
        "actor_kind",
        "model_name",
        "estimated_total_tokens",
        "estimated_cost_micros",
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
        "model_name",
        "status",
        "limit_reason",
        "is_stream",
        "created_at",
        "updated_at",
    )
