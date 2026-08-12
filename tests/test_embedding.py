"""Tests fuer aifw.embedding — litellm gemockt, keine echten API-Aufrufe.

Der Schwerpunkt liegt auf den drei Stellen, an denen ein Embedding-Aufruf
lautlos falsch werden kann: falsche Parameter am Endpunkt, vertauschte
Zuordnung Vektor↔Text, und ein Fehlschlag, der als Ausnahme statt als Ergebnis
zurueckkommt und damit einen Lauf ueber Zehntausende Textstuecke abreisst.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aifw.schema import EmbeddingResult
from aifw.service import _build_embedding_kwargs, embedding, sync_embedding

CONFIG = {
    "model_string": "text-embedding-3-large",
    "api_key": "sk-test-123",
    "api_base": None,
    "max_tokens": 2000,
    "temperature": 0.7,
    "action_id": None,
    "model_id": None,
}


def _antwort(vektoren, tokens=42, model="text-embedding-3-large", reihenfolge=None):
    """Provider-Antwort nachbilden; `reihenfolge` setzt die index-Werte."""
    indizes = reihenfolge if reihenfolge is not None else list(range(len(vektoren)))
    antwort = MagicMock()
    antwort.data = [{"index": i, "embedding": v} for i, v in zip(indizes, vektoren, strict=True)]
    antwort.model = model
    antwort.usage = MagicMock(prompt_tokens=tokens, total_tokens=tokens)
    return antwort


class TestBuildEmbeddingKwargs:
    def test_should_not_send_completion_only_parameters(self):
        """`max_tokens`/`temperature` sind am Embedding-Endpunkt ungueltig (400)."""
        kwargs = _build_embedding_kwargs(CONFIG, ["a", "b"], {})

        assert "max_tokens" not in kwargs
        assert "temperature" not in kwargs
        assert kwargs["input"] == ["a", "b"]
        assert kwargs["model"] == "text-embedding-3-large"
        assert kwargs["api_key"] == "sk-test-123"

    def test_should_pass_through_provider_options(self):
        kwargs = _build_embedding_kwargs(CONFIG, ["a"], {"dimensions": 1024})

        assert kwargs["dimensions"] == 1024

    def test_should_let_the_key_follow_a_model_override(self, monkeypatch):
        """Dieselbe Regel wie bei Completions (aifw#37): Schluessel folgt Modell."""
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-mistral")

        kwargs = _build_embedding_kwargs(CONFIG, ["a"], {"model": "mistral/mistral-embed"})

        assert kwargs["model"] == "mistral/mistral-embed"
        assert kwargs["api_key"] == "sk-mistral"

    def test_should_omit_api_base_when_not_configured(self):
        assert "api_base" not in _build_embedding_kwargs(CONFIG, ["a"], {})


@pytest.mark.asyncio
class TestEmbedding:
    async def test_should_return_vectors_in_input_order(self):
        """Der Provider darf durcheinander antworten — die Zuordnung nicht.

        Ein vertauschter Vektor faellt nie als Fehler auf: die Suche wird nur
        schlechter. Deshalb wird nach `index` sortiert statt der Reihenfolge
        der Antwort zu vertrauen.
        """
        antwort = _antwort([[0.3], [0.1], [0.2]], reihenfolge=[2, 0, 1])

        with (
            patch("aifw.service.get_model_config", AsyncMock(return_value=CONFIG)),
            patch("aifw.service._log_usage", AsyncMock(return_value="log-1")),
            patch("aifw.service._aembedding_with_retry", AsyncMock(return_value=antwort)),
        ):
            ergebnis = await embedding("recherche_embedding", ["a", "b", "c"])

        assert ergebnis.success is True
        assert ergebnis.vectors == [[0.1], [0.2], [0.3]]
        assert ergebnis.call_id == "log-1"

    async def test_should_accept_a_single_string(self):
        with (
            patch("aifw.service.get_model_config", AsyncMock(return_value=CONFIG)),
            patch("aifw.service._log_usage", AsyncMock(return_value="")),
            patch(
                "aifw.service._aembedding_with_retry",
                AsyncMock(return_value=_antwort([[0.1, 0.2]])),
            ),
        ):
            ergebnis = await embedding("recherche_embedding", "ein Text")

        assert ergebnis.dimensions == 2
        assert len(ergebnis.vectors) == 1

    async def test_should_report_failure_as_result_not_exception(self):
        """Ein Stapel darf scheitern, ohne den ganzen Lauf mitzunehmen."""
        with (
            patch("aifw.service.get_model_config", AsyncMock(return_value=CONFIG)),
            patch("aifw.service._log_usage", AsyncMock(return_value="")),
            patch(
                "aifw.service._aembedding_with_retry",
                AsyncMock(side_effect=RuntimeError("rate limited")),
            ),
        ):
            ergebnis = await embedding("recherche_embedding", ["a"])

        assert ergebnis.success is False
        assert "rate limited" in ergebnis.error
        assert ergebnis.vectors == []

    async def test_should_fail_gracefully_without_a_configured_model(self):
        with patch("aifw.service.get_model_config", AsyncMock(return_value={"model_string": ""})):
            ergebnis = await embedding("unbekannt", ["a"])

        assert ergebnis.success is False
        assert "No model configured" in ergebnis.error

    async def test_should_reject_an_empty_input_list(self):
        ergebnis = await embedding("recherche_embedding", [])

        assert ergebnis.success is False
        assert ergebnis.vectors == []

    async def test_should_count_input_tokens_for_cost_tracking(self):
        with (
            patch("aifw.service.get_model_config", AsyncMock(return_value=CONFIG)),
            patch("aifw.service._log_usage", AsyncMock(return_value="")),
            patch(
                "aifw.service._aembedding_with_retry",
                AsyncMock(return_value=_antwort([[0.1]], tokens=1234)),
            ),
        ):
            ergebnis = await embedding("recherche_embedding", ["a"])

        assert ergebnis.input_tokens == 1234
        assert ergebnis.total_tokens == 1234


class TestSyncEmbedding:
    def test_should_work_outside_an_event_loop(self):
        with (
            patch("aifw.service.get_model_config", AsyncMock(return_value=CONFIG)),
            patch("aifw.service._log_usage", AsyncMock(return_value="")),
            patch(
                "aifw.service._aembedding_with_retry",
                AsyncMock(return_value=_antwort([[0.5]])),
            ),
        ):
            ergebnis = sync_embedding("recherche_embedding", ["a"])

        assert ergebnis.success is True
        assert ergebnis.vectors == [[0.5]]


class TestEmbeddingResult:
    def test_should_report_dimensions_of_the_first_vector(self):
        assert EmbeddingResult(success=True, vectors=[[0.0] * 3072]).dimensions == 3072

    def test_should_report_zero_dimensions_when_empty(self):
        assert EmbeddingResult(success=False).dimensions == 0
