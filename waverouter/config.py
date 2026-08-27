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
    enabled: bool = True  # permet de suspendre un jeu sans le supprimer

    def normalized_process_name(self) -> str:
        return self.process_name.strip().lower()


@dataclass
class Settings:
    """Réglages globaux de l'application."""

    soundvolumeview_path: str = ""
    poll_interval: float = 1.0
    notifications_enabled: bool = True
    autostart: bool = False
    debug: bool = False
    minimize_to_tray_on_close: bool = True
    # Canal appliqué aux jeux détectés automatiquement mais non configurés.
    # Vide = aucun routage par défaut.
    default_channel: str = ""
    # Propose l'ajout des applications inconnues qui ouvrent une session audio
    # tout en occupant une fenêtre de la taille de l'écran (signature d'un jeu).
    auto_detect_games: bool = True
    # Durée pendant laquelle on retente/vérifie le routage après le lancement
    # d'un jeu, le temps que son moteur audio ouvre réellement sa session.
    routing_confirm_seconds: float = 60.0


# Version 2 : le moteur de surveillance est passé au scan différentiel, bien
# moins coûteux que le balayage complet d'origine. L'intervalle hérité de
# l'ancien moteur (3 s) est donc ramené une seule fois à la nouvelle valeur,
# qui détecte les jeux presque au moment de leur lancement.
CONFIG_VERSION = 2
_LEGACY_POLL_INTERVAL = 3.0


@dataclass
class AppConfig:
    """Configuration complète : jeux + réglages."""

    games: list[GameEntry] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)
    # Process refusés par l'utilisateur lors de la détection automatique :
    # on ne les repropose plus (stockés en minuscules).
    ignored_processes: list[str] = field(default_factory=list)
    # Dossiers de jeux ajoutés à la main, parcourus à chaque import en plus
    # des bibliothèques Steam, Epic Games et GOG.
    game_folders: list[str] = field(default_factory=list)
    version: int = CONFIG_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "games": [asdict(g) for g in self.games],
            "settings": asdict(self.settings),
            "ignored_processes": list(self.ignored_processes),
            "game_folders": list(self.game_folders),
        }

    def add_game_folder(self, folder: str) -> bool:
        """Mémorise un dossier de jeux. Retourne False s'il y était déjà."""
        cleaned = folder.strip().rstrip("\\/")
        if not cleaned:
            return False
        existing = {f.lower() for f in self.game_folders}
        if cleaned.lower() in existing:
            return False
        self.game_folders.append(cleaned)
        return True

    def find_game(self, process_name: str) -> GameEntry | None:
        """Retourne le jeu configuré pour ce process, insensible à la casse."""
        target = process_name.strip().lower()
        for game in self.games:
            if game.normalized_process_name() == target:
                return game
        return None

    def is_ignored(self, process_name: str) -> bool:
        return process_name.strip().lower() in self.ignored_processes

    def ignore_process(self, process_name: str) -> None:
        normalized = process_name.strip().lower()
        if normalized and normalized not in self.ignored_processes:
            self.ignored_processes.append(normalized)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AppConfig":
        games = [
            GameEntry(
                label=g.get("label", ""),
                process_name=g.get("process_name", ""),
                channel=g.get("channel", ""),
                exe_path=g.get("exe_path", ""),
                enabled=bool(g.get("enabled", True)),
            )
            for g in data.get("games", [])
            if isinstance(g, dict) and g.get("process_name")
        ]
        settings_data = data.get("settings", {})
        if not isinstance(settings_data, dict):
            settings_data = {}
        defaults = Settings()
        settings = Settings(
            soundvolumeview_path=settings_data.get("soundvolumeview_path", ""),
            poll_interval=_as_float(
                settings_data.get("poll_interval"), defaults.poll_interval, minimum=0.5
            ),
            notifications_enabled=bool(settings_data.get("notifications_enabled", True)),
            autostart=bool(settings_data.get("autostart", False)),
            debug=bool(settings_data.get("debug", False)),
            minimize_to_tray_on_close=bool(
                settings_data.get("minimize_to_tray_on_close", True)
            ),
            default_channel=settings_data.get("default_channel", ""),
            auto_detect_games=bool(settings_data.get("auto_detect_games", True)),
            routing_confirm_seconds=_as_float(
                settings_data.get("routing_confirm_seconds"),
                defaults.routing_confirm_seconds,
                minimum=0.0,
            ),
        )
        ignored = [
            str(p).strip().lower()
            for p in data.get("ignored_processes", [])
            if str(p).strip()
        ]

        try:
            version = int(data.get("version", 1))
        except (TypeError, ValueError):
            version = 1
        if version < 2 and settings.poll_interval == _LEGACY_POLL_INTERVAL:
            settings.poll_interval = defaults.poll_interval

        folders = [
            str(f).strip().rstrip("\\/")
            for f in data.get("game_folders", [])
            if str(f).strip()
        ]

        return AppConfig(
            games=games,
            settings=settings,
            ignored_processes=ignored,
            game_folders=folders,
            version=CONFIG_VERSION,
        )


def _as_float(value: Any, fallback: float, minimum: float = 0.0) -> float:
    """Convertit une valeur de config en float, en retombant sur le défaut."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    if result != result:  # NaN
        return fallback
    return max(minimum, result)


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
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # Fichier corrompu ou illisible : on repart sur une config vide
            # plutôt que de planter l'application au démarrage.
            return AppConfig()
        if not isinstance(data, dict):
            return AppConfig()
        return AppConfig.from_dict(data)

    def save(self) -> None:
        """
        Écrit la configuration de façon atomique.

        Le flush + fsync avant le remplacement évite de retrouver un
        config.json tronqué ou vide après une coupure de courant ou un arrêt
        brutal de Windows, cas réaliste pour une application qui tourne en
        permanence en arrière-plan.
        """
        with self._lock:
            path = get_config_path()
            tmp_path = path.with_suffix(".tmp")
            payload = self.config.to_dict()
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(path)
