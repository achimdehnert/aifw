"""Ein ``model``-Override zieht den Schluessel seines Providers mit.

Fundstelle (writing-hub, 2026-07-30): eine auf ``openai:gpt-4o-mini`` verdrahtete
Action wurde per Override auf ``groq/qwen/qwen3.6-27b`` gesetzt. Der Modellstring
kam bei litellm an, der ``api_key`` blieb der von OpenAI — Ergebnis „Invalid API
Key". Die Meldung liest sich wie ein toter Schluessel, obwohl beide Schluessel
gueltig waren; zwei Sessions suchten deshalb an der falschen Stelle.

Der Konsument baute sich daraufhin eine eigene Aufloesung und gab den Schluessel
bei jedem Aufruf manuell mit. Genau das soll hier nicht noetig sein.
"""

import pytest

from aifw.service import _build_kwargs, _resolve_api_key

VERDRAHTET = {
    "model_string": "openai/gpt-4o-mini",
    "api_key": "openai-wert",
    "max_tokens": 2000,
    "temperature": 0.7,
}
NACHRICHTEN = [{"role": "user", "content": "hallo"}]


def _kwargs(overrides, config=None):
    return _build_kwargs(dict(config or VERDRAHTET), NACHRICHTEN, overrides)


def test_should_use_the_key_of_the_overridden_provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-wert")
    kwargs = _kwargs({"model": "groq/qwen/qwen3.6-27b"})
    assert kwargs["api_key"] == "groq-wert"


def test_should_keep_the_wired_key_without_an_override():
    assert _kwargs({})["api_key"] == "openai-wert"


def test_should_keep_the_wired_key_for_the_same_provider(monkeypatch):
    """Modellwechsel INNERHALB des Providers laesst den Schluessel unberuehrt."""
    monkeypatch.setenv("OPENAI_API_KEY", "anderer-wert")
    assert _kwargs({"model": "openai/gpt-4o"})["api_key"] == "openai-wert"


def test_should_let_an_explicit_key_win(monkeypatch):
    """Ausgerollte Workarounds geben den Schluessel selbst mit — die bleiben gueltig."""
    monkeypatch.setenv("GROQ_API_KEY", "groq-wert")
    kwargs = _kwargs({"model": "groq/qwen/qwen3.6-27b", "api_key": "handgereicht"})
    assert kwargs["api_key"] == "handgereicht"


def test_should_drop_the_foreign_key_when_none_is_configured(monkeypatch):
    """Ohne passenden Schluessel lieber KEINER als der fremde.

    Der fremde scheitert garantiert und erzeugt dabei „Invalid API Key" — die
    irrefuehrendste Meldung von allen. Ohne Schluessel sagt litellm sauber, dass
    keiner da ist.
    """
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert "api_key" not in _kwargs({"model": "groq/qwen/qwen3.6-27b"})


def test_should_ignore_a_model_override_without_provider_prefix(monkeypatch):
    """Ohne Praefix deutet litellm den Namen als OpenAI-Modell — Verdrahtung gilt."""
    assert _kwargs({"model": "gpt-4o"})["api_key"] == "openai-wert"


def test_should_not_touch_other_overrides(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-wert")
    kwargs = _kwargs(
        {"model": "groq/qwen/qwen3.6-27b", "reasoning_format": "parsed", "max_tokens": 8000}
    )
    assert kwargs["reasoning_format"] == "parsed"
    assert kwargs["max_tokens"] == 8000
    assert kwargs["model"] == "groq/qwen/qwen3.6-27b"


# --- Schluessel-Aufloesung nach Konvention ---


@pytest.mark.parametrize(
    "provider,env_var",
    [
        ("groq", "GROQ_API_KEY"),
        ("mistral", "MISTRAL_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
    ],
)
def test_should_resolve_by_convention(monkeypatch, provider, env_var):
    """Die Map deckte vier Provider ab; alle anderen fielen still auf ''."""
    monkeypatch.setenv(env_var, f"{provider}-wert")
    assert _resolve_api_key(provider, "") == f"{provider}-wert"


def test_should_prefer_an_explicit_env_var(monkeypatch):
    monkeypatch.setenv("HAUSEIGEN", "expliziter-wert")
    monkeypatch.setenv("GROQ_API_KEY", "konventions-wert")
    assert _resolve_api_key("groq", "HAUSEIGEN") == "expliziter-wert"


def test_should_return_empty_for_an_unknown_provider(monkeypatch):
    monkeypatch.delenv("PHANTASIE_API_KEY", raising=False)
    assert _resolve_api_key("phantasie", "") == ""


def test_should_survive_a_provider_name_with_punctuation(monkeypatch):
    """Provider-Namen sind freier Text — der Variablenname darf davon nicht zerbrechen."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-wert")
    assert _resolve_api_key("azure-openai", "") == "azure-wert"
