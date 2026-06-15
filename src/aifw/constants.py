"""
aifw/constants.py — Shared constants for quality-level routing.

ADR-095 §5.1 — QualityLevel scale definition.
"""
from __future__ import annotations


class QualityLevel:
    """Quality band constants (1–9 scale).

    Consumers use symbolic names, never raw integers:
        from aifw.constants import QualityLevel
        quality = QualityLevel.PREMIUM  # 8
    """

    ECONOMY: int = 2   # 1–3 band centre
    BALANCED: int = 5  # 4–6 band centre
    PREMIUM: int = 8   # 7–9 band centre

    #: All valid values (1–9 inclusive)
    ALL: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9)

    @classmethod
    def is_valid(cls, value: int | None) -> bool:
        """Return True if value is a valid quality level (1–9) or None."""
        if value is None:
            return True
        return value in cls.ALL

    @classmethod
    def band_for(cls, value: int) -> str:
        """Return human-readable band name for a quality level."""
        if 1 <= value <= 3:
            return "economy"
        if 4 <= value <= 6:
            return "balanced"
        if 7 <= value <= 9:
            return "premium"
        raise ValueError(f"quality_level must be 1–9, got {value}")


#: Valid priority string values (NULL = catch-all, handled separately)
VALID_PRIORITIES: frozenset[str] = frozenset({"fast", "balanced", "quality"})


class PrivacyMode:
    """Privacy policy applied to an AIUsageLog row at write time (issue #8).

    Consumers select the active mode via the ``AIFW_PRIVACY_MODE`` Django
    setting and use symbolic names rather than raw strings::

        from aifw.constants import PrivacyMode
        # settings.py
        AIFW_PRIVACY_MODE = PrivacyMode.PSEUDONYMOUS
    """

    FULL: str = "full"                  # legacy default — user + metadata raw
    PSEUDONYMOUS: str = "pseudonymous"  # HMAC user_hash + classified topic
    ANONYMOUS: str = "anonymous"        # tenant + tokens + day_bucket only

    #: All valid mode strings
    ALL: tuple[str, ...] = (FULL, PSEUDONYMOUS, ANONYMOUS)

    @classmethod
    def is_valid(cls, value: str | None) -> bool:
        """Return True if value is a valid privacy mode."""
        return value in cls.ALL


#: Valid privacy mode strings
VALID_PRIVACY_MODES: frozenset[str] = frozenset(PrivacyMode.ALL)
