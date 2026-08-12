"""
Backend audio : encapsule les appels à SoundVolumeView.exe (Nirsoft).

SoundVolumeView permet, entre autres, de définir le périphérique de sortie
par défaut pour une application spécifique via la fonctionnalité Windows
"App volume and device preferences" :

    SoundVolumeView.exe /SetAppDefault "<Nom du périphérique>" all app.exe

Il permet aussi de lister tous les périphériques/sessions audio via :

    SoundVolumeView.exe /scomma "sortie.csv"
"""

from __future__ import annotations

import csv
import subprocess
import tempfile
from pathlib import Path

# Lien officiel de téléchargement de SoundVolumeView (Nirsoft)
SOUNDVOLUMEVIEW_DOWNLOAD_URL = "https://www.nirsoft.net/utils/sound_volume_view.html"

# Flag Windows pour éviter l'ouverture d'une fenêtre console lors des appels
_CREATE_NO_WINDOW = 0x08000000


class SoundVolumeViewError(Exception):
    """Erreur levée quand SoundVolumeView est introuvable ou échoue."""


class AudioBackend:
    """Enveloppe les commandes SoundVolumeView utilisées par WaveRouter."""

    def __init__(self, executable_path: str) -> None:
        self.executable_path = executable_path

    def is_available(self) -> bool:
        return bool(self.executable_path) and Path(self.executable_path).is_file()

    def _run(self, args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
        if not self.is_available():
            raise SoundVolumeViewError(
                "SoundVolumeView.exe introuvable. Vérifiez le chemin configuré "
                "dans les réglages."
            )
        cmd = [self.executable_path, *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )

    def set_app_default_device(self, device_name: str, process_name: str) -> None:
        """
        Force le périphérique de sortie par défaut d'une application donnée.

        `device_name` doit correspondre au nom du périphérique tel que
        rapporté par Windows (ex: "Wave Link - Games (Elgato Wave Link)").
        `process_name` est le nom de l'exécutable (ex: "jeu.exe").
        """
        # "all" applique le changement pour les 3 rôles (multimédia,
        # console et communications) afin de couvrir tous les cas de jeux.
        self._run(["/SetAppDefault", device_name, "all", process_name])

    def list_devices(self) -> list[dict[str, str]]:
        """
        Retourne la liste brute des périphériques/sessions audio connus
        de SoundVolumeView, sous forme de liste de dictionnaires (colonnes
        du CSV exporté).
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "waverouter_devices.csv"
            self._run(["/scomma", str(csv_path)], timeout=15.0)
            if not csv_path.exists():
                raise SoundVolumeViewError(
                    "SoundVolumeView n'a pas produit de fichier d'export. "
                    "Vérifiez que l'exécutable fonctionne correctement."
                )
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                return list(reader)
