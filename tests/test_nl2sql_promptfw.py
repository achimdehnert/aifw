"""NL2SQL system-prompt resolution — promptfw first, builtin fallback (ADR-146).

The promptfw-backed tests use ``pytest.importorskip`` (testing convention
T-01): they run when the optional ``[promptfw]`` extra is installed (it is
part of ``[dev]``) and skip cleanly otherwise. The fallback test forces the
"promptfw not installed" path via ``sys.modules`` regardless of the
environment.
"""
import sys

import pytest

from aifw.nl2sql.engine import (
    PROMPTFW_ACTION_CODE,
    _builtin_system_prompt,
    _resolve_system_prompt,
)

CTX = {
    "question": "Wie viele Auftraege sind offen?",
    "blocked_tables": "auth_user, django_session",
    "max_rows": 100,
    "schema_xml": "<schema><table name='orders'/></schema>",
}


def _expected_builtin() -> str:
    return _builtin_system_prompt(
        CTX["blocked_tables"], CTX["max_rows"], CTX["schema_xml"]
    )


def test_should_fallback_to_builtin_prompt_without_promptfw(monkeypatch):
    """Without promptfw installed the behaviour is byte-identical to before."""
    # None in sys.modules ⇒ `import promptfw…` raises ImportError.
    monkeypatch.setitem(sys.modules, "promptfw", None)

    result = _resolve_system_prompt(**CTX)

    assert result == _expected_builtin()
    assert "auth_user, django_session" in result
    assert "<schema><table name='orders'/></schema>" in result


@pytest.mark.django_db
def test_should_use_promptfw_template_when_available():
    resolution = pytest.importorskip("promptfw.contrib.django.resolution")
    from promptfw.contrib.django.models import PromptTemplate

    resolution.invalidate_cache(PROMPTFW_ACTION_CODE)
    try:
        PromptTemplate.objects.create(
            action_code=PROMPTFW_ACTION_CODE,
            version=1,
            system_template="CUSTOM PROMPT max_rows={{ max_rows }}",
            user_template="{{ question }}",
        )
        result = _resolve_system_prompt(**CTX)
    finally:
        resolution.invalidate_cache(PROMPTFW_ACTION_CODE)

    assert result == "CUSTOM PROMPT max_rows=100"


@pytest.mark.django_db
def test_should_fallback_to_builtin_when_template_missing():
    """promptfw installed but no `nl2sql.system` row ⇒ builtin prompt."""
    resolution = pytest.importorskip("promptfw.contrib.django.resolution")

    resolution.invalidate_cache(PROMPTFW_ACTION_CODE)
    try:
        result = _resolve_system_prompt(**CTX)
    finally:
        resolution.invalidate_cache(PROMPTFW_ACTION_CODE)

    assert result == _expected_builtin()


@pytest.mark.django_db
def test_should_render_seeded_template_identical_to_builtin():
    """The seeded Jinja2 template renders the same content as the builtin."""
    resolution = pytest.importorskip("promptfw.contrib.django.resolution")
    from io import StringIO

    from django.core.management import call_command

    resolution.invalidate_cache(PROMPTFW_ACTION_CODE)
    try:
        call_command("init_aifw_config", stdout=StringIO())
        result = _resolve_system_prompt(**CTX)
    finally:
        resolution.invalidate_cache(PROMPTFW_ACTION_CODE)

    # render_prompt strips trailing whitespace — content must match otherwise.
    assert result == _expected_builtin().strip()
