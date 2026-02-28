from django.contrib import admin

from aifw.models import AIActionType, AIUsageLog, LLMModel, LLMProvider


@admin.register(LLMProvider)
class LLMProviderAdmin(admin.ModelAdmin):
    list_display = ["name", "display_name", "is_active"]
    list_filter = ["is_active"]


@admin.register(LLMModel)
class LLMModelAdmin(admin.ModelAdmin):
    list_display = ["display_name", "provider", "is_active", "is_default", "max_tokens"]
    list_filter = ["provider", "is_active", "is_default"]


@admin.register(AIActionType)
class AIActionTypeAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "default_model", "fallback_model", "is_active"]
    list_filter = ["is_active"]


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = [
        "action_type", "model_used", "user", "total_tokens",
        "estimated_cost", "latency_ms", "success", "created_at",
    ]
    list_filter = ["success", "action_type", "model_used"]
    readonly_fields = [
        "action_type", "model_used", "user", "input_tokens", "output_tokens",
        "total_tokens", "estimated_cost", "latency_ms", "success",
        "error_message", "created_at",
    ]
