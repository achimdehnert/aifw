"""Regression: aifw-Import darf litellm nicht mitladen (platform#1899).

Der volle litellm-Import kostet ~190 MiB RSS; er gehoert nicht in den
Django-Boot-Pfad. In-Prozess laesst sich das nicht pruefen, weil andere
Tests litellm bereits geladen haben — daher Subprozess.
"""

import os
import pathlib
import subprocess
import sys

import aifw

_PROBE = (
    "import sys; import aifw, aifw.cost, aifw.service; "
    "sys.exit(1 if 'litellm' in sys.modules else 0)"
)


def test_should_not_load_litellm_on_package_import():
    # pytest-cov-Subprozess-Hooks stoeren die Probe — Coverage-Env entfernen.
    env = {k: v for k, v in os.environ.items() if not k.startswith("COV_CORE")}
    # Subprozess erbt pytests sys.path nicht — aifw-Paketwurzel explizit mitgeben.
    pkg_root = str(pathlib.Path(aifw.__file__).resolve().parent.parent)
    env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"litellm im Import-Pfad: {result.stderr}"
