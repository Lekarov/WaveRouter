"""
Point d'entrée de WaveRouter.

Câble ensemble la configuration, le logger, le moteur de surveillance,
la fenêtre principale et l'icône de la barre système.

Usage :
    python main.py [--debug]
"""

from __future__ import annotations

import argparse
import sys

from waverouter.audio_backend import AudioBackend
from waverouter.config import ConfigManager
from waverouter.logger import EventLogger
from waverouter.process_monitor import ProcessMonitor
from waverouter.ui.main_window import MainWindow
from waverouter.ui.tray import TrayIcon


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WaveRouter")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Active le mode debug/verbose (journalisation détaillée du scan).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    config_manager = ConfigManager()
    if args.debug:
        config_manager.config.settings.debug = True

    logger = EventLogger(debug=config_manager.config.settings.debug)

    def backend_factory() -> AudioBackend:
        return AudioBackend(config_manager.config.settings.soundvolumeview_path)

    def on_routed(label: str, channel: str) -> None:
        if config_manager.config.settings.notifications_enabled:
            TrayIcon.notify("WaveRouter", f"{label} → routé vers {channel}")
        # Appelé depuis le thread de surveillance : on repasse par `after`
        # pour mettre à jour le tableau de bord sur le thread principal Tk.
        window.after(0, window.on_game_routed, label, channel)

    monitor = ProcessMonitor(
        config=config_manager.config,
        backend_factory=backend_factory,
        logger=logger,
        on_routed=on_routed,
    )

    def open_window() -> None:
        # Appelé depuis le thread de l'icône système : on passe par `after`
        # pour rester sur le thread principal Tkinter.
        window.after(0, window.show_and_focus)

    def toggle_pause() -> bool:
        if monitor.is_paused:
            monitor.resume()
        else:
            monitor.pause()
        window.after(0, window.refresh_dashboard)
        return monitor.is_paused

    def quit_app() -> None:
        def do_quit() -> None:
            monitor.stop()
            window.destroy()

        window.after(0, do_quit)

    def minimize_to_tray() -> None:
        pass  # La fenêtre est déjà retirée (withdraw) par MainWindow._handle_close

    window = MainWindow(
        config_manager=config_manager,
        monitor=monitor,
        logger=logger,
        backend_factory=backend_factory,
        on_close_to_tray=minimize_to_tray,
    )
    logger.add_callback(window.log_line)

    tray = TrayIcon(on_open=open_window, on_toggle_pause=toggle_pause, on_quit=quit_app)
    tray.run_detached()

    logger.info("WaveRouter démarré.")
    monitor.start()

    window.mainloop()

    # La boucle Tk s'est terminée (fermeture définitive) : on nettoie le reste.
    monitor.stop()
    tray.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
