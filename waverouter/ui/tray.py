"""
Icône dans la barre des tâches (system tray) : ouvrir la fenêtre, mettre la
surveillance en pause, quitter l'application. Génère son icône par code
(pas de fichier .ico requis) via Pillow.
"""

from __future__ import annotations

import threading
from typing import Callable

import pystray
from PIL import Image, ImageDraw

try:
    from plyer import notification as plyer_notification
except ImportError:  # plyer optionnel si les notifications sont désactivées
    plyer_notification = None


def _build_icon_image() -> Image.Image:
    """Dessine une icône simple (onde stylisée) pour la barre système."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, size - 2, size - 2), fill=(124, 92, 255, 255))  # theme.ACCENT (#7C5CFF)
    # Trois barres façon égaliseur audio, pour évoquer le routage audio
    bars = [(18, 34, 26, 46), (30, 20, 38, 46), (42, 28, 50, 46)]
    for x0, y0, x1, y1 in bars:
        draw.rounded_rectangle((x0, y0, x1, y1), radius=2, fill=(255, 255, 255, 255))
    return img


class TrayIcon:
    """Enveloppe pystray.Icon avec les actions spécifiques à WaveRouter."""

    def __init__(
        self,
        on_open: Callable[[], None],
        on_toggle_pause: Callable[[], bool],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_open = on_open
        self._on_toggle_pause = on_toggle_pause
        self._on_quit = on_quit

        self._icon = pystray.Icon(
            "WaveRouter",
            icon=_build_icon_image(),
            title="WaveRouter",
            menu=pystray.Menu(
                pystray.MenuItem("Ouvrir", self._handle_open, default=True),
                pystray.MenuItem(
                    "Pause surveillance", self._handle_toggle_pause, checked=self._is_paused
                ),
                pystray.MenuItem("Quitter", self._handle_quit),
            ),
        )
        self._paused = False
        self._thread: threading.Thread | None = None

    def _is_paused(self, _item: pystray.MenuItem) -> bool:
        return self._paused

    def _handle_open(self, _icon=None, _item=None) -> None:
        self._on_open()

    def _handle_toggle_pause(self, _icon=None, _item=None) -> None:
        self._paused = self._on_toggle_pause()
        self._icon.update_menu()

    def _handle_quit(self, _icon=None, _item=None) -> None:
        self._on_quit()
        self._icon.stop()

    def run_detached(self) -> None:
        """Démarre la boucle pystray dans un thread dédié (non bloquant)."""
        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="WaveRouterTray")
        self._thread.start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass

    @staticmethod
    def notify(title: str, message: str) -> None:
        """Affiche une notification toast discrète (best-effort)."""
        if plyer_notification is None:
            return
        try:
            plyer_notification.notify(
                title=title, message=message, app_name="WaveRouter", timeout=4
            )
        except Exception:
            pass  # Les notifications sont un confort, jamais bloquantes
