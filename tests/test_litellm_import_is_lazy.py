"""Waechter: aifw darf litellm nicht beim Import mitziehen.

``import litellm`` kostet rund 176 MB (gemessen 2026-08-10: 12 MB -> 188 MB).
Solange das auf Modulebene stand, trug jeder Prozess diese Grundlast, der aifw
ueber ``AppConfig.ready()`` laedt — auch ein ``celery beat``, der nie ein
Modell aufruft. Realfall tax-hub: beat lief mit 128 MB Limit sofort in
OOMKilled (ExitCode 137, RestartCount 10), web stand bei 98,9 % seines Limits.

Der Test laeuft in einem **Subprozess**: im laufenden pytest hat schon
irgendein anderer Test litellm importiert, ``sys.modules`` waere dort also
immer belegt und die Pruefung wertlos.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap


def _in_fresh_interpreter(code: str) -> str:
    """Fuehrt `code` in einem frischen Interpreter mit DEMSELBEN aifw aus.

    Der Subprozess erbt pytests sys.path-Anpassung nicht. Ohne die explizite
    PYTHONPATH-Bruecke wuerde er ein evtl. installiertes aifw aus
    site-packages importieren statt des Quellbaums — der Test pruefte dann
    eine andere Version als die, die gerade geaendert wurde.
    """
    import aifw

    paket_wurzel = str(pathlib.Path(aifw.__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [paket_wurzel, *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )

    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_should_not_import_litellm_when_importing_aifw():
    ausgabe = _in_fresh_interpreter(
        """
        import sys
        import aifw  # noqa: F401
        print("litellm" in sys.modules)
        """
    )
    assert ausgabe == "False", (
        "import aifw zieht litellm mit — das kostet rund 176 MB in JEDEM "
        "Prozess, auch in celery beat. Den Import lazy halten (aifw.service."
        "_litellm / aifw.cost._litellm)."
    )


def test_should_not_import_litellm_when_importing_service_module():
    ausgabe = _in_fresh_interpreter(
        """
        import sys
        from aifw import cost, service  # noqa: F401
        print("litellm" in sys.modules)
        """
    )
    assert ausgabe == "False", (
        "aifw.service oder aifw.cost zieht litellm auf Modulebene — siehe "
        "Modul-Docstring dieses Tests."
    )


def test_should_import_litellm_only_on_first_real_use():
    """Die Gegenrichtung: der Accessor muss das Modul auch wirklich liefern."""
    ausgabe = _in_fresh_interpreter(
        """
        import sys
        from aifw import service
        vorher = "litellm" in sys.modules
        modul = service._litellm()
        print(vorher, "litellm" in sys.modules, modul.__name__)
        """
    )
    assert ausgabe == "False True litellm"
