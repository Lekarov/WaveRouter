"""
Gestion de la configuration persistante de WaveRouter.

La configuration est stockée en JSON dans
%APPDATA%/DoktorP3st/WaveRouter/config.json (dossier commun DoktorP3st
regroupant les données de tous les outils dev) et contient la liste des
jeux gérés ainsi que les réglages de l'application.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


def get_config_dir() -> Path:
    """Retourne le dossier %APPDATA%/DoktorP3st/WaveRouter, en le créant si besoin."""
    appdata = os.environ.get("APPDATA", str(Path.home()))
    config_dir = Path(appdata) / "DoktorP3st" / "WaveRouter"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


def get_logs_dir() -> Path:
    logs_dir = get_config_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


@dataclass
class GameEntry:
    """Représente un jeu géré par WaveRouter."""

    label: str
    process_name: str  # ex: "HuntGame-Win64-Shipping.exe"
    channel: str  # nom du périphérique Wave Link cible
    exe_path: str = ""  # chemin complet connu (pour extraire l'icône), optionnel

    def normalized_process_name(self) -> str:
        return self.process_name.strip().lower()


@dataclass
class Settings:
    """Réglages globaux de l'application."""

    soundvolumeview_path: str = ""
    poll_interval: float = 3.0
    notifications_enabled: bool = True
    autostart: bool = False
    debug: bool = False
    minimize_to_tray_on_close: bool = True


@dataclass
class AppConfig:
    """Configuration complète : jeux + réglages."""

    games: list[GameEntry] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "games": [asdict(g) for g in self.games],
            "settings": asdict(self.settings),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AppConfig":
        games = [
            GameEntry(
                label=g.get("label", ""),
                process_name=g.get("process_name", ""),
                channel=g.get("channel", ""),
                exe_path=g.get("exe_path", ""),
            )
            for g in data.get("games", [])
        ]
        settings_data = data.get("settings", {})
        settings = Settings(
            soundvolumeview_path=settings_data.get("soundvolumeview_path", ""),
            poll_interval=settings_data.get("poll_interval", 3.0),
            notifications_enabled=settings_data.get("notifications_enabled", True),
            autostart=settings_data.get("autostart", False),
            debug=settings_data.get("debug", False),
            minimize_to_tray_on_close=settings_data.get(
                "minimize_to_tray_on_close", True
            ),
        )
        return AppConfig(games=games, settings=settings)


class ConfigManager:
    """Charge/sauvegarde la configuration, thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.config = self.load()

    def load(self) -> AppConfig:
        path = get_config_path()
        if not path.exists():
            return AppConfig()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AppConfig.from_dict(data)
        except (json.JSONDecodeError, OSError):
            # Fichier corrompu ou illisible : on repart sur une config vide
            # plutôt que de planter l'application au démarrage.
            return AppConfig()

    def save(self) -> None:
        with self._lock:
            path = get_config_path()
            tmp_path = path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.config.to_dict(), f, ensure_ascii=False, indent=2)
            tmp_path.replace(path)
