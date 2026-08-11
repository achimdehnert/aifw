"""API-Key-Aufloesung aus gemounteten Secret-Dateien.

Hintergrund: Secrets werden im Betrieb als Datei in den Container gemountet
(``/opt/<app>/.secrets/<name>`` -> ``/run/secrets/<name>``), nicht als
Umgebungsvariable gesetzt. Solange ``_resolve_api_key`` nur ``os.environ``
las, sah aifw einen sauber hinterlegten Schluessel nicht.

Gemessen 2026-08-10 auf Prod: drei aifw-Consumer (tax-hub, risk-hub,
ausschreibungs-hub), kein einziger mit einem LLM-Schluessel in der Umgebung.
Der Fehler faellt nicht auf, weil ein leerer Schluessel beim Provider dieselbe
Meldung erzeugt wie ein ungueltiger ("Invalid API Key").
"""

from __future__ import annotations

import pytest

from aifw.service import _resolve_api_key

PROVIDER = "groq"
VAR = "GROQ_API_KEY"


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch, tmp_path):
    """Kein echter Schluessel und kein echtes /run/secrets im Test."""
    for name in (VAR, f"{VAR}_FILE", "AIFW_SECRETS_DIR"):
        monkeypatch.delenv(name, raising=False)
    # Zeigt ins Leere, solange ein Test nichts anderes setzt — sonst wuerde der
    # Test auf einer Maschine mit echtem /run/secrets/groq_api_key anders
    # ausgehen als in CI.
    monkeypatch.setenv("AIFW_SECRETS_DIR", str(tmp_path / "leer"))
    return tmp_path


def test_should_prefer_environment_variable_over_file(monkeypatch, saubere_umgebung):
    """Bestandsdeployments mit Wert in der Umgebung aendern ihr Verhalten nicht."""
    datei = saubere_umgebung / "aus_datei"
    datei.write_text("schluessel-aus-datei")
    monkeypatch.setenv(VAR, "schluessel-aus-env")
    monkeypatch.setenv(f"{VAR}_FILE", str(datei))

    assert _resolve_api_key(PROVIDER, VAR) == "schluessel-aus-env"


def test_should_read_key_from_var_file_path(monkeypatch, saubere_umgebung):
    datei = saubere_umgebung / "geheim"
    datei.write_text("schluessel-aus-datei")
    monkeypatch.setenv(f"{VAR}_FILE", str(datei))

    assert _resolve_api_key(PROVIDER, VAR) == "schluessel-aus-datei"


def test_should_read_key_from_mounted_secrets_directory(monkeypatch, saubere_umgebung):
    """Der Haus-Weg: /run/secrets/<variable in klein>."""
    secrets = saubere_umgebung / "run-secrets"
    secrets.mkdir()
    (secrets / "groq_api_key").write_text("schluessel-aus-mount")
    monkeypatch.setenv("AIFW_SECRETS_DIR", str(secrets))

    assert _resolve_api_key(PROVIDER, VAR) == "schluessel-aus-mount"


def test_should_strip_trailing_newline_from_secret_file(monkeypatch, saubere_umgebung):
    """Der Zeilenumbruch ist der eigentliche Stolperstein.

    Eine per `echo` erzeugte Datei endet mit \\n. Ungestrippt landet der im
    Authorization-Header und der Provider antwortet mit derselben Meldung wie
    bei einem toten Schluessel.
    """
    datei = saubere_umgebung / "mit_umbruch"
    datei.write_text("schluessel-mit-umbruch\n")
    monkeypatch.setenv(f"{VAR}_FILE", str(datei))

    assert _resolve_api_key(PROVIDER, VAR) == "schluessel-mit-umbruch"


def test_should_fall_through_to_mount_when_var_file_is_missing(monkeypatch, saubere_umgebung):
    """Ein toter <VAR>_FILE-Pfad darf den Mount-Weg nicht blockieren."""
    secrets = saubere_umgebung / "run-secrets"
    secrets.mkdir()
    (secrets / "groq_api_key").write_text("schluessel-aus-mount")
    monkeypatch.setenv(f"{VAR}_FILE", str(saubere_umgebung / "gibt-es-nicht"))
    monkeypatch.setenv("AIFW_SECRETS_DIR", str(secrets))

    assert _resolve_api_key(PROVIDER, VAR) == "schluessel-aus-mount"


def test_should_return_empty_when_nothing_is_configured(saubere_umgebung):
    assert _resolve_api_key(PROVIDER, VAR) == ""


def test_should_use_provider_convention_when_action_has_no_env_var(monkeypatch, saubere_umgebung):
    """Ohne hinterlegten Variablennamen greift <PROVIDER>_API_KEY — auch als Datei."""
    secrets = saubere_umgebung / "run-secrets"
    secrets.mkdir()
    (secrets / "mistral_api_key").write_text("schluessel-mistral")
    monkeypatch.setenv("AIFW_SECRETS_DIR", str(secrets))

    assert _resolve_api_key("mistral", "") == "schluessel-mistral"


def test_should_return_empty_for_unknown_provider_without_var(saubere_umgebung):
    assert _resolve_api_key("", "") == ""


def test_should_not_crash_when_secret_path_is_a_directory(monkeypatch, saubere_umgebung):
    """Ein Verzeichnis statt einer Datei darf keine Exception werfen."""
    verzeichnis = saubere_umgebung / "kein_file"
    verzeichnis.mkdir()
    monkeypatch.setenv(f"{VAR}_FILE", str(verzeichnis))

    assert _resolve_api_key(PROVIDER, VAR) == ""
