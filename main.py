"""
Point d'entrée de WaveRouter 2.0.

Câble ensemble la configuration, le logger, le moteur de surveillance,
la fenêtre principale et l'icône de la barre système.

Le moteur (détection des processus, routage confirmé, découverte des jeux
installés) est identique à celui de la version 1 : seule l'interface change,
passée de CustomTkinter à Qt.

Usage :
    python main.py [--debug] [--minimized]
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from waverouter.audio_backend import AudioBackend
from waverouter.config import ConfigManager
from waverouter.logger import EventLogger
from waverouter.process_monitor import ProcessMonitor
from waverouter.single_instance import SingleInstance, show_already_running_message
from waverouter.ui.main_window import MainWindow
from waverouter.ui.tray import TrayIcon
from waverouter.ui.widgets import app_icon


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WaveRouter")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Active le mode debug/verbose (journalisation détaillée du scan).",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Démarre directement dans la barre système, sans ouvrir la fenêtre.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    lock = SingleInstance()
    if not lock.acquire():
        show_already_running_message()
        return 0

    try:
        return _run(args)
    finally:
        lock.release()


def _run(args: argparse.Namespace) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("WaveRouter")
    app.setWindowIcon(app_icon())
    # La fenêtre se réduit dans la barre système : sans cela, Qt quitterait
    # l'application dès la fermeture de la dernière fenêtre visible.
    app.setQuitOnLastWindowClosed(False)

    config_manager = ConfigManager()
    if args.debug:
        config_manager.config.settings.debug = True

    logger = EventLogger(debug=config_manager.config.settings.debug)

    def backend_factory() -> AudioBackend:
        return AudioBackend(config_manager.config.settings.soundvolumeview_path)

    # Les callbacks ci-dessous sont invoqués depuis le thread de
    # surveillance : ils se contentent d'émettre un signal Qt, que Qt délivre
    # sur le thread de l'interface. Ils se referment sur `window` et `tray`,
    # créés juste après, mais ne sont appelés qu'une fois le moteur démarré.
    def on_routed(label: str, channel: str) -> None:
        if config_manager.config.settings.notifications_enabled:
            tray.notify("WaveRouter", f"{label} → routé vers {channel}")
        window.routed.emit(label, channel)

    def on_game_candidate(process_name: str, exe_path: str, title: str) -> None:
        window.candidate_found.emit(process_name, exe_path, title)

    def on_state_changed() -> None:
        window.monitor_state_changed.emit()
        tray.update_menu()

    monitor = ProcessMonitor(
        config=config_manager.config,
        backend_factory=backend_factory,
        logger=logger,
        on_routed=on_routed,
        on_game_candidate=on_game_candidate,
        on_state_changed=on_state_changed,
    )

    window = MainWindow(
        config_manager=config_manager,
        monitor=monitor,
        logger=logger,
        backend_factory=backend_factory,
    )

    def quit_app() -> None:
        monitor.stop()
        window.prepare_quit()
        tray.hide()
        app.quit()

    tray = TrayIcon(
        parent=window,
        on_open=window.show_and_focus,
        on_toggle_pause=monitor.toggle_pause,
        is_paused=lambda: monitor.is_paused,
        on_quit=quit_app,
    )
    tray.show()

    logger.add_callback(window.log_line)

    if not args.minimized:
        window.show()

    logger.info("WaveRouter démarré.")
    monitor.start()
    window.refresh_monitor_state()

    code = app.exec()

    monitor.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
