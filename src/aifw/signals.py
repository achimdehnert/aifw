"""
Django signals for aifw cache invalidation.

Registered in AifwConfig.ready() — invalidates both the process-local cache
and the shared Django cache (Redis if configured) whenever AIActionType,
LLMModel, LLMProvider, or TierQualityMapping records are saved or deleted.

For multi-worker Gunicorn deployments: configure CACHES to use Redis in the
consumer app. The process-local cache provides an additional 30s buffer.

``weak=False`` is load-bearing, not decoration. The receivers below are local
functions inside :func:`_connect_signals`; with Django's default ``weak=True``
nothing holds a strong reference once that function returns, so all four
entries stay in ``post_save.receivers`` while their targets are already gone.
Measured on 2026-08-30 in a writing-hub test run: 4 entries, 0 live receivers,
and a cache key survived ``AIActionType.save(update_fields=[...])`` untouched.

That silent death is what writing-hub#766 cost: a reseed to a different
provider did not take effect for up to ``AIFW_CACHE_TTL`` (600s), while the
error message read the fresh database row and named the *new* provider. The
call kept going to the old one. Every aifw consumer relying on save-triggered
invalidation was affected, not just that repo.
"""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


def _connect_signals() -> None:
    """Connect all aifw cache invalidation signals."""
    from aifw.models import AIActionType, LLMModel, LLMProvider, TierQualityMapping
    from aifw.service import invalidate_action_cache, invalidate_tier_cache

    @receiver(post_save, weak=False, sender=AIActionType)
    @receiver(post_delete, weak=False, sender=AIActionType)
    def _invalidate_on_action_change(sender, instance, **kwargs) -> None:
        invalidate_action_cache(instance.code)

    @receiver(post_save, weak=False, sender=LLMModel)
    @receiver(post_delete, weak=False, sender=LLMModel)
    def _invalidate_on_model_change(sender, instance, **kwargs) -> None:
        invalidate_action_cache()  # full clear — any action may be affected

    @receiver(post_save, weak=False, sender=LLMProvider)
    @receiver(post_delete, weak=False, sender=LLMProvider)
    def _invalidate_on_provider_change(sender, instance, **kwargs) -> None:
        invalidate_action_cache()  # full clear — any action may be affected

    @receiver(post_save, weak=False, sender=TierQualityMapping)
    @receiver(post_delete, weak=False, sender=TierQualityMapping)
    def _invalidate_on_tier_change(sender, instance, **kwargs) -> None:
        invalidate_tier_cache(instance.tier)
