"""
Fenêtre principale de WaveRouter.

Navigation latérale (sidebar) façon "control center" moderne : Tableau de
bord, Jeux, Réglages, Logs. Voir waverouter/ui/theme.py pour la palette et
les constantes de style.
"""

from __future__ import annotations

import datetime
import os
import webbrowser
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from waverouter import autostart
from waverouter.audio_backend import AudioBackend, SOUNDVOLUMEVIEW_DOWNLOAD_URL
from waverouter.config import ConfigManager, GameEntry, get_logs_dir
from waverouter.icon_extractor import extract_icon_image
from waverouter.logger import EventLogger
from waverouter.process_monitor import ProcessMonitor
from waverouter.ui import theme
from waverouter.ui.dialogs import GameDialog, QuickAddDialog
from waverouter.wavelink_devices import list_all_render_device_names, try_detect_wavelink_channels
from waverouter.window_processes import find_running_exe_path

_GAME_ICON_SIZE = 32

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

_NAV_ITEMS = ("Tableau de bord", "Jeux", "Réglages", "Logs")


class MainWindow(ctk.CTk):
    """Fenêtre principale de l'application."""

    def __init__(
        self,
        config_manager: ConfigManager,
        monitor: ProcessMonitor,
        logger: EventLogger,
        backend_factory: Callable[[], AudioBackend],
        on_close_to_tray: Callable[[], None],
    ) -> None:
        super().__init__()

        self.config_manager = config_manager
        self.monitor = monitor
        self.logger = logger
        self.backend_factory = backend_factory
        self.on_close_to_tray = on_close_to_tray

        self._known_channels: list[str] = []
        self._last_routing: tuple[str, str, str] | None = None  # (jeu, canal, heure)
        self._icon_cache: dict[str, ctk.CTkImage] = {}

        self.title("WaveRouter")
        self.geometry("980x640")
        self.minsize(860, 560)
        self.configure(fg_color=theme.BG_APP)

        self.protocol("WM_DELETE_WINDOW", self._handle_close)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._active_page = _NAV_ITEMS[0]

        self._build_sidebar()
        self._build_content_area()

        self._refresh_games_list()
        self.refresh_dashboard()
        self._show_page(self._active_page)

    # ------------------------------------------------------------------
    # Structure générale : sidebar + zone de contenu
    # ------------------------------------------------------------------
    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=0, width=220)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        header = ctk.CTkFrame(sidebar, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(24, 8))
        ctk.CTkLabel(
            header, text="●", text_color=theme.ACCENT, font=(theme.FONT_FAMILY, 16)
        ).pack(side="left")
        ctk.CTkLabel(
            header, text=" WaveRouter", text_color=theme.TEXT_PRIMARY, font=theme.FONT_H2
        ).pack(side="left")
        ctk.CTkLabel(
            sidebar,
            text="Routage audio automatique",
            text_color=theme.TEXT_MUTED,
            font=theme.FONT_SMALL,
        ).pack(anchor="w", padx=21, pady=(0, 24))

        nav_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav_frame.pack(fill="x", padx=12)
        for name in _NAV_ITEMS:
            btn = ctk.CTkButton(
                nav_frame,
                text=name,
                anchor="w",
                corner_radius=theme.RADIUS_BUTTON,
                font=theme.FONT_BODY,
                height=38,
                command=lambda n=name: self._show_page(n),
                **theme.nav_button_colors(active=(name == self._active_page)),
            )
            btn.pack(fill="x", pady=3)
            self._nav_buttons[name] = btn

        # --- Bloc statut en bas de la sidebar ---
        status_frame = ctk.CTkFrame(sidebar, fg_color=theme.BG_CARD, corner_radius=theme.RADIUS_CARD)
        status_frame.pack(fill="x", padx=12, side="bottom", pady=(0, 16))

        dot_row = ctk.CTkFrame(status_frame, fg_color="transparent")
        dot_row.pack(fill="x", padx=14, pady=(14, 4))
        self.status_dot = ctk.CTkLabel(
            dot_row, text="", width=10, height=10, corner_radius=5, fg_color=theme.SUCCESS
        )
        self.status_dot.pack(side="left")
        self.status_label = ctk.CTkLabel(
            dot_row, text="Surveillance active", font=theme.FONT_SMALL_BOLD, text_color=theme.TEXT_PRIMARY
        )
        self.status_label.pack(side="left", padx=(8, 0))

        self.toggle_button = ctk.CTkButton(
            status_frame,
            text="Mettre en pause",
            font=theme.FONT_SMALL,
            height=30,
            corner_radius=theme.RADIUS_BUTTON,
            fg_color=theme.BG_CARD_ALT,
            hover_color=theme.BG_CARD_HOVER,
            text_color=theme.TEXT_PRIMARY,
            command=self._toggle_monitor,
        )
        self.toggle_button.pack(fill="x", padx=14, pady=(4, 14))

    def _build_content_area(self) -> None:
        container = ctk.CTkFrame(self, fg_color=theme.BG_APP, corner_radius=0)
        container.grid(row=0, column=1, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        for name in _NAV_ITEMS:
            page = ctk.CTkFrame(container, fg_color="transparent")
            page.grid(row=0, column=0, sticky="nsew", padx=28, pady=24)
            page.grid_columnconfigure(0, weight=1)
            self._pages[name] = page

        self._build_dashboard_page(self._pages["Tableau de bord"])
        self._build_games_page(self._pages["Jeux"])
        self._build_settings_page(self._pages["Réglages"])
        self._build_logs_page(self._pages["Logs"])

    def _show_page(self, name: str) -> None:
        self._active_page = name
        for nav_name, btn in self._nav_buttons.items():
            btn.configure(**theme.nav_button_colors(active=(nav_name == name)))
        self._pages[name].tkraise()
        if name == "Tableau de bord":
            self.refresh_dashboard()
        elif name == "Jeux":
            # Permet de retrouver l'icône d'un jeu qui vient d'être lancé
            # (résolution "en direct" quand le chemin n'est pas enregistré).
            self._refresh_games_list()

    def _page_header(self, parent, title: str, subtitle: str = "") -> ctk.CTkFrame:
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=title, font=theme.FONT_H1, text_color=theme.TEXT_PRIMARY).grid(
            row=0, column=0, sticky="w"
        )
        if subtitle:
            ctk.CTkLabel(
                header, text=subtitle, font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY
            ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        return header

    def _card(self, parent, **kwargs) -> ctk.CTkFrame:
        return ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=theme.RADIUS_CARD, **kwargs)

    # ------------------------------------------------------------------
    # Page : Tableau de bord
    # ------------------------------------------------------------------
    def _build_dashboard_page(self, page: ctk.CTkFrame) -> None:
        self._page_header(
            page, "Tableau de bord", "Vue d'ensemble du routage audio en temps réel."
        )

        page.grid_rowconfigure(2, weight=1)

        stats_row = ctk.CTkFrame(page, fg_color="transparent")
        stats_row.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        for i in range(3):
            stats_row.grid_columnconfigure(i, weight=1, uniform="stats")

        self.stat_status_card = self._build_stat_card(
            stats_row, 0, "État", "Surveillance active", theme.SUCCESS
        )
        self.stat_games_card = self._build_stat_card(stats_row, 1, "Jeux configurés", "0", theme.ACCENT)
        self.stat_last_card = self._build_stat_card(
            stats_row, 2, "Dernier routage", "Aucun pour le moment", theme.TEXT_SECONDARY
        )

        activity_card = self._card(page)
        activity_card.grid(row=2, column=0, sticky="nsew")
        activity_card.grid_columnconfigure(0, weight=1)
        activity_card.grid_rowconfigure(1, weight=1)

        activity_header = ctk.CTkFrame(activity_card, fg_color="transparent")
        activity_header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            activity_header, text="Activité récente", font=theme.FONT_H3, text_color=theme.TEXT_PRIMARY
        ).pack(side="left")
        ctk.CTkButton(
            activity_header,
            text="Voir tous les logs",
            font=theme.FONT_SMALL,
            fg_color="transparent",
            hover_color=theme.BG_CARD_HOVER,
            text_color=theme.ACCENT,
            height=26,
            command=lambda: self._show_page("Logs"),
        ).pack(side="right")

        self.activity_textbox = ctk.CTkTextbox(
            activity_card,
            fg_color=theme.BG_CARD,
            text_color=theme.TEXT_SECONDARY,
            font=theme.FONT_MONO,
            state="disabled",
            wrap="word",
            border_width=0,
        )
        self.activity_textbox.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

    def _build_stat_card(self, parent, column: int, title: str, value: str, accent: str):
        card = self._card(parent)
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0 if column == 2 else 8))
        ctk.CTkLabel(card, text=title, font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(
            anchor="w", padx=18, pady=(16, 2)
        )
        value_label = ctk.CTkLabel(card, text=value, font=theme.FONT_H2, text_color=accent)
        value_label.pack(anchor="w", padx=18, pady=(0, 16))
        card.value_label = value_label  # type: ignore[attr-defined]
        return card

    def refresh_dashboard(self) -> None:
        paused = self.monitor.is_paused
        self.stat_status_card.value_label.configure(  # type: ignore[attr-defined]
            text="En pause" if paused else "Surveillance active",
            text_color=theme.WARNING if paused else theme.SUCCESS,
        )
        self.stat_games_card.value_label.configure(  # type: ignore[attr-defined]
            text=str(len(self.config_manager.config.games))
        )
        if self._last_routing:
            label, channel, when = self._last_routing
            self.stat_last_card.value_label.configure(  # type: ignore[attr-defined]
                text=f"{label} → {channel}", text_color=theme.TEXT_PRIMARY
            )

    def on_game_routed(self, label: str, channel: str) -> None:
        """Appelé (depuis le thread principal Tk) quand un routage vient d'être appliqué."""
        when = datetime.datetime.now().strftime("%H:%M:%S")
        self._last_routing = (label, channel, when)
        self._append_activity(f"{when} - {label} → {channel}")
        self.refresh_dashboard()

    def _append_activity(self, line: str) -> None:
        self.activity_textbox.configure(state="normal")
        self.activity_textbox.insert("end", line + "\n")
        self.activity_textbox.see("end")
        self.activity_textbox.configure(state="disabled")

    # ------------------------------------------------------------------
    # Page : Jeux
    # ------------------------------------------------------------------
    def _build_games_page(self, page: ctk.CTkFrame) -> None:
        header = self._page_header(
            page, "Jeux", "Applications surveillées et leur canal Wave Link cible."
        )
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        header.grid_columnconfigure(1, weight=0)

        ctk.CTkButton(
            actions,
            text="Détecter un jeu en cours",
            font=theme.FONT_BODY,
            corner_radius=theme.RADIUS_BUTTON,
            fg_color=theme.BG_CARD_ALT,
            hover_color=theme.BG_CARD_HOVER,
            text_color=theme.TEXT_PRIMARY,
            command=self._quick_add_game,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="+ Ajouter un jeu",
            font=theme.FONT_BODY_BOLD,
            corner_radius=theme.RADIUS_BUTTON,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            command=self._add_game,
        ).pack(side="left")

        page.grid_rowconfigure(1, weight=1)
        self.games_scroll = ctk.CTkScrollableFrame(
            page, fg_color="transparent", scrollbar_button_color=theme.BG_CARD_ALT
        )
        self.games_scroll.grid(row=1, column=0, sticky="nsew")
        self.games_scroll.grid_columnconfigure(0, weight=1)

        footer = ctk.CTkFrame(page, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ctk.CTkButton(
            footer,
            text="Actualiser la liste des canaux",
            font=theme.FONT_SMALL,
            fg_color="transparent",
            hover_color=theme.BG_CARD_HOVER,
            text_color=theme.TEXT_SECONDARY,
            height=28,
            command=self._refresh_channels_clicked,
        ).pack(side="left")

    def _refresh_games_list(self) -> None:
        for child in self.games_scroll.winfo_children():
            child.destroy()

        games = self.config_manager.config.games
        if not games:
            empty = self._card(self.games_scroll)
            empty.pack(fill="x", pady=6)
            ctk.CTkLabel(
                empty,
                text="Aucun jeu configuré pour l'instant.",
                font=theme.FONT_BODY,
                text_color=theme.TEXT_SECONDARY,
            ).pack(padx=20, pady=24)
            return

        for index, game in enumerate(games):
            self._build_game_row(index, game)

    def _build_game_row(self, index: int, game: GameEntry) -> None:
        row = self._card(self.games_scroll)
        row.pack(fill="x", pady=6)
        row.grid_columnconfigure(1, weight=1)

        icon_label = ctk.CTkLabel(row, image=self._get_game_icon(game), text="")
        icon_label.grid(row=0, column=0, padx=(18, 0), pady=14)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.grid(row=0, column=1, sticky="w", padx=12, pady=14)
        ctk.CTkLabel(info, text=game.label, font=theme.FONT_BODY_BOLD, text_color=theme.TEXT_PRIMARY).pack(
            anchor="w"
        )
        ctk.CTkLabel(
            info, text=game.process_name, font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED
        ).pack(anchor="w", pady=(2, 0))

        badge = ctk.CTkLabel(
            row,
            text=game.channel,
            font=theme.FONT_SMALL_BOLD,
            text_color=theme.ACCENT,
            fg_color=theme.ACCENT_SOFT,
            corner_radius=theme.RADIUS_BADGE,
            padx=10,
            pady=4,
        )
        badge.grid(row=0, column=2, padx=(8, 8))

        ctk.CTkButton(
            row,
            text="✎",
            width=30,
            height=30,
            corner_radius=theme.RADIUS_BUTTON,
            fg_color="transparent",
            hover_color=theme.BG_CARD_HOVER,
            text_color=theme.TEXT_SECONDARY,
            font=theme.FONT_BODY,
            command=lambda i=index: self._edit_game(i),
        ).grid(row=0, column=3, padx=(0, 4))

        ctk.CTkButton(
            row,
            text="✕",
            width=30,
            height=30,
            corner_radius=theme.RADIUS_BUTTON,
            fg_color="transparent",
            hover_color=theme.DANGER_SOFT,
            text_color=theme.TEXT_SECONDARY,
            font=theme.FONT_BODY,
            command=lambda i=index: self._remove_game(i),
        ).grid(row=0, column=4, padx=(0, 14))

    def _get_game_icon(self, game: GameEntry) -> ctk.CTkImage:
        """
        Retourne l'icône du jeu. Ordre de résolution :
        1. Le chemin .exe enregistré avec le jeu, si connu.
        2. À défaut, le chemin de l'exécutable actuellement en cours
           d'exécution portant ce nom de processus (le jeu est ouvert
           mais son chemin n'a jamais été enregistré).
        3. À défaut, un badge avec l'initiale du libellé.

        Les icônes effectivement extraites sont mises en cache (par
        chemin) pour éviter de solliciter l'API Windows à chaque
        rafraîchissement de la liste. Le résultat de secours (initiale)
        n'est volontairement pas mis en cache : si le jeu est lancé plus
        tard, l'icône réelle doit pouvoir être retrouvée au prochain
        rafraîchissement sans redémarrer l'application.
        """
        resolved_path = game.exe_path or find_running_exe_path(game.process_name) or ""

        if resolved_path:
            cached = self._icon_cache.get(resolved_path)
            if cached is not None:
                return cached
            pil_image = extract_icon_image(resolved_path, size=_GAME_ICON_SIZE)
            if pil_image is not None:
                ctk_image = ctk.CTkImage(
                    light_image=pil_image, dark_image=pil_image, size=(_GAME_ICON_SIZE, _GAME_ICON_SIZE)
                )
                self._icon_cache[resolved_path] = ctk_image
                return ctk_image

        pil_image = self._placeholder_icon(game.label)
        return ctk.CTkImage(
            light_image=pil_image, dark_image=pil_image, size=(_GAME_ICON_SIZE, _GAME_ICON_SIZE)
        )

    @staticmethod
    def _placeholder_icon(label: str) -> Image.Image:
        """Icône de secours : initiale du jeu sur un fond accent arrondi."""
        size = _GAME_ICON_SIZE
        letter = (label.strip()[:1] or "?").upper()
        accent_rgb = tuple(int(theme.ACCENT[i : i + 2], 16) for i in (1, 3, 5))

        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=8, fill=(*accent_rgb, 255))
        try:
            font = ImageFont.truetype("segoeui.ttf", int(size * 0.5))
        except OSError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), letter, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((size - text_w) / 2 - bbox[0], (size - text_h) / 2 - bbox[1]),
            letter,
            font=font,
            fill=(255, 255, 255, 255),
        )
        return img

    def _current_channels(self) -> list[str]:
        backend = self.backend_factory()
        if not backend.is_available():
            return self._known_channels
        channels, error = try_detect_wavelink_channels(backend)
        if error:
            return self._known_channels
        self._known_channels = channels
        return channels

    def _refresh_channels_clicked(self) -> None:
        channels = self._current_channels()
        if not channels:
            backend = self.backend_factory()
            raw_names: list[str] = []
            if backend.is_available():
                try:
                    raw_names = list_all_render_device_names(backend)
                except Exception:
                    raw_names = []

            if raw_names:
                details = "\n".join(f"  - {n}" for n in raw_names)
                self.log_line("Périphériques de sortie détectés :\n" + details)
                messagebox.showwarning(
                    "WaveRouter",
                    "Aucun périphérique de sortie exploitable n'a été retenu.\n\n"
                    "La liste complète des périphériques détectés a été ajoutée "
                    "à l'onglet Logs.",
                )
            else:
                messagebox.showwarning(
                    "WaveRouter",
                    "Aucun périphérique de sortie audio détecté.\n"
                    "Vérifiez que SoundVolumeView.exe est correctement configuré "
                    "dans l'onglet Réglages.",
                )
        else:
            messagebox.showinfo(
                "WaveRouter",
                f"{len(channels)} périphérique(s) de sortie disponible(s) dans la "
                "liste déroulante des canaux. Repérez-y le(s) canal/canaux "
                "correspondant à Wave Link (ex: Games!, Music, System, Voice "
                "chat...) tel que nommé dans l'application Wave Link.",
            )

    def _add_game(self) -> None:
        channels = self._current_channels()

        def on_confirm(game: GameEntry) -> None:
            self.config_manager.config.games.append(game)
            self.config_manager.save()
            self._refresh_games_list()
            self.refresh_dashboard()

        GameDialog(self, channels=channels, on_confirm=on_confirm)

    def _quick_add_game(self) -> None:
        channels = self._current_channels()

        def on_confirm(game: GameEntry) -> None:
            self.config_manager.config.games.append(game)
            self.config_manager.save()
            self._refresh_games_list()
            self.refresh_dashboard()

        QuickAddDialog(self, channels=channels, on_confirm=on_confirm)

    def _edit_game(self, index: int) -> None:
        games = self.config_manager.config.games
        if not (0 <= index < len(games)):
            return
        channels = self._current_channels()

        def on_confirm(updated: GameEntry) -> None:
            games[index] = updated
            self.config_manager.save()
            self._refresh_games_list()
            self.refresh_dashboard()

        GameDialog(self, channels=channels, on_confirm=on_confirm, existing=games[index])

    def _remove_game(self, index: int) -> None:
        games = self.config_manager.config.games
        if 0 <= index < len(games):
            removed = games.pop(index)
            self.config_manager.save()
            self._refresh_games_list()
            self.refresh_dashboard()
            self.log_line(f"Jeu supprimé de la liste : {removed.label}")

    # ------------------------------------------------------------------
    # Page : Réglages
    # ------------------------------------------------------------------
    def _build_settings_page(self, page: ctk.CTkFrame) -> None:
        self._page_header(page, "Réglages", "Configuration du backend audio et du comportement de l'app.")

        settings = self.config_manager.config.settings

        backend_card = self._card(page)
        backend_card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        backend_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            backend_card, text="Backend audio", font=theme.FONT_H3, text_color=theme.TEXT_PRIMARY
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 4))
        ctk.CTkLabel(
            backend_card,
            text="Chemin vers SoundVolumeView.exe",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(4, 4))

        path_frame = ctk.CTkFrame(backend_card, fg_color="transparent")
        path_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))
        path_frame.grid_columnconfigure(0, weight=1)
        self.svv_path_entry = ctk.CTkEntry(
            path_frame,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER,
            corner_radius=theme.RADIUS_INPUT,
        )
        self.svv_path_entry.insert(0, settings.soundvolumeview_path)
        self.svv_path_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            path_frame,
            text="Parcourir...",
            width=100,
            fg_color=theme.BG_CARD_ALT,
            hover_color=theme.BG_CARD_HOVER,
            corner_radius=theme.RADIUS_BUTTON,
            command=self._browse_svv,
        ).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(
            path_frame,
            text="Télécharger",
            width=110,
            fg_color=theme.BG_CARD_ALT,
            hover_color=theme.BG_CARD_HOVER,
            corner_radius=theme.RADIUS_BUTTON,
            command=lambda: webbrowser.open(SOUNDVOLUMEVIEW_DOWNLOAD_URL),
        ).grid(row=0, column=2, padx=(8, 0))

        behavior_card = self._card(page)
        behavior_card.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        behavior_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            behavior_card, text="Comportement", font=theme.FONT_H3, text_color=theme.TEXT_PRIMARY
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 8))

        interval_row = ctk.CTkFrame(behavior_card, fg_color="transparent")
        interval_row.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 12))
        ctk.CTkLabel(
            interval_row,
            text="Intervalle de vérification (secondes)",
            font=theme.FONT_BODY,
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")
        self.poll_entry = ctk.CTkEntry(
            interval_row,
            width=70,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER,
            corner_radius=theme.RADIUS_INPUT,
        )
        self.poll_entry.insert(0, str(settings.poll_interval))
        self.poll_entry.pack(side="left", padx=(12, 0))

        self.notif_var = ctk.BooleanVar(value=settings.notifications_enabled)
        self._checkbox(
            behavior_card, "Afficher une notification lors d'un routage", self.notif_var, row=2
        )
        self.autostart_var = ctk.BooleanVar(value=settings.autostart)
        self._checkbox(
            behavior_card, "Lancer WaveRouter au démarrage de Windows", self.autostart_var, row=3
        )
        self.minimize_var = ctk.BooleanVar(value=settings.minimize_to_tray_on_close)
        self._checkbox(
            behavior_card, "Réduire dans la barre système à la fermeture", self.minimize_var, row=4
        )
        self.debug_var = ctk.BooleanVar(value=settings.debug)
        self._checkbox(
            behavior_card,
            "Mode debug / verbose (diagnostic de la détection)",
            self.debug_var,
            row=5,
            pady_bottom=18,
        )

        save_row = ctk.CTkFrame(page, fg_color="transparent")
        save_row.grid(row=3, column=0, sticky="w")
        ctk.CTkButton(
            save_row,
            text="Enregistrer les réglages",
            font=theme.FONT_BODY_BOLD,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            corner_radius=theme.RADIUS_BUTTON,
            command=self._save_settings,
        ).pack(side="left")
        self.settings_status = ctk.CTkLabel(save_row, text="", font=theme.FONT_SMALL, text_color=theme.SUCCESS)
        self.settings_status.pack(side="left", padx=(12, 0))

    def _checkbox(self, parent, text: str, variable, row: int, pady_bottom: int = 4) -> None:
        ctk.CTkCheckBox(
            parent,
            text=text,
            variable=variable,
            font=theme.FONT_BODY,
            text_color=theme.TEXT_PRIMARY,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
        ).grid(row=row, column=0, sticky="w", padx=20, pady=(0, pady_bottom))

    def _browse_svv(self) -> None:
        path = filedialog.askopenfilename(
            title="Sélectionner SoundVolumeView.exe",
            filetypes=[("Exécutable", "SoundVolumeView.exe"), ("Tous les fichiers", "*.*")],
        )
        if path:
            self.svv_path_entry.delete(0, "end")
            self.svv_path_entry.insert(0, path)

    def _save_settings(self) -> None:
        settings = self.config_manager.config.settings
        settings.soundvolumeview_path = self.svv_path_entry.get().strip()
        try:
            settings.poll_interval = max(1.0, float(self.poll_entry.get().strip()))
        except ValueError:
            settings.poll_interval = 3.0
        settings.notifications_enabled = self.notif_var.get()
        settings.minimize_to_tray_on_close = self.minimize_var.get()
        settings.debug = self.debug_var.get()

        wants_autostart = self.autostart_var.get()
        if wants_autostart != settings.autostart:
            try:
                autostart.set_enabled(wants_autostart)
                settings.autostart = wants_autostart
            except OSError as exc:
                messagebox.showerror(
                    "WaveRouter", f"Impossible de modifier le démarrage automatique :\n{exc}"
                )

        self.config_manager.save()
        self.logger.debug = settings.debug  # met à jour le niveau de verbosité live
        self.settings_status.configure(text="Réglages enregistrés.")
        self.log_line("Réglages mis à jour.")

    # ------------------------------------------------------------------
    # Page : Logs
    # ------------------------------------------------------------------
    def _build_logs_page(self, page: ctk.CTkFrame) -> None:
        header = self._page_header(page, "Logs", "Historique complet des événements de l'application.")
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        header.grid_columnconfigure(1, weight=0)
        ctk.CTkButton(
            actions,
            text="Ouvrir le dossier des logs",
            font=theme.FONT_SMALL,
            fg_color=theme.BG_CARD_ALT,
            hover_color=theme.BG_CARD_HOVER,
            text_color=theme.TEXT_PRIMARY,
            height=30,
            corner_radius=theme.RADIUS_BUTTON,
            command=self._open_logs_folder,
        ).pack(side="left")

        page.grid_rowconfigure(1, weight=1)
        log_card = self._card(page)
        log_card.grid(row=1, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(
            log_card,
            fg_color=theme.BG_CARD,
            text_color=theme.TEXT_SECONDARY,
            font=theme.FONT_MONO,
            state="disabled",
            wrap="word",
            border_width=0,
        )
        self.log_textbox.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)

    def _open_logs_folder(self) -> None:
        try:
            os.startfile(get_logs_dir())  # nosec - ouverture d'un dossier local uniquement
        except OSError as exc:
            messagebox.showerror("WaveRouter", f"Impossible d'ouvrir le dossier des logs :\n{exc}")

    def log_line(self, line: str) -> None:
        """Ajoute une ligne au panneau de logs (thread-safe via `after`)."""

        def append() -> None:
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", line + "\n")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
            self._append_activity(line)

        try:
            self.after(0, append)
        except RuntimeError:
            pass  # la fenêtre a pu être détruite entre-temps

    # ------------------------------------------------------------------
    # Surveillance (pause/reprise) depuis la fenêtre
    # ------------------------------------------------------------------
    def _toggle_monitor(self) -> None:
        if self.monitor.is_paused:
            self.monitor.resume()
        else:
            self.monitor.pause()
        paused = self.monitor.is_paused
        self.status_dot.configure(fg_color=theme.WARNING if paused else theme.SUCCESS)
        self.status_label.configure(text="En pause" if paused else "Surveillance active")
        self.toggle_button.configure(text="Reprendre" if paused else "Mettre en pause")
        self.refresh_dashboard()

    # ------------------------------------------------------------------
    # Fermeture / réduction dans le system tray
    # ------------------------------------------------------------------
    def _handle_close(self) -> None:
        if self.config_manager.config.settings.minimize_to_tray_on_close:
            self.withdraw()
            self.on_close_to_tray()
        else:
            self.destroy()

    def show_and_focus(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
