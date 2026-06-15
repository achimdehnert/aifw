"""
Privacy-by-Design pre-write transforms for AIUsageLog (ADR-003 ttz-hub, issue #8).

A *privacy hook* rewrites the AIUsageLog create-payload **before** it is written,
so PII never reaches the database in the first place (DSGVO Art. 25 / Art. 5 Abs.
1 lit. c — Privacy-by-Design + Datenminimierung).

Three built-in modes (selected via the ``AIFW_PRIVACY_MODE`` Django setting):

- ``"full"``         — legacy default: ``user`` + ``metadata`` written raw, as before.
- ``"pseudonymous"`` — ``user`` dropped; ``metadata["user_hash"]`` = HMAC(user.pk);
                       any ``metadata["nl_question"]`` is replaced by ``metadata["topic"]``
                       via a topic classifier (default: a coarse placeholder — wire
                       ``iil-promptfw`` or any callable via a custom hook for real topics).
- ``"anonymous"``    — ``user`` dropped; ``metadata`` reduced to ``{"day_bucket": <ISO date>}``.
                       Only ``tenant_id`` + ``action_type`` + token counts survive.

Custom hooks are registered via the ``AIFW_PRIVACY_HOOK`` setting, a dotted path
in either ``"module.path:attr"`` or ``"module.path.attr"`` form. The target may be
a :class:`PrivacyHook` instance, a :class:`PrivacyHook` subclass, or a zero-arg
factory returning one.

**Fail-closed.** If a configured non-``full`` hook raises, the payload is scrubbed
(``user=None``, ``metadata={"privacy_error": True}``) rather than leaking raw PII.

The ``AIFW_PRIVACY_HMAC_SECRET`` setting keys the pseudonymous user hash; it falls
back to Django's ``SECRET_KEY`` when unset. ``aifw`` never imports ``iil-promptfw`` —
topic classification is a plain callable injected by the consumer.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import logging
from typing import Any, Callable

from aifw.constants import PrivacyMode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings access (read fresh every call — override_settings must take effect)
# ---------------------------------------------------------------------------

def _get_setting(name: str, default: Any = None) -> Any:
    from django.conf import settings
    return getattr(settings, name, default)


def _resolve_hmac_secret() -> bytes:
    secret = _get_setting("AIFW_PRIVACY_HMAC_SECRET") or _get_setting("SECRET_KEY", "")
    return str(secret).encode("utf-8")


def _hmac_user(user_pk: Any, secret: bytes) -> str:
    return hmac.new(secret, str(user_pk).encode("utf-8"), hashlib.sha256).hexdigest()


def _today_iso() -> str:
    from django.utils import timezone
    return timezone.now().date().isoformat()


def _default_topic_classifier(nl_question: str) -> str:
    """Built-in placeholder classifier.

    aifw ships no NLP. This guarantees the raw question never persists by
    replacing it with a coarse marker. Consumers wire a real classifier
    (e.g. iil-promptfw) via a custom hook for meaningful topics.
    """
    return "unclassified"


# ---------------------------------------------------------------------------
# Hook implementations
# ---------------------------------------------------------------------------

class PrivacyHook:
    """Base hook — ``full`` mode: identity transform (writes payload raw)."""

    mode: str = PrivacyMode.FULL

    def transform(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Rewrite the AIUsageLog create-payload in place and return it.

        Payload keys of interest: ``user`` (User instance or None), ``tenant_id``,
        ``metadata`` (dict). Other keys (tokens, action_type, ...) pass through.
        """
        return payload


class PseudonymousHook(PrivacyHook):
    """Drop the user FK, replace it with an HMAC hash, classify the question."""

    mode = PrivacyMode.PSEUDONYMOUS

    def __init__(
        self,
        hmac_secret: bytes | None = None,
        topic_classifier: Callable[[str], str] | None = None,
    ) -> None:
        self._secret = hmac_secret if hmac_secret is not None else _resolve_hmac_secret()
        self._classify = topic_classifier or _default_topic_classifier

    def transform(self, payload: dict[str, Any]) -> dict[str, Any]:
        user = payload.get("user")
        user_pk = getattr(user, "pk", None)
        payload["user"] = None
        meta = dict(payload.get("metadata") or {})
        if user_pk is not None:
            meta["user_hash"] = _hmac_user(user_pk, self._secret)
        if "nl_question" in meta:
            meta["topic"] = self._classify(meta.pop("nl_question"))
        payload["metadata"] = meta
        return payload


class AnonymousHook(PrivacyHook):
    """Strip every user trace — keep only tenant/action/tokens + a day bucket."""

    mode = PrivacyMode.ANONYMOUS

    def transform(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["user"] = None
        payload["metadata"] = {"day_bucket": _today_iso()}
        return payload


_BUILTIN_HOOKS: dict[str, type[PrivacyHook]] = {
    PrivacyMode.FULL: PrivacyHook,
    PrivacyMode.PSEUDONYMOUS: PseudonymousHook,
    PrivacyMode.ANONYMOUS: AnonymousHook,
}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _import_hook(dotted: str) -> PrivacyHook:
    """Import a custom hook from ``"module:attr"`` or ``"module.attr"``."""
    if ":" in dotted:
        module_path, attr = dotted.split(":", 1)
    else:
        module_path, attr = dotted.rsplit(".", 1)
    module = importlib.import_module(module_path)
    obj = getattr(module, attr)
    if isinstance(obj, PrivacyHook):
        return obj
    if isinstance(obj, type) and issubclass(obj, PrivacyHook):
        return obj()
    if callable(obj):
        result = obj()
        if isinstance(result, PrivacyHook):
            return result
        raise TypeError(
            f"AIFW_PRIVACY_HOOK {dotted!r} factory returned {type(result).__name__}, "
            f"expected a PrivacyHook"
        )
    raise TypeError(
        f"AIFW_PRIVACY_HOOK {dotted!r} is neither a PrivacyHook, subclass, nor factory"
    )


def get_privacy_hook() -> PrivacyHook:
    """Resolve the active privacy hook from Django settings.

    Priority: ``AIFW_PRIVACY_HOOK`` (custom dotted path) → ``AIFW_PRIVACY_MODE``
    (built-in mode, default ``"full"``). An invalid mode logs a warning and
    falls back to ``"full"``.
    """
    dotted = _get_setting("AIFW_PRIVACY_HOOK")
    if dotted:
        return _import_hook(dotted)

    mode = _get_setting("AIFW_PRIVACY_MODE", PrivacyMode.FULL)
    if not PrivacyMode.is_valid(mode):
        logger.warning(
            "Invalid AIFW_PRIVACY_MODE %r — falling back to 'full'", mode
        )
        mode = PrivacyMode.FULL
    return _BUILTIN_HOOKS[mode]()


def apply_privacy(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the active privacy hook over an AIUsageLog create-payload.

    Always stamps ``payload["privacy_mode"]`` with the applied mode. Fail-closed:
    if a configured non-``full`` hook raises, the user/metadata are scrubbed so a
    broken transform can never leak PII.
    """
    try:
        hook = get_privacy_hook()
        payload = hook.transform(payload)
        payload["privacy_mode"] = getattr(hook, "mode", PrivacyMode.FULL)
        return payload
    except Exception as exc:  # noqa: BLE001 — privacy must never crash logging
        intended = _get_setting("AIFW_PRIVACY_MODE", PrivacyMode.FULL)
        custom = bool(_get_setting("AIFW_PRIVACY_HOOK"))
        if custom or intended != PrivacyMode.FULL:
            logger.warning(
                "Privacy hook failed (%s) — failing closed, scrubbing PII", exc
            )
            payload["user"] = None
            payload["metadata"] = {"privacy_error": True}
            payload["privacy_mode"] = (
                intended if PrivacyMode.is_valid(intended) else PrivacyMode.ANONYMOUS
            )
        else:
            logger.warning("Privacy hook failed (%s) — writing 'full' raw log", exc)
            payload["privacy_mode"] = PrivacyMode.FULL
        return payload
