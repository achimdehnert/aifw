"""
AI Services Models — DB-driven LLM configuration.

New in 0.6.0 (ADR-095):
- AIActionType.code: unique=True → db_index=True (Breaking change — allows
  multiple rows per code for quality_level / priority routing)
- AIActionType.quality_level: nullable int 1–9 (NULL = catch-all)
- AIActionType.priority: nullable 'fast'|'balanced'|'quality' (NULL = catch-all)
- AIActionType.prompt_template_key: nullable str (promptfw key)
- TierQualityMapping: DB-driven subscription tier → quality_level mapping
- AIUsageLog.quality_level: dedicated column for cost-per-tier analytics

New in 0.6.1:
- AIActionType._budget_exceeded(): TTL cache (default 60s, env AIFW_BUDGET_TTL)
  reduces DB aggregation from O(n_calls) to O(1/TTL) under load.

Uniqueness on AIActionType is enforced by 4 partial unique indexes (migration 0005),
not unique_together — required due to PostgreSQL NULL != NULL semantics.
"""
from __future__ import annotations

import logging
import os
import time

from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)

_BUDGET_TTL: int = int(os.environ.get("AIFW_BUDGET_TTL", "60"))
_budget_cache: dict[str, tuple[bool, float]] = {}


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
        unique_together = [["provider", "name"]]

    def __str__(self) -> str:
        return f"{self.provider.name}:{self.name}"


class AIActionType(models.Model):
    """Maps action codes to LLM models — DB-driven quality-level routing.

    Each row defines model + template for a (code, quality_level, priority)
    combination. NULL in quality_level or priority means "catch-all" for
    that dimension.

    Uniqueness is enforced by 4 partial unique indexes (NOT unique_together):
        uix_aiaction_exact      — both non-NULL
        uix_aiaction_ql_only    — quality_level non-NULL, priority NULL
        uix_aiaction_prio_only  — priority non-NULL, quality_level NULL
        uix_aiaction_catchall   — both NULL (classic 0.5.x rows)

    See ADR-095 §5.2 for NULL semantics explanation.
    """

    code = models.CharField(max_length=100, db_index=True)
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
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Max USD spend per day. Switches to fallback model when exceeded.",
    )

    # ── NEW in 0.6.0 (ADR-095) ───────────────────────────────────────────────────
    quality_level = models.IntegerField(
        null=True,
        blank=True,
        help_text=(
            "Quality band (1–9) or NULL (catch-all for any quality_level). "
            "1–3=Economy, 4–6=Balanced, 7–9=Premium. "
            "Use QualityLevel constants: ECONOMY=2, BALANCED=5, PREMIUM=8."
        ),
    )
    priority = models.CharField(
        max_length=16,
        null=True,
        blank=True,
        help_text=(
            "'fast'|'balanced'|'quality' or NULL (catch-all). "
            "Enforced by DB CHECK constraint chk_aiaction_priority."
        ),
    )
    prompt_template_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text=(
            "promptfw template key e.g. 'story_writing_premium'. "
            "NULL = caller uses action code as fallback. "
            "Convention: <action_code>[_economy|_balanced|_premium]. "
            "aifw never imports promptfw — this is a plain string."
        ),
    )

    class Meta:
        app_label = "aifw"
        db_table = "aifw_action_types"
        verbose_name = "AI Action Type"
        verbose_name_plural = "AI Action Types"
        ordering = ["code", "quality_level", "priority"]
        indexes = [
            models.Index(
                fields=["code", "is_active"],
                name="idx_aiaction_code_active",
            ),
        ]

    def __str__(self) -> str:
        parts = [self.code]
        if self.quality_level is not None:
            parts.append(f"ql={self.quality_level}")
        if self.priority is not None:
            parts.append(f"p={self.priority}")
        return ":".join(parts)

    def clean(self) -> None:
        """Model-level validation (secondary guard; DB CHECK is primary)."""
        from django.core.exceptions import ValidationError

        from aifw.constants import VALID_PRIORITIES, QualityLevel

        if self.priority is not None and self.priority not in VALID_PRIORITIES:
            raise ValidationError(
                f"Invalid priority {self.priority!r}. "
                f"Valid values: {sorted(VALID_PRIORITIES)} or None."
            )
        if self.quality_level is not None and not QualityLevel.is_valid(self.quality_level):
            raise ValidationError(
                f"quality_level must be 1–9 or None, got {self.quality_level}."
            )

    def get_model(self) -> LLMModel | None:
        """Return the effective model respecting budget limits."""
        if self.default_model and self.default_model.is_active:
            if not self._budget_exceeded():
                return self.default_model
            logger.info("Budget exceeded for '%s' — switching to fallback", self.code)
        if self.fallback_model and self.fallback_model.is_active:
            return self.fallback_model
        return LLMModel.objects.filter(is_active=True, is_default=True).first()

    def _budget_exceeded(self) -> bool:
        """Return True if today's spend has reached or exceeded budget_per_day.

        Result is cached per action code for _BUDGET_TTL seconds (default 60s,
        env: AIFW_BUDGET_TTL) to avoid per-call DB aggregation under load.
        Cache is invalidated by invalidate_config_cache() on model save/delete.
        """
        if not self.budget_per_day:
            return False

        now = time.monotonic()
        cached = _budget_cache.get(self.code)
        if cached is not None and (now - cached[1]) < _BUDGET_TTL:
            return cached[0]

        from datetime import date

        today_spend = (
            AIUsageLog.objects.filter(
                action_code=self.code,
                created_at__date=date.today(),
                success=True,
            ).aggregate(total=models.Sum("estimated_cost"))["total"]
            or 0
        )
        result = float(today_spend) >= float(self.budget_per_day)
        _budget_cache[self.code] = (result, now)
        return result


def _invalidate_budget_cache(code: str | None = None) -> None:
    """Invalidate budget cache for a specific action code or all codes."""
    if code is not None:
        _budget_cache.pop(code, None)
    else:
        _budget_cache.clear()


class TierQualityMapping(models.Model):
    """DB-driven mapping from subscription tier names to quality_level integers.

    Replaces hardcoded TIER_QUALITY_MAP dicts in consumer apps (ADR-095 H-01).
    Changeable via Django Admin without code deployment.

    Default seed (applied in migration 0005):
        premium  → 8 (QualityLevel.PREMIUM)
        pro      → 5 (QualityLevel.BALANCED)
        freemium → 2 (QualityLevel.ECONOMY)

    Consumer apps use::
        from aifw import get_quality_level_for_tier
        quality = get_quality_level_for_tier(user.subscription)  # "premium" → 8
    """

    tier = models.CharField(
        max_length=64,
        unique=True,
        help_text="Subscription tier name e.g. 'premium', 'pro', 'freemium'.",
    )
    quality_level = models.IntegerField(
        help_text=(
            "Quality level 1–9 assigned to this tier. "
            "Use QualityLevel constants: ECONOMY=2, BALANCED=5, PREMIUM=8."
        ),
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "aifw"
        verbose_name = "Tier Quality Mapping"
        verbose_name_plural = "Tier Quality Mappings"
        ordering = ["-quality_level"]

    def __str__(self) -> str:
        return f"{self.tier} → ql={self.quality_level}"


class AIUsageLog(models.Model):
    """Token & cost tracking per LLM request.

    New in 0.6.0: quality_level column for direct cost-per-tier analytics
    without joins (ADR-095 OQ-2).
    """

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
        help_text="Opaque reference to the domain object (e.g. 'chapter:42').",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Arbitrary key/value context (pipeline stage, prompt version, etc.).",
    )
    # ── NEW in 0.6.0 ───────────────────────────────────────────────────────────────
    quality_level = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Quality level of the request (1–9). "
            "NULL for legacy entries created before 0.6.0. "
            "Dedicated column — never use join to AIActionType for cost analytics."
        ),
    )
    # ──────────────────────────────────────────────────────────────────────
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
        indexes = [
            models.Index(fields=["quality_level", "created_at"]),
            models.Index(fields=["action_type", "created_at"]),
        ]

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
