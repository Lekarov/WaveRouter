"""
Moteur de surveillance en arrière-plan : détecte les processus de jeux
lancés et applique automatiquement le routage audio configuré.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

import psutil

from waverouter.audio_backend import AudioBackend, SoundVolumeViewError
from waverouter.config import AppConfig
from waverouter.logger import EventLogger

# Callback appelé après un routage réussi : (libellé_jeu, canal)
RoutedCallback = Callable[[str, str], None]


class ProcessMonitor:
    """Thread de fond qui scanne les processus actifs et route l'audio."""

    def __init__(
        self,
        config: AppConfig,
        backend_factory: Callable[[], AudioBackend],
        logger: EventLogger,
        on_routed: RoutedCallback | None = None,
    ) -> None:
        self._config = config
        self._backend_factory = backend_factory
        self._logger = logger
        self._on_routed = on_routed

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()  # set = en pause

        # Noms de process (en minuscules) déjà routés dans la session en cours,
        # pour éviter de réappliquer la commande à chaque scan.
        self._routed_processes: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="WaveRouterMonitor")
        self._thread.start()
        self._logger.info("Surveillance démarrée.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._logger.info("Surveillance arrêtée.")

    def pause(self) -> None:
        self._pause_event.set()
        self._logger.info("Surveillance mise en pause.")

    def resume(self) -> None:
        self._pause_event.clear()
        self._logger.info("Surveillance reprise.")

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            interval = max(1.0, float(self._config.settings.poll_interval))
            if not self._pause_event.is_set():
                try:
                    self._scan_once()
                except Exception as exc:  # ne jamais laisser le thread mourir silencieusement
                    self._logger.error(f"Erreur pendant le scan des processus : {exc}")
            self._stop_event.wait(interval)

    def _scan_once(self) -> None:
        games_by_process = {
            game.normalized_process_name(): game for game in self._config.games
        }
        if not games_by_process:
            return

        running_names: set[str] = set()
        for proc in psutil.process_iter(attrs=["name"]):
            name = (proc.info.get("name") or "").strip().lower()
            if name:
                running_names.add(name)

        self._logger.debug_log(
            f"Scan effectué : {len(running_names)} processus actifs, "
            f"{len(games_by_process)} jeu(x) surveillé(s)."
        )

        with self._lock:
            # Nettoyage des jeux qui ne tournent plus (permet de les
            # re-router s'ils sont relancés plus tard).
            closed = self._routed_processes - running_names
            for proc_name in closed:
                self._routed_processes.discard(proc_name)
                self._logger.debug_log(f"Processus fermé, marquage retiré : {proc_name}")

            for proc_name, game in games_by_process.items():
                if proc_name in running_names and proc_name not in self._routed_processes:
                    self._apply_routing(game.label, proc_name, game.channel)
                    self._routed_processes.add(proc_name)

    def _apply_routing(self, label: str, process_name: str, channel: str) -> None:
        backend = self._backend_factory()
        if not backend.is_available():
            self._logger.error(
                f"Impossible de router '{label}' : SoundVolumeView.exe introuvable."
            )
            return
        if not channel:
            self._logger.error(f"Impossible de router '{label}' : aucun canal configuré.")
            return
        try:
            backend.set_app_default_device(channel, process_name)
            self._logger.info(f"{process_name} détecté → routé vers {channel}")
            if self._on_routed:
                self._on_routed(label, channel)
        except SoundVolumeViewError as exc:
            self._logger.error(f"Échec du routage de '{label}' : {exc}")
        except Exception as exc:
            self._logger.error(f"Échec inattendu du routage de '{label}' : {exc}")
