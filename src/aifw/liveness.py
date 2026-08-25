"""Ask each provider which models it still serves (issue: retired model IDs).

## Why this exists

``check_aifw_config`` verified that every action code has a catch-all row — a
statement about *this* database. It never asked whether the model that row
points at still exists upstream. On 2026-08-25 that gap was measured:
``groq/llama-3.3-70b-versatile``, seeded here as the **global default**, is no
longer listed by Groq. Every fresh seed in any of the consuming repos brought
the dead pin back, and nothing turned red until someone made a real call.

A model being retired is routine, not an incident. The registry therefore has
to notice it on its own.

## Why the model list and not a test call

The obvious check — send one token and see whether it works — conflates three
different failures. Measured on 2026-08-25: a one-token request against
``claude-sonnet-5`` (a model that *is* listed) returned HTTP 400 because the
account had no credit. A liveness check built on test calls would have
declared the whole Anthropic catalogue dead.

``GET /models`` answers exactly one question — *does this provider serve this
id* — and that is the question here.

## Four outcomes, deliberately not three

``LIVE`` · ``RETIRED`` · ``NO_KEY`` · ``KEY_REJECTED`` · ``UNREACHABLE``.

``NO_KEY`` and ``KEY_REJECTED`` look similar and are not: a missing key is a
coverage gap (this installation does not use that provider), a rejected key is
a defect (it is configured and does not work). Measured 2026-08-25: the Mistral
key in the org secret store answers ``Invalid API Key`` while the routing
policy lists Mistral as available.

## Aliases without a date suffix

Anthropic lists dated ids (``claude-haiku-4-5-20251001``) while the undated
alias (``claude-haiku-4-5``) is a valid model string. A pin therefore counts as
live when it is listed **or** when a listed id starts with it followed by a
dash. ``*-latest`` remains forbidden as a pin (platform:ADR-208) — that rule is
about reproducibility, not about liveness, and is not enforced here.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

LIVE = "live"
RETIRED = "retired"
NO_KEY = "no_key"
KEY_REJECTED = "key_rejected"
UNREACHABLE = "unreachable"

#: Only RETIRED and KEY_REJECTED are defects. NO_KEY is a coverage gap, and a
#: checker that goes red on it in every installation gets switched off.
DEFECTS = frozenset({RETIRED, KEY_REJECTED})

DEFAULT_TIMEOUT = 15.0

#: Sent on every catalogue request. Not cosmetic: with urllib's default
#: ``Python-urllib/3.12`` both Groq and Cerebras answer **HTTP 403** — measured
#: 2026-08-25, same key, same URL, ``curl`` got 200 and urllib got 403. Without
#: this header the checker reports a perfectly good key as rejected, which is
#: exactly the kind of false alarm that gets a checker switched off.
USER_AGENT = "aifw-liveness/1.0 (+https://github.com/achimdehnert/aifw)"

#: Providers whose catalogue endpoint is OpenAI-compatible (``{"data": [{"id"…}]}``).
OPENAI_COMPATIBLE_BASE = {
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "openai": "https://api.openai.com/v1",
    "together": "https://api.together.xyz/v1",
    "together_ai": "https://api.together.xyz/v1",
    "mistral": "https://api.mistral.ai/v1",
}

ANTHROPIC_BASE = "https://api.anthropic.com/v1"


@dataclass
class Katalog:
    """What a provider answered when asked for its model list."""

    status: str
    ids: list[str] = field(default_factory=list)
    detail: str = ""


def _hole(url: str, headers: dict[str, str], timeout: float) -> tuple[int, str]:
    anfrage = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})  # noqa: S310
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:  # noqa: S310
            return antwort.status, antwort.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _ids_aus(rohtext: str, schluessel: str = "data") -> list[str]:
    daten = json.loads(rohtext)
    eintraege = daten.get(schluessel, daten) if isinstance(daten, dict) else daten
    if not isinstance(eintraege, list):
        return []
    return [str(e.get("id") or e.get("name") or "") for e in eintraege if isinstance(e, dict)]


def katalog_fuer(provider, timeout: float = DEFAULT_TIMEOUT) -> Katalog:
    """The model ids a provider currently serves — or why we could not ask."""
    name = (provider.name or "").lower()

    if name == "ollama":
        basis = (provider.base_url or "http://localhost:11434").rstrip("/")
        try:
            code, roh = _hole(f"{basis}/api/tags", {}, timeout)
        except Exception as exc:  # noqa: BLE001 — every cause leads to the same answer
            return Katalog(status=UNREACHABLE, detail=f"{type(exc).__name__}: {exc}")
        if code != 200:
            return Katalog(status=UNREACHABLE, detail=f"HTTP {code}")
        return Katalog(status=LIVE, ids=_ids_aus(roh, "models"))

    env_var = provider.api_key_env_var or ""
    schluessel = os.environ.get(env_var, "") if env_var else ""
    if env_var and not schluessel:
        return Katalog(status=NO_KEY, detail=f"{env_var} not set")

    if name == "anthropic":
        url = f"{ANTHROPIC_BASE}/models"
        headers = {"x-api-key": schluessel, "anthropic-version": "2023-06-01"}
    else:
        basis = OPENAI_COMPATIBLE_BASE.get(name)
        if not basis:
            return Katalog(status=NO_KEY, detail=f"no catalogue endpoint known for '{name}'")
        url = f"{basis}/models"
        headers = {"Authorization": f"Bearer {schluessel}"}

    try:
        code, roh = _hole(url, headers, timeout)
    except Exception as exc:  # noqa: BLE001
        return Katalog(status=UNREACHABLE, detail=f"{type(exc).__name__}: {exc}")

    if code in (401, 403):
        return Katalog(status=KEY_REJECTED, detail=f"HTTP {code} — {env_var} is set but rejected")
    if code != 200:
        return Katalog(status=UNREACHABLE, detail=f"HTTP {code}")
    try:
        return Katalog(status=LIVE, ids=_ids_aus(roh))
    except (ValueError, AttributeError) as exc:
        return Katalog(status=UNREACHABLE, detail=f"unreadable catalogue: {exc}")


def pin_ist_live(pin: str, ids: list[str]) -> bool:
    """Exact hit — or a dated id that this undated alias stands for."""
    if pin in ids:
        return True
    prefix = f"{pin}-"
    return any(i.startswith(prefix) for i in ids)


def pruefe_modell(modell, katalog: Katalog) -> tuple[str, str]:
    """(status, detail) for one registry row against its provider's catalogue."""
    if katalog.status != LIVE:
        return katalog.status, katalog.detail
    if pin_ist_live(modell.name, katalog.ids):
        return LIVE, ""
    return RETIRED, f"'{modell.name}' is not served by {modell.provider.name} any more"
