"""
Django signals for aifw cache invalidation.

Registered in AifwConfig.ready() — invalidates the in-memory config cache
whenever AIActionType, LLMModel, or LLMProvider records are saved or deleted.

This covers single-process deployments. For multi-worker setups (Gunicorn),
configure a Redis pub/sub channel to broadcast invalidation across workers.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


def _connect_signals() -> None:
    """Connect all aifw cache invalidation signals."""
    from aifw.models import AIActionType, LLMModel, LLMProvider
    from aifw.service import invalidate_config_cache

    @receiver(post_save, sender=AIActionType)
    @receiver(post_delete, sender=AIActionType)
    def _invalidate_on_action_change(sender, instance, **kwargs) -> None:
        invalidate_config_cache(instance.code)

    @receiver(post_save, sender=LLMModel)
    @receiver(post_delete, sender=LLMModel)
    def _invalidate_on_model_change(sender, instance, **kwargs) -> None:
        invalidate_config_cache()

    @receiver(post_save, sender=LLMProvider)
    @receiver(post_delete, sender=LLMProvider)
    def _invalidate_on_provider_change(sender, instance, **kwargs) -> None:
        invalidate_config_cache()
