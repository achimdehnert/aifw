"""
Django signals for aifw cache invalidation.

Registered in AifwConfig.ready() — invalidates both the process-local cache
and the shared Django cache (Redis if configured) whenever AIActionType,
LLMModel, LLMProvider, or TierQualityMapping records are saved or deleted.

For multi-worker Gunicorn deployments: configure CACHES to use Redis in the
consumer app. The process-local cache provides an additional 30s buffer.
"""
from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


def _connect_signals() -> None:
    """Connect all aifw cache invalidation signals."""
    from aifw.models import AIActionType, LLMModel, LLMProvider, TierQualityMapping
    from aifw.service import invalidate_action_cache, invalidate_tier_cache

    @receiver(post_save, sender=AIActionType)
    @receiver(post_delete, sender=AIActionType)
    def _invalidate_on_action_change(sender, instance, **kwargs) -> None:
        invalidate_action_cache(instance.code)

    @receiver(post_save, sender=LLMModel)
    @receiver(post_delete, sender=LLMModel)
    def _invalidate_on_model_change(sender, instance, **kwargs) -> None:
        invalidate_action_cache()  # full clear — any action may be affected

    @receiver(post_save, sender=LLMProvider)
    @receiver(post_delete, sender=LLMProvider)
    def _invalidate_on_provider_change(sender, instance, **kwargs) -> None:
        invalidate_action_cache()  # full clear — any action may be affected

    @receiver(post_save, sender=TierQualityMapping)
    @receiver(post_delete, sender=TierQualityMapping)
    def _invalidate_on_tier_change(sender, instance, **kwargs) -> None:
        invalidate_tier_cache(instance.tier)
