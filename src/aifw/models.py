"""
AI Services Models — DB-driven LLM configuration.

Allows configuring which LLM/provider to use per action type.
Zero code changes required for model/provider swaps.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)


class LLMProvider(models.Model):
    """Available LLM providers (OpenAI, Anthropic, Google, Ollama, ...)."""

    name = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    api_key_env_var = models.CharField(max_length=100, default="")
    base_url = models.URLField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "aifw"
        db_table = "aifw_llm_providers"
        verbose_name = "LLM Provider"
        verbose_name_plural = "LLM Providers"

    def __str__(self) -> str:
        return self.display_name


class LLMModel(models.Model):
    """Available LLM models with cost & capability metadata."""

    provider = models.ForeignKey(
        LLMProvider, on_delete=models.CASCADE, related_name="models"
    )
    name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=100)
    max_tokens = models.IntegerField(default=4096)
    supports_vision = models.BooleanField(default=False)
    supports_tools = models.BooleanField(default=True)
    input_cost_per_million = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    output_cost_per_million = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        app_label = "aifw"
        db_table = "aifw_llm_models"
        verbose_name = "LLM Model"
        verbose_name_plural = "LLM Models"
        unique_together = ["provider", "name"]

    def __str__(self) -> str:
        return f"{self.provider.name}:{self.name}"


class AIActionType(models.Model):
    """Maps action codes to LLM models — DB-driven routing."""

    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    default_model = models.ForeignKey(
        LLMModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_actions",
    )
    fallback_model = models.ForeignKey(
        LLMModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fallback_for_actions",
    )
    max_tokens = models.IntegerField(default=2000)
    temperature = models.FloatField(default=0.7)
    is_active = models.BooleanField(default=True)
    budget_per_day = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="Max USD spend per day. Switches to fallback model when exceeded."
    )

    class Meta:
        app_label = "aifw"
        db_table = "aifw_action_types"
        verbose_name = "AI Action Type"
        verbose_name_plural = "AI Action Types"

    def __str__(self) -> str:
        return self.name

    def get_model(self) -> LLMModel | None:
        if self.default_model and self.default_model.is_active:
            if not self._budget_exceeded():
                return self.default_model
            logger.info("Budget exceeded for '%s' — switching to fallback", self.code)
        if self.fallback_model and self.fallback_model.is_active:
            return self.fallback_model
        return LLMModel.objects.filter(is_active=True, is_default=True).first()

    def _budget_exceeded(self) -> bool:
        """Return True if today's spend has reached or exceeded budget_per_day."""
        if not self.budget_per_day:
            return False
        from datetime import date
        today_spend = (
            AIUsageLog.objects.filter(
                action_type=self,
                created_at__date=date.today(),
                success=True,
            ).aggregate(total=models.Sum("estimated_cost"))["total"] or 0
        )
        return float(today_spend) >= float(self.budget_per_day)


class AIUsageLog(models.Model):
    """Token & cost tracking per LLM request."""

    action_type = models.ForeignKey(
        AIActionType, on_delete=models.SET_NULL, null=True, blank=True
    )
    model_used = models.ForeignKey(
        LLMModel, on_delete=models.SET_NULL, null=True, blank=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    tenant_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Tenant UUID for multi-tenant applications.",
    )
    object_id = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        help_text="Opaque reference to the domain object that triggered this call "
        "(e.g. 'chapter:42', 'project:7'). Set by the consumer.",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Arbitrary key/value context (pipeline stage, prompt version, etc.).",
    )
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    latency_ms = models.IntegerField(default=0)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "aifw"
        db_table = "aifw_usage_logs"
        verbose_name = "AI Usage Log"
        verbose_name_plural = "AI Usage Logs"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action_type} / {self.model_used} ({self.created_at:%Y-%m-%d})"

    def save(self, *args, **kwargs) -> None:
        self.total_tokens = self.input_tokens + self.output_tokens
        if self.model_used:
            input_cost = (self.input_tokens / 1_000_000) * float(
                self.model_used.input_cost_per_million
            )
            output_cost = (self.output_tokens / 1_000_000) * float(
                self.model_used.output_cost_per_million
            )
            self.estimated_cost = input_cost + output_cost
        super().save(*args, **kwargs)
