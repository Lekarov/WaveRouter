"""
Backend audio : encapsule les appels à SoundVolumeView.exe (Nirsoft).

SoundVolumeView permet, entre autres, de définir le périphérique de sortie
par défaut pour une application spécifique via la fonctionnalité Windows
"App volume and device preferences" :

    SoundVolumeView.exe /SetAppDefault "<Nom du périphérique>" all app.exe

Il permet aussi de lister tous les périphériques/sessions audio via :

    SoundVolumeView.exe /scomma "sortie.csv"

Point clé pour la fiabilité du routage : `/SetAppDefault` enregistre une
préférence Windows persistante, mais une session audio DÉJÀ ouverte par
l'application continue de sortir sur l'ancien périphérique. La seule
vérification fiable consiste donc à relire les sessions applicatives
(`list_app_sessions`) et à comparer le périphérique réellement utilisé.
"""

from __future__ import annotations

import csv
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath

# Lien officiel de téléchargement de SoundVolumeView (Nirsoft)
SOUNDVOLUMEVIEW_DOWNLOAD_URL = "https://www.nirsoft.net/utils/sound_volume_view.html"

# Flag Windows pour éviter l'ouverture d'une fenêtre console lors des appels
_CREATE_NO_WINDOW = 0x08000000

# SoundVolumeView écrit son CSV en UTF-8 quand l'option Unicode est active,
# en ANSI sinon : on tente les deux plutôt que d'échouer sur un nom de
# périphérique accentué ("Haut-parleurs (Realtek®)").
_CSV_ENCODINGS = ("utf-8-sig", "cp1252")


class SoundVolumeViewError(Exception):
    """Erreur levée quand SoundVolumeView est introuvable ou échoue."""


@dataclass(frozen=True)
class AppSession:
    """Session audio d'une application, telle que rapportée par SoundVolumeView."""

    process_name: str  # ex: "jeu.exe"
    pid: int  # 0 si non rapporté
    device_name: str  # périphérique de sortie réellement utilisé
    process_path: str = ""


class AudioBackend:
    """Enveloppe les commandes SoundVolumeView utilisées par WaveRouter."""

    def __init__(self, executable_path: str) -> None:
        self.executable_path = executable_path

    def is_available(self) -> bool:
        return bool(self.executable_path) and Path(self.executable_path).is_file()

    def _run(self, args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
        """
        Lance SoundVolumeView et vérifie qu'il s'est terminé correctement.

        Toutes les défaillances possibles (exécutable absent, timeout, erreur
        système, code de sortie non nul) sont converties en
        SoundVolumeViewError : les appelants n'ont qu'un seul type d'exception
        à gérer, y compris ceux qui tournent sur le thread de l'interface.
        """
        if not self.is_available():
            raise SoundVolumeViewError(
                "SoundVolumeView.exe introuvable. Vérifiez le chemin configuré "
                "dans les réglages."
            )
        cmd = [self.executable_path, *args]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise SoundVolumeViewError(
                f"SoundVolumeView n'a pas répondu en moins de {timeout:.0f} s."
            ) from exc
        except OSError as exc:
            raise SoundVolumeViewError(
                f"Impossible de lancer SoundVolumeView : {exc}"
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
            suffix = f" ({detail})" if detail else ""
            raise SoundVolumeViewError(
                f"SoundVolumeView a échoué (code {completed.returncode}){suffix}."
            )
        return completed

    def set_app_default_device(self, device_name: str, process_name: str) -> None:
        """
        Force le périphérique de sortie par défaut d'une application donnée.

        `device_name` doit correspondre au nom du périphérique tel que
        rapporté par Windows (ex: "Games!" pour un canal Wave Link).
        `process_name` est le nom de l'exécutable (ex: "jeu.exe").
        """
        # "all" applique le changement pour les 3 rôles (multimédia,
        # console et communications) afin de couvrir tous les cas de jeux.
        self._run(["/SetAppDefault", device_name, "all", process_name])

    def _read_csv(self, csv_path: Path) -> list[dict[str, str]]:
        last_error: Exception | None = None
        for encoding in _CSV_ENCODINGS:
            try:
                with open(csv_path, "r", encoding=encoding, newline="") as f:
                    return list(csv.DictReader(f))
            except UnicodeDecodeError as exc:
                last_error = exc
        raise SoundVolumeViewError(
            f"Export SoundVolumeView illisible (encodage inattendu) : {last_error}"
        )

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
            return self._read_csv(csv_path)

    def list_app_sessions(self) -> list[AppSession]:
        """
        Retourne les sessions audio applicatives de sortie actuellement
        ouvertes, avec le canal sur lequel chacune sort réellement.

        C'est la source de vérité pour confirmer qu'un routage a bien été
        pris en compte : `/SetAppDefault` peut réussir alors que la session
        déjà ouverte continue de sortir ailleurs.

        Deux pièges du format de SoundVolumeView sont traités ici, et ils
        rendent les colonnes évidentes inutilisables :

        - Pour une session applicative, la colonne `Name` contient le nom
          commercial de l'application ("Brave Browser"), pas le nom de son
          exécutable. Seul `Process Path` permet de retrouver `brave.exe`.
        - La colonne `Device Name` désigne la carte son ("Elgato Virtual
          Audio"), commune à TOUS les canaux Wave Link. Elle ne distingue
          donc pas "Games!" de "Music". Le canal exact ne s'obtient qu'en
          reliant le préfixe de l'`Item ID` de la session à l'`Item ID` du
          périphérique correspondant.
        """
        rows = self.list_devices()

        endpoints: dict[str, str] = {}
        for row in rows:
            if (row.get("Type") or "").strip().lower() != "device":
                continue
            if (row.get("Direction") or "").strip().lower() != "render":
                continue
            item_id = (row.get("Item ID") or "").strip()
            name = (row.get("Name") or "").strip()
            if item_id and name:
                endpoints[item_id] = name

        sessions: list[AppSession] = []
        for row in rows:
            if (row.get("Type") or "").strip().lower() != "application":
                continue
            if (row.get("Direction") or "").strip().lower() != "render":
                continue

            process_path = (row.get("Process Path") or "").strip()
            if not process_path:
                continue  # sons système : aucun processus à router

            # L'Item ID d'une session vaut "<item id du périphérique>|<...>".
            device_item_id = (row.get("Item ID") or "").split("|", 1)[0].strip()
            device_name = endpoints.get(device_item_id, "")
            if not device_name:
                continue  # périphérique disparu entre-temps

            try:
                pid = int((row.get("Process ID") or "0").strip() or 0)
            except ValueError:
                pid = 0

            sessions.append(
                AppSession(
                    process_name=PurePath(process_path).name,
                    pid=pid,
                    device_name=device_name,
                    process_path=process_path,
                )
            )
        return sessions

    def find_app_sessions(self, process_name: str, pid: int | None = None) -> list[AppSession]:
        """
        Retourne toutes les sessions audio de sortie d'un process donné.

        Une même application peut détenir des sessions sur plusieurs canaux
        à la fois (sessions résiduelles d'un périphérique utilisé plus tôt) :
        l'appelant doit donc raisonner sur l'ensemble, et non sur une session
        unique choisie arbitrairement.
        """
        target = process_name.strip().lower()
        matching = [
            session
            for session in self.list_app_sessions()
            if session.process_name.strip().lower() == target
        ]
        if pid is None:
            return matching
        # Le PID départage plusieurs instances du même exécutable, mais
        # SoundVolumeView ne le renseigne pas toujours : sans correspondance
        # exacte, on garde l'ensemble plutôt que de conclure à tort à l'absence.
        by_pid = [session for session in matching if session.pid == pid]
        return by_pid or matching
