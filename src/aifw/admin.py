from django.contrib import admin

from aifw.models import AIActionType, AIUsageLog, LLMModel, LLMProvider, TierQualityMapping


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
    list_display = [
        "code", "name", "quality_level", "priority",
        "default_model", "fallback_model", "prompt_template_key", "is_active",
    ]
    list_filter = ["is_active", "quality_level", "priority"]
    search_fields = ["code", "name"]
    ordering = ["code", "quality_level", "priority"]


@admin.register(TierQualityMapping)
class TierQualityMappingAdmin(admin.ModelAdmin):
    list_display = ["tier", "quality_level", "is_active", "updated_at"]
    list_filter = ["is_active"]
    ordering = ["-quality_level"]


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = [
        "action_type", "model_used", "quality_level", "user",
        "total_tokens", "estimated_cost", "latency_ms", "success", "created_at",
    ]
    list_filter = ["success", "quality_level", "action_type", "model_used"]
    readonly_fields = [
        "action_type", "model_used", "user", "quality_level",
        "input_tokens", "output_tokens", "total_tokens",
        "estimated_cost", "latency_ms", "success",
        "error_message", "created_at",
    ]
