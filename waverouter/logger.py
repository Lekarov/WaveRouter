"""
Journalisation des événements de WaveRouter.

Écrit dans un fichier log (%APPDATA%/DoktorP3st/WaveRouter/logs/app.log) et permet
d'enregistrer des callbacks pour afficher les événements en temps réel
dans l'interface graphique (panneau de logs).
"""

from __future__ import annotations

import datetime
import threading
from pathlib import Path
from typing import Callable

from waverouter.config import get_logs_dir

LogCallback = Callable[[str], None]

# WaveRouter est conçu pour tourner en permanence (démarrage Windows) : sans
# rotation, app.log grossit indéfiniment, d'autant plus vite en mode debug.
MAX_LOG_BYTES = 1_000_000
BACKUP_SUFFIX = ".1"

# Nombre de lignes relues au lancement pour réafficher l'historique récent.
TAIL_LINES = 200


class EventLogger:
    """Logger simple, thread-safe, avec diffusion vers l'UI."""

    def __init__(self, debug: bool = False) -> None:
        self.debug = debug
        self._lock = threading.Lock()
        self._callbacks: list[LogCallback] = []
        self._log_file: Path = get_logs_dir() / "app.log"

    @property
    def log_file(self) -> Path:
        return self._log_file

    def add_callback(self, callback: LogCallback) -> None:
        self._callbacks.append(callback)

    def _timestamp(self) -> str:
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _rotate_if_needed(self) -> None:
        """Bascule app.log vers app.log.1 une fois la taille maximale atteinte."""
        try:
            if self._log_file.stat().st_size < MAX_LOG_BYTES:
                return
        except OSError:
            return
        backup = self._log_file.with_suffix(self._log_file.suffix + BACKUP_SUFFIX)
        try:
            backup.unlink(missing_ok=True)
            self._log_file.replace(backup)
        except OSError:
            pass  # Rotation impossible (fichier verrouillé) : on continue d'écrire

    def _write(self, level: str, message: str) -> None:
        line = f"{self._timestamp()} - {message}"
        with self._lock:
            try:
                self._rotate_if_needed()
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(f"[{level}] {line}\n")
            except OSError:
                pass  # Ne jamais planter l'app pour un souci d'écriture de log
        for callback in list(self._callbacks):
            try:
                callback(line)
            except Exception:
                pass  # Un callback UI défaillant ne doit pas casser le logger

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def error(self, message: str) -> None:
        self._write("ERREUR", message)

    def debug_log(self, message: str) -> None:
        if self.debug:
            self._write("DEBUG", message)

    def read_recent_lines(self, count: int = TAIL_LINES) -> list[str]:
        """
        Retourne les dernières lignes du fichier de log, pour réafficher
        l'historique au lancement plutôt qu'un panneau vide.
        """
        try:
            with open(self._log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return []
        return [line.rstrip("\n") for line in lines[-count:] if line.strip()]
