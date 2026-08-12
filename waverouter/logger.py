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


class EventLogger:
    """Logger simple, thread-safe, avec diffusion vers l'UI."""

    def __init__(self, debug: bool = False) -> None:
        self.debug = debug
        self._lock = threading.Lock()
        self._callbacks: list[LogCallback] = []
        self._log_file: Path = get_logs_dir() / "app.log"

    def add_callback(self, callback: LogCallback) -> None:
        self._callbacks.append(callback)

    def _timestamp(self) -> str:
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _write(self, level: str, message: str) -> None:
        line = f"{self._timestamp()} - {message}"
        with self._lock:
            try:
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
