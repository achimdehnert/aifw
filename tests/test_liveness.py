"""`check_aifw_config --liveness` — ask the provider, do not trust the seed.

The gap this closes was measured on 2026-08-25: ``groq/llama-3.3-70b-versatile``
was seeded here as the **global default** and is no longer listed by Groq. Every
catch-all row was present, every check green, and 19 consuming repos kept
getting the dead pin on every fresh seed.

Two design decisions are pinned by these tests, because both were arrived at by
measurement rather than by taste:

1. **The oracle is the model list, not a test call.** A one-token request against
   ``claude-sonnet-5`` — a model that *is* listed — returned HTTP 400 that day,
   because the account had no credit. A liveness check built on test calls would
   have reported the entire Anthropic catalogue as retired.
2. **A missing key is not a defect.** An installation that does not use Mistral
   must not go red because of it — a checker that is permanently red gets
   switched off, and then it checks nothing at all. A *rejected* key is a
   different matter and does go red.
"""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from aifw.liveness import (
    KEY_REJECTED,
    LIVE,
    NO_KEY,
    RETIRED,
    UNREACHABLE,
    Katalog,
    pin_ist_live,
    pruefe_modell,
)
from aifw.models import AIActionType, LLMModel, LLMProvider


def _registry(modellname: str, provider_name: str = "groq", env_var: str = "GROQ_API_KEY"):
    provider = LLMProvider.objects.create(
        name=provider_name, display_name=provider_name.title(), api_key_env_var=env_var
    )
    modell = LLMModel.objects.create(
        provider=provider, name=modellname, display_name=modellname, is_active=True
    )
    AIActionType.objects.create(code="probe", name="Probe", default_model=modell, is_active=True)
    return modell


def _lauf(katalog: Katalog) -> str:
    aus = StringIO()
    with patch("aifw.liveness.katalog_fuer", return_value=katalog):
        call_command("check_aifw_config", "--liveness", stdout=aus)
    return aus.getvalue()


# ── pin matching ─────────────────────────────────────────────────────────────


def test_should_accept_an_exactly_listed_pin():
    assert pin_ist_live("openai/gpt-oss-120b", ["openai/gpt-oss-120b", "whisper-large-v3"])


def test_should_accept_an_undated_alias_of_a_dated_id():
    """Anthropic lists dated ids while the undated alias is a valid model string."""
    assert pin_ist_live("claude-haiku-4-5", ["claude-haiku-4-5-20251001", "claude-opus-5"])


def test_should_not_accept_a_pin_the_provider_no_longer_lists():
    groq_heute = ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "whisper-large-v3"]
    assert not pin_ist_live("llama-3.3-70b-versatile", groq_heute)


# ── verdict per model ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_should_call_a_missing_pin_retired():
    modell = _registry("llama-3.3-70b-versatile")

    status, detail = pruefe_modell(modell, Katalog(status=LIVE, ids=["openai/gpt-oss-120b"]))

    assert status == RETIRED
    assert "llama-3.3-70b-versatile" in detail


@pytest.mark.django_db
def test_should_pass_a_catalogue_problem_through_instead_of_guessing():
    """No catalogue means no statement about the model — not 'retired'."""
    modell = _registry("openai/gpt-oss-120b")

    for lage in (NO_KEY, KEY_REJECTED, UNREACHABLE):
        status, _ = pruefe_modell(modell, Katalog(status=lage, detail="x"))
        assert status == lage


# ── the command ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_should_fail_loudly_when_a_model_is_retired():
    _registry("llama-3.3-70b-versatile")

    with pytest.raises(CommandError) as fehler:
        _lauf(Katalog(status=LIVE, ids=["openai/gpt-oss-120b"]))

    assert "llama-3.3-70b-versatile" in str(fehler.value)


@pytest.mark.django_db
def test_should_stay_green_when_the_pin_is_served():
    _registry("openai/gpt-oss-120b")

    text = _lauf(Katalog(status=LIVE, ids=["openai/gpt-oss-120b"]))

    assert "LIVE" in text
    assert "1 model(s) confirmed served" in text


@pytest.mark.django_db
def test_should_not_go_red_on_a_provider_this_installation_does_not_use():
    _registry("mistral-large", provider_name="mistral", env_var="MISTRAL_API_KEY")

    text = _lauf(Katalog(status=NO_KEY, detail="MISTRAL_API_KEY not set"))

    assert "SKIP" in text
    assert "not checkable" in text


@pytest.mark.django_db
def test_should_go_red_on_a_key_that_is_set_and_rejected():
    """A configured key that the provider refuses is a defect, not a gap."""
    _registry("mistral-large", provider_name="mistral", env_var="MISTRAL_API_KEY")

    with pytest.raises(CommandError) as fehler:
        _lauf(Katalog(status=KEY_REJECTED, detail="HTTP 401"))

    assert "key_rejected" in str(fehler.value)


# ── the request itself ───────────────────────────────────────────────────────


def test_should_send_a_real_user_agent():
    """urllib's default UA is refused by Groq and Cerebras with HTTP 403.

    Measured 2026-08-25: same key, same URL — ``curl`` got 200, urllib got 403.
    Without an explicit User-Agent this checker reports a working key as
    rejected, i.e. it manufactures exactly the false alarm that gets a checker
    switched off. This test pins the header, not the value.
    """
    from unittest.mock import MagicMock

    from aifw import liveness

    gesehen = {}

    class _Antwort:
        status = 200

        def read(self):
            return b'{"data": [{"id": "openai/gpt-oss-120b"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def _urlopen(anfrage, timeout=None):
        gesehen.update(anfrage.headers)
        return _Antwort()

    provider = MagicMock(name="groq")
    provider.name = "groq"
    provider.api_key_env_var = "GROQ_API_KEY"

    with (
        patch.object(liveness.urllib.request, "urlopen", _urlopen),
        patch.dict("os.environ", {"GROQ_API_KEY": "x"}),
    ):
        katalog = liveness.katalog_fuer(provider)

    assert katalog.status == LIVE
    # urllib normalises header names to Capitalised form.
    assert "aifw-liveness" in gesehen.get("User-agent", "")
