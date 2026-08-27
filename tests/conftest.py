"""
Configuration commune des tests.

Les modules de WaveRouter créent leur dossier de configuration à l'import
(`get_config_dir`). On redirige APPDATA vers un dossier temporaire avant tout
import de code applicatif, pour qu'aucun test ne touche à la configuration
réelle de l'utilisateur.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TEMP_APPDATA = tempfile.mkdtemp(prefix="waverouter-tests-")
os.environ["APPDATA"] = _TEMP_APPDATA

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def config_dir(tmp_path, monkeypatch) -> Path:
    """Isole la configuration d'un test dans son propre dossier."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path / "DoktorP3st" / "WaveRouter"
