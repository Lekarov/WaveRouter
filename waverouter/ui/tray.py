"""
Icône de la barre système : ouvrir la fenêtre, mettre la surveillance en
pause, quitter l'application.

Qt fournit nativement l'icône et les notifications, là où la version 1
devait combiner deux bibliothèques externes : pystray, avec sa propre
boucle d'événements dans un thread séparé, et plyer, qui écrivait une
icône temporaire sur le disque à chaque notification. Tout se déroule
désormais sur la boucle Qt, sans thread ni fichier intermédiaire.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from waverouter.ui import theme
from waverouter.ui.widgets import app_icon


class TrayIcon:
    """Enveloppe QSystemTrayIcon avec les actions propres à WaveRouter."""

    def __init__(
        self,
        parent,
        on_open: Callable[[], None],
        on_toggle_pause: Callable[[], None],
        is_paused: Callable[[], bool],
        on_quit: Callable[[], None],
    ) -> None:
        # L'état de pause est toujours lu à la source plutôt que recopié :
        # la bascule peut venir de la fenêtre comme du menu, et une copie
        # locale finit systématiquement désynchronisée de l'une des deux.
        self._is_paused = is_paused
        self._on_open = on_open

        self._icon = QSystemTrayIcon(app_icon(), parent)
        self._icon.setToolTip("WaveRouter")

        menu = QMenu(parent)
        menu.setStyleSheet(theme.stylesheet())

        self._open_action = QAction("Ouvrir", parent)
        self._open_action.triggered.connect(lambda: on_open())
        menu.addAction(self._open_action)

        self._pause_action = QAction("Pause surveillance", parent)
        self._pause_action.setCheckable(True)
        self._pause_action.triggered.connect(lambda: (on_toggle_pause(), self.update_menu()))
        menu.addAction(self._pause_action)

        menu.addSeparator()

        quit_action = QAction("Quitter", parent)
        quit_action.triggered.connect(lambda: on_quit())
        menu.addAction(quit_action)

        self._icon.setContextMenu(menu)
        self._icon.activated.connect(self._on_activated)
        self.update_menu()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._on_open()

    def show(self) -> None:
        self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    def update_menu(self) -> None:
        """Aligne la coche du menu sur l'état réel de la surveillance."""
        paused = self._is_paused()
        self._pause_action.setChecked(paused)
        self._icon.setToolTip(
            "WaveRouter — surveillance en pause" if paused else "WaveRouter — surveillance active"
        )

    def notify(self, title: str, message: str) -> None:
        """Affiche une notification native Windows (best-effort)."""
        try:
            if QSystemTrayIcon.supportsMessages():
                self._icon.showMessage(title, message, app_icon(), 4000)
        except Exception:
            pass  # Les notifications sont un confort, jamais bloquantes
