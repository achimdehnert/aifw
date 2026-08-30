"""Die Cache-Invalidierung feuert wirklich — gemessen, nicht angenommen.

Herkunft: writing-hub#766 (platform:KONZ-platform-051). Ein Reseed auf einen
anderen Provider wirkte bis zu zehn Minuten nicht, waehrend die Fehlermeldung
bereits den neuen Provider nannte. Ursache war nicht der Konsument, sondern
diese Datei: die Empfaenger in :func:`_connect_signals` sind lokale Funktionen,
und mit Djangos Vorgabe ``weak=True`` starben sie beim Verlassen der Funktion.

Gemessen am 2026-08-30, bevor der Fix stand: ``post_save.receivers`` trug 4
Eintraege, ``_live_receivers`` lieferte ``[]``, und ein Cache-Key ueberlebte ein
``save(update_fields=[...])``. Der Test unten haelt genau diese drei Messungen
fest — die Anwesenheit eines Eintrags ist ausdruecklich **kein** Beleg dafuer,
dass er feuert.
"""

from __future__ import annotations

import time
import weakref

import pytest
from django.db.models.signals import post_delete, post_save

from aifw.service import _LOCAL_CACHE, _action_cache_key

pytestmark = pytest.mark.django_db


def _lebende_empfaenger(signal, sender) -> list[str]:
    empfaenger = signal._live_receivers(sender=sender)
    if isinstance(empfaenger, tuple):  # Django 5 liefert (sync, async)
        empfaenger = [f for teil in empfaenger for f in teil]
    return [getattr(f, "__name__", str(f)) for f in empfaenger]


def _tote_eintraege(signal) -> int:
    tot = 0
    for eintrag in signal.receivers:
        ref = eintrag[1]
        ziel = ref() if isinstance(ref, weakref.ReferenceType) else ref
        if ziel is None:
            tot += 1
    return tot


@pytest.mark.parametrize("signal", [post_save, post_delete], ids=["post_save", "post_delete"])
def test_should_keep_a_live_receiver_for_action_types(signal):
    """Ein Eintrag in der Liste ist kein feuernder Empfaenger."""
    from aifw.models import AIActionType

    namen = _lebende_empfaenger(signal, AIActionType)

    assert namen, (
        "Kein LEBENDER Empfaenger fuer AIActionType. Die Eintraege koennen trotzdem in "
        "signal.receivers stehen — als tote Weakrefs. Genau dieser Zustand liess einen "
        "Reseed bis AIFW_CACHE_TTL (600 s) wirkungslos (writing-hub#766). Fix: weak=False."
    )


def test_should_not_leave_dead_weakrefs_behind():
    """Die Gegenprobe zur Anwesenheit: keiner der Eintraege darf tot sein."""
    assert _tote_eintraege(post_save) == 0, (
        f"{_tote_eintraege(post_save)} tote Weakref-Eintraege in post_save — "
        "verbundene Empfaenger, deren Ziel schon weg ist."
    )


def test_should_clear_the_cached_config_when_an_action_is_saved():
    """Der Wirknachweis: nach einem `save()` ist der Schluessel weg.

    Ohne diesen Test bliebe der Fix eine Behauptung ueber Django-Interna —
    hier zaehlt der Cache-Inhalt, nicht die Empfaengerliste.
    """
    from aifw.models import AIActionType, LLMModel, LLMProvider

    provider = LLMProvider.objects.create(name="probe", api_key_env_var="PROBE_KEY", is_active=True)
    modell = LLMModel.objects.create(provider=provider, name="mini")
    aktion = AIActionType.objects.create(
        code="probe_code", quality_level=None, priority=None, name="Probe", default_model=modell
    )

    schluessel = _action_cache_key("probe_code", None, None)
    _LOCAL_CACHE[schluessel] = ("ALTWERT", time.monotonic())
    assert schluessel in _LOCAL_CACHE, "Vorbedingung: der Schluessel liegt im Cache"

    aktion.name = "Probe 2"
    aktion.save(update_fields=["name"])

    assert schluessel not in _LOCAL_CACHE, (
        "Der Cache-Eintrag hat das save() ueberlebt — die Invalidierung feuert nicht. "
        "Das ist der Zustand aus writing-hub#766: die DB traegt die neue Verdrahtung, "
        "der naechste Aufruf nimmt die alte."
    )


def test_should_clear_everything_when_a_provider_changes():
    """Zweiter Fall derselben Klasse: Provider/Modell raeumen den ganzen Cache."""
    from aifw.models import LLMProvider

    provider = LLMProvider.objects.create(
        name="probe2", api_key_env_var="PROBE2_KEY", is_active=True
    )
    _LOCAL_CACHE[_action_cache_key("irgendein_code", None, None)] = ("ALTWERT", time.monotonic())

    provider.display_name = "Probe 2"
    provider.save(update_fields=["display_name"])

    assert not _LOCAL_CACHE, (
        "Eine Provider-Aenderung kann jede Aktion betreffen — der Cache muss leer sein"
    )
