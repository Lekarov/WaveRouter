"""
Fenêtre principale de WaveRouter.

Navigation latérale façon "control center" : Tableau de bord, Jeux,
Réglages, Logs.

Règle de threading : les threads de fond (surveillance, balayage des
périphériques) ne touchent jamais un widget. Ils émettent un signal Qt, que
Qt délivre automatiquement sur le thread de l'interface via une connexion
différée. C'est le mécanisme prévu par la boîte à outils, là où la version 1
devait maintenir sa propre file d'attente vidée par minuterie, `after()`
n'étant pas sûr depuis un thread tiers.
"""

from __future__ import annotations

import datetime
import os
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from waverouter import autostart
from waverouter.audio_backend import SOUNDVOLUMEVIEW_DOWNLOAD_URL
from waverouter.config import GameEntry
from waverouter.icon_extractor import extract_icon_image
from waverouter.ui import theme
from waverouter.ui.dialogs import GameDialog, LibraryDialog, NewGameDialog, QuickAddDialog
from waverouter.ui.widgets import (
    Badge,
    Card,
    GameCard,
    NavButton,
    PageHeader,
    StatCard,
    StatusDot,
    button,
    label,
    letter_icon,
    pil_to_pixmap,
)
from waverouter.wavelink_devices import list_all_render_device_names, try_detect_wavelink_channels
from waverouter.window_processes import map_running_exe_paths

_GAME_ICON_SIZE = 40

# Grille de la page Jeux : largeur minimale d'une fiche et écart entre elles.
_CARD_MIN_WIDTH = 320
_GRID_SPACING = 12

# Qt plafonne lui-même le nombre de blocs conservés : l'application tourne
# des jours d'affilée, les panneaux de texte ne doivent pas croître sans fin.
_MAX_LOG_BLOCKS = 800

_NAV_ITEMS = ("Tableau de bord", "Jeux", "Réglages", "Logs")


class MainWindow(QMainWindow):
    """Fenêtre principale de l'application."""

    # Ponts thread de fond -> interface. Émettre un signal est sûr depuis
    # n'importe quel thread ; Qt se charge de la bascule.
    routed = Signal(str, str)
    candidate_found = Signal(str, str, str)
    monitor_state_changed = Signal()
    log_received = Signal(str)
    channels_loaded = Signal(list, str)

    def __init__(self, config_manager, monitor, logger, backend_factory) -> None:
        super().__init__()
        self.config_manager = config_manager
        self.monitor = monitor
        self.logger = logger
        self.backend_factory = backend_factory

        self._known_channels: list[str] = []
        self._channels_loading = False
        self._last_routing: tuple[str, str, str] | None = None
        self._icon_cache: dict[str, object] = {}
        self._really_quit = False
        self.on_close_to_tray = lambda: None

        self.setWindowTitle("WaveRouter")
        self.resize(1040, 680)
        self.setMinimumSize(900, 580)
        self.setStyleSheet(theme.stylesheet())

        self._build_ui()

        # Redimensionner génère une rafale d'événements : on ne reconstruit la
        # grille qu'une fois le geste terminé.
        self._relayout_games_timer = QTimer(self)
        self._relayout_games_timer.setSingleShot(True)
        self._relayout_games_timer.timeout.connect(self._refresh_games_list)

        self.routed.connect(self._on_game_routed)
        self.candidate_found.connect(self._on_game_candidate)
        self.monitor_state_changed.connect(self.refresh_monitor_state)
        self.log_received.connect(self._append_log)
        self.channels_loaded.connect(self._on_channels_loaded)

        self._load_log_history()
        self._refresh_games_list()
        self.refresh_monitor_state()
        self._reconcile_autostart()
        self.refresh_channels_async()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        # Le fond du conteneur est décrit dans la feuille globale, jamais posé
        # ici : une feuille appliquée à un widget vaut aussi pour toute sa
        # descendance et écraserait le fond de chaque bouton des pages.
        self.pages = QStackedWidget()
        self._page_index: dict[str, int] = {}
        for name, builder in (
            ("Tableau de bord", self._build_dashboard_page),
            ("Jeux", self._build_games_page),
            ("Réglages", self._build_settings_page),
            ("Logs", self._build_logs_page),
        ):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(28, 26, 28, 26)
            layout.setSpacing(18)
            builder(layout)
            self._page_index[name] = self.pages.addWidget(page)
        root.addWidget(self.pages, 1)

        self.setCentralWidget(central)
        self._nav_buttons[_NAV_ITEMS[0]].setChecked(True)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 22, 14, 16)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(8)
        dot = StatusDot(theme.ACCENT)
        brand.addWidget(dot)
        brand.addWidget(label("WaveRouter", "brand"))
        brand.addStretch(1)
        layout.addLayout(brand)
        subtitle = label("Routage audio automatique", "muted")
        layout.addWidget(subtitle)
        layout.addSpacing(20)

        self._nav_buttons: dict[str, NavButton] = {}
        for name in _NAV_ITEMS:
            btn = NavButton(name, lambda n=name: self.show_page(n))
            layout.addWidget(btn)
            self._nav_buttons[name] = btn

        layout.addStretch(1)

        status_card = Card(role="cardAlt", shadow=False, padding=(14, 12, 14, 12), spacing=8)
        dot_row = QHBoxLayout()
        dot_row.setSpacing(8)
        self.status_dot = StatusDot(theme.SUCCESS)
        dot_row.addWidget(self.status_dot)
        self.status_label = label("Surveillance active", "small")
        self.status_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-weight: 700; font-size: {theme.SIZE_SMALL}px;"
        )
        dot_row.addWidget(self.status_label)
        dot_row.addStretch(1)
        status_card.body().addLayout(dot_row)

        self.toggle_button = button("Mettre en pause", "", self._toggle_monitor)
        status_card.body().addWidget(self.toggle_button)
        layout.addWidget(status_card)

        return sidebar

    def show_page(self, name: str) -> None:
        self.pages.setCurrentIndex(self._page_index[name])
        self._nav_buttons[name].setChecked(True)
        if name == "Tableau de bord":
            self.refresh_dashboard()
        elif name == "Jeux":
            # Retrouve l'icône d'un jeu qui vient d'être lancé, dont le
            # chemin n'était pas encore connu.
            self._refresh_games_list()

    # ------------------------------------------------------------------
    # Page : Tableau de bord
    # ------------------------------------------------------------------
    def _build_dashboard_page(self, layout: QVBoxLayout) -> None:
        layout.addWidget(
            PageHeader("Tableau de bord", "Vue d'ensemble du routage audio en temps réel.")
        )

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_status = StatCard("État", "Active", theme.SUCCESS)
        self.stat_games = StatCard("Jeux configurés", "0", theme.ACCENT)
        self.stat_active = StatCard("Routages actifs", "0", theme.TEXT_SECONDARY)
        self.stat_last = StatCard("Dernier routage", "Aucun", theme.TEXT_SECONDARY)
        for card in (self.stat_status, self.stat_games, self.stat_active, self.stat_last):
            stats.addWidget(card, 1)
        layout.addLayout(stats)

        columns = QHBoxLayout()
        columns.setSpacing(14)

        # --- Colonne gauche : routages en cours ---
        active_card = Card()
        active_card.body().addWidget(label("Routages en cours", "h3"))
        self.active_container = QVBoxLayout()
        self.active_container.setSpacing(8)
        active_card.body().addLayout(self.active_container)
        active_card.body().addStretch(1)
        columns.addWidget(active_card, 1)

        # --- Colonne droite : historique des routages ---
        activity_card = Card()
        header = QHBoxLayout()
        header.addWidget(label("Routages effectués", "h3"))
        header.addStretch(1)
        header.addWidget(button("Voir tous les logs", "link", lambda: self.show_page("Logs")))
        activity_card.body().addLayout(header)

        self.activity_view = QPlainTextEdit()
        self.activity_view.setReadOnly(True)
        self.activity_view.setMaximumBlockCount(_MAX_LOG_BLOCKS)
        activity_card.body().addWidget(self.activity_view)
        columns.addWidget(activity_card, 1)

        layout.addLayout(columns, 1)

    def refresh_dashboard(self) -> None:
        paused = self.monitor.is_paused
        self.stat_status.set_value(
            "En pause" if paused else "Active",
            theme.WARNING if paused else theme.SUCCESS,
        )
        self.stat_games.set_value(str(len(self.config_manager.config.games)))

        routes = self.monitor.active_routes()
        self.stat_active.set_value(
            str(len(routes)), theme.SUCCESS if routes else theme.TEXT_SECONDARY
        )
        if self._last_routing:
            game_label, channel, _when = self._last_routing
            self.stat_last.set_value(f"{game_label}\n→ {channel}", theme.TEXT_PRIMARY)

        self._refresh_active_routes(routes)

    def _refresh_active_routes(self, routes) -> None:
        while self.active_container.count():
            item = self.active_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not routes:
            self.active_container.addWidget(
                label("Aucun jeu surveillé n'est en cours d'exécution.", "muted")
            )
            return

        for route in sorted(routes, key=lambda r: r.label.lower()):
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(StatusDot(theme.SUCCESS))
            texts = QVBoxLayout()
            texts.setSpacing(1)
            name = label(route.label, "small")
            name.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-weight: 600;")
            texts.addWidget(name)
            texts.addWidget(label(route.process_name, "muted"))
            row.addLayout(texts)
            row.addStretch(1)
            row.addWidget(Badge(route.channel))
            holder = QWidget()
            holder.setLayout(row)
            self.active_container.addWidget(holder)

    def _on_game_routed(self, game_label: str, channel: str) -> None:
        when = datetime.datetime.now().strftime("%H:%M:%S")
        self._last_routing = (game_label, channel, when)
        self.activity_view.appendPlainText(f"{when}   {game_label} → {channel}")
        self.refresh_dashboard()

    # ------------------------------------------------------------------
    # Page : Jeux
    # ------------------------------------------------------------------
    def _build_games_page(self, layout: QVBoxLayout) -> None:
        layout.addWidget(
            PageHeader("Jeux", "Applications surveillées et leur canal Wave Link cible.")
        )

        # Les trois actions occupent leur propre ligne : sur la même que le
        # titre, elles se font tronquer dès que la fenêtre approche sa taille
        # minimale, le sous-titre revendiquant déjà la moitié de la largeur.
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        for text, role, slot, tip in (
            ("Importer mes jeux", "", self._import_library,
             "Steam, Epic Games, GOG et vos dossiers de jeux"),
            ("Détecter un jeu en cours", "", self._quick_add_game,
             "Choisir parmi les applications actuellement ouvertes"),
            ("+ Ajouter un jeu", "primary", self._add_game,
             "Saisir manuellement un exécutable"),
        ):
            btn = button(text, role, slot)
            btn.setToolTip(tip)
            actions.addWidget(btn)
        layout.addLayout(actions)

        # --- Barre de recherche et compteur ---
        tools = QHBoxLayout()
        tools.setSpacing(10)
        self.games_search = QLineEdit()
        self.games_search.setPlaceholderText("Rechercher un jeu...")
        self.games_search.setClearButtonEnabled(True)
        self.games_search.setMinimumHeight(34)
        self.games_search.setMinimumWidth(280)
        self.games_search.setMaximumWidth(340)
        self.games_search.textChanged.connect(lambda _t: self._refresh_games_list())
        tools.addWidget(self.games_search)
        self.games_count = label("", "muted")
        tools.addSpacing(4)
        tools.addWidget(self.games_count)
        tools.addStretch(1)
        layout.addLayout(tools)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.games_container = QWidget()
        self.games_grid = QGridLayout(self.games_container)
        self.games_grid.setContentsMargins(0, 0, 8, 0)
        self.games_grid.setSpacing(12)
        self.games_grid.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.games_container)
        self.games_scroll = scroll
        layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addWidget(button("Actualiser la liste des canaux", "link", self._refresh_channels_clicked))
        footer.addStretch(1)
        layout.addLayout(footer)

    def _clear_games_grid(self) -> None:
        while self.games_grid.count():
            item = self.games_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _games_columns(self) -> int:
        """Nombre de colonnes tenant dans la largeur disponible."""
        available = self.games_scroll.viewport().width()
        return max(1, min(3, (available + _GRID_SPACING) // (_CARD_MIN_WIDTH + _GRID_SPACING)))

    def _refresh_games_list(self) -> None:
        self._clear_games_grid()

        games = self.config_manager.config.games
        query = self.games_search.text().strip().lower()
        visible = [
            (index, game)
            for index, game in enumerate(games)
            if not query
            or query in game.label.lower()
            or query in game.process_name.lower()
            or query in game.channel.lower()
        ]

        if not games:
            self.games_count.setText("")
            self.games_grid.addWidget(self._empty_games_card(), 0, 0)
            return
        if not visible:
            self.games_count.setText(f"0 / {len(games)}")
            empty = Card(shadow=False)
            empty.body().addWidget(label(f"Aucun jeu ne correspond à « {query} ».", "body"))
            self.games_grid.addWidget(empty, 0, 0)
            return

        # Un seul balayage des processus pour tous les jeux sans chemin
        # enregistré, au lieu d'un balayage complet par jeu.
        missing = {g.normalized_process_name() for g in games if not g.exe_path}
        resolved = map_running_exe_paths(missing) if missing else {}
        active = {r.process_name.lower() for r in self.monitor.active_routes()}

        running_count = sum(1 for _i, g in visible if g.normalized_process_name() in active)
        total = f"{len(visible)} sur {len(games)}" if query else str(len(games))
        suffix = f"  •  {running_count} en cours" if running_count else ""
        self.games_count.setText(f"{total} jeu(x){suffix}")

        columns = self._games_columns()
        for position, (index, game) in enumerate(visible):
            card = GameCard(
                title=game.label,
                process_name=game.process_name,
                channel=game.channel,
                pixmap=self._game_icon(game, resolved),
                enabled=game.enabled,
                running=game.normalized_process_name() in active,
                on_edit=lambda i=index: self._edit_game(i),
                on_remove=lambda i=index: self._remove_game(i),
            )
            self.games_grid.addWidget(card, position // columns, position % columns)
        for column in range(columns):
            self.games_grid.setColumnStretch(column, 1)

    def _empty_games_card(self) -> QWidget:
        empty = Card()
        empty.body().addWidget(label("Aucun jeu configuré pour l'instant.", "h3"))
        hint = label(
            "Utilisez « Importer mes jeux » pour partir de vos bibliothèques "
            "Steam, Epic Games et GOG, ou pour analyser un dossier contenant "
            "vos jeux installés à la main.",
            "body",
        )
        hint.setWordWrap(True)
        empty.body().addWidget(hint)
        return empty

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # La grille se réorganise avec la fenêtre : le nombre de colonnes
        # dépend de la largeur restante une fois la barre latérale déduite.
        if self.pages.currentIndex() == self._page_index.get("Jeux"):
            self._relayout_games_timer.start(120)

    def _game_icon(self, game: GameEntry, resolved: dict):
        """
        Icône du jeu. Ordre de résolution : chemin enregistré, puis chemin du
        processus en cours d'exécution, puis pastille avec l'initiale.

        Les icônes extraites sont mises en cache par chemin. Le repli sur
        l'initiale n'est volontairement pas mis en cache : si le jeu démarre
        plus tard, la vraie icône doit pouvoir apparaître au rafraîchissement
        suivant sans redémarrer l'application.
        """
        path = game.exe_path or resolved.get(game.normalized_process_name(), "")
        if path:
            cached = self._icon_cache.get(path)
            if cached is not None:
                return cached
            image = extract_icon_image(path, size=_GAME_ICON_SIZE * 2)
            if image is not None:
                pixmap = pil_to_pixmap(image).scaled(
                    _GAME_ICON_SIZE,
                    _GAME_ICON_SIZE,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self._icon_cache[path] = pixmap
                return pixmap
        return letter_icon(game.label, _GAME_ICON_SIZE)

    # ------------------------------------------------------------------
    # Gestion de la liste de jeux
    # ------------------------------------------------------------------
    def _is_duplicate(self, process_name: str) -> bool:
        return self.config_manager.config.find_game(process_name) is not None

    def _save_config(self) -> None:
        try:
            self.config_manager.save()
        except OSError as exc:
            QMessageBox.critical(
                self,
                "WaveRouter",
                f"Impossible d'enregistrer la configuration :\n{exc}\n\n"
                "Les modifications seront perdues à la fermeture.",
            )

    def _add_games(self, entries: list[GameEntry]) -> None:
        self.config_manager.config.games.extend(entries)
        self._save_config()
        self._refresh_games_list()
        self.refresh_dashboard()
        for entry in entries:
            self.logger.info(f"Jeu ajouté : {entry.label} → {entry.channel}")
        self._route_running_games(entries)

    def _route_running_games(self, entries: list[GameEntry]) -> None:
        """
        Route immédiatement les jeux ajoutés ou modifiés qui tournent déjà.

        Le moteur ne réagit qu'aux lancements de processus : sans cet appel,
        un jeu ajouté en pleine partie (cas typique de la détection
        automatique) ne serait routé qu'à son prochain lancement.
        """
        targets = [e for e in entries if e.enabled and e.channel]
        if not targets:
            return

        def worker() -> None:  # request_route invoque SoundVolumeView : hors UI
            for entry in targets:
                if not self.monitor.request_route(
                    entry.process_name, entry.label, entry.channel
                ):
                    self.logger.debug_log(
                        f"{entry.process_name} n'est pas en cours d'exécution, "
                        f"il sera routé à son prochain lancement."
                    )

        threading.Thread(target=worker, daemon=True, name="WaveRouterRouteNow").start()

    def _add_game(self) -> None:
        GameDialog(
            self,
            channels=self._channels(),
            on_confirm=lambda game: self._add_games([game]),
            is_duplicate=self._is_duplicate,
        ).exec()

    def _quick_add_game(self) -> None:
        QuickAddDialog(
            self,
            channels=self._channels(),
            on_confirm=lambda game: self._add_games([game]),
            is_duplicate=self._is_duplicate,
        ).exec()

    def _import_library(self) -> None:
        def on_add_folder(folder: str) -> bool:
            if not self.config_manager.config.add_game_folder(folder):
                return False
            self._save_config()
            self.logger.info(f"Dossier de jeux ajouté : {folder}")
            return True

        LibraryDialog(
            self,
            channels=self._channels(),
            on_import=self._add_games,
            is_duplicate=self._is_duplicate,
            folders=self.config_manager.config.game_folders,
            on_add_folder=on_add_folder,
        ).exec()

    def _edit_game(self, index: int) -> None:
        games = self.config_manager.config.games
        if not (0 <= index < len(games)):
            return
        original = games[index]

        def is_duplicate(process_name: str) -> bool:
            # L'entrée éditée ne doit pas se déclarer en doublon d'elle-même.
            if process_name.strip().lower() == original.normalized_process_name():
                return False
            return self._is_duplicate(process_name)

        def on_confirm(updated: GameEntry) -> None:
            games[index] = updated
            self._save_config()
            self._refresh_games_list()
            self.refresh_dashboard()
            if updated.normalized_process_name() != original.normalized_process_name():
                self.monitor.forget_process(original.process_name)
            if updated.enabled:
                # Nouveau canal ou jeu réactivé : appliquer sans attendre
                # un prochain lancement.
                self._route_running_games([updated])
            else:
                self.monitor.forget_process(updated.process_name)

        GameDialog(
            self,
            channels=self._channels(),
            on_confirm=on_confirm,
            existing=original,
            is_duplicate=is_duplicate,
        ).exec()

    def _remove_game(self, index: int) -> None:
        games = self.config_manager.config.games
        if not (0 <= index < len(games)):
            return
        game = games[index]
        confirm = QMessageBox.question(
            self,
            "WaveRouter",
            f"Retirer « {game.label} » de la liste des jeux surveillés ?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        removed = games.pop(index)
        self.monitor.forget_process(removed.process_name)
        self._save_config()
        self._refresh_games_list()
        self.refresh_dashboard()
        self.logger.info(f"Jeu supprimé de la liste : {removed.label}")

    # ------------------------------------------------------------------
    # Détection automatique d'un nouveau jeu
    # ------------------------------------------------------------------
    def _on_game_candidate(self, process_name: str, exe_path: str, title: str) -> None:
        if self._is_duplicate(process_name):
            return

        def on_ignore(name: str) -> None:
            self.config_manager.config.ignore_process(name)
            self._save_config()
            self.logger.info(f"{name} ne sera plus proposé.")

        self.show_and_focus()
        NewGameDialog(
            self,
            process_name=process_name,
            exe_path=exe_path,
            title=title,
            channels=self._default_first_channels(),
            on_add=lambda game: self._add_games([game]),
            on_ignore=on_ignore,
        ).exec()

    def _default_first_channels(self) -> list[str]:
        """Canaux connus, le canal par défaut placé en tête s'il existe."""
        channels = list(self._channels())
        default = self.config_manager.config.settings.default_channel
        if default and default in channels:
            channels.remove(default)
            channels.insert(0, default)
        return channels

    # ------------------------------------------------------------------
    # Canaux audio (chargés hors du thread d'interface)
    # ------------------------------------------------------------------
    def refresh_channels_async(self) -> None:
        """
        Recharge la liste des canaux dans un thread dédié.

        L'export SoundVolumeView prend plusieurs centaines de millisecondes :
        exécuté sur le thread de l'interface, il la fige visiblement à chaque
        ouverture de dialogue.
        """
        if self._channels_loading:
            return
        self._channels_loading = True

        def work() -> None:
            backend = self.backend_factory()
            if not backend.is_available():
                self.channels_loaded.emit([], "SoundVolumeView.exe n'est pas configuré.")
                return
            channels, error = try_detect_wavelink_channels(backend)
            self.channels_loaded.emit(channels, error or "")

        threading.Thread(target=work, daemon=True, name="WaveRouterChannels").start()

    def _on_channels_loaded(self, channels: list, error: str) -> None:
        self._channels_loading = False
        if channels:
            self._known_channels = list(channels)
        elif error:
            self.logger.debug_log(f"Détection des canaux : {error}")

    def _channels(self) -> list[str]:
        self.refresh_channels_async()
        return self._known_channels

    def _refresh_channels_clicked(self) -> None:
        backend = self.backend_factory()
        if not backend.is_available():
            QMessageBox.warning(
                self,
                "WaveRouter",
                "SoundVolumeView.exe n'est pas configuré.\n"
                "Renseignez son chemin dans l'onglet Réglages.",
            )
            return
        channels, error = try_detect_wavelink_channels(backend)
        if channels:
            self._known_channels = channels
            QMessageBox.information(
                self,
                "WaveRouter",
                f"{len(channels)} périphérique(s) de sortie disponible(s) :\n\n"
                + "\n".join(f"  •  {c}" for c in channels)
                + "\n\nRepérez-y le canal correspondant à Wave Link, tel que nommé "
                "dans l'application Wave Link.",
            )
            return

        try:
            raw = list_all_render_device_names(backend)
        except Exception:
            raw = []
        if raw:
            self.logger.info("Périphériques de sortie détectés :\n" + "\n".join(f"  - {n}" for n in raw))
            QMessageBox.warning(
                self,
                "WaveRouter",
                "Aucun périphérique exploitable n'a été retenu.\n\n"
                "La liste complète a été ajoutée à l'onglet Logs.",
            )
        else:
            QMessageBox.warning(
                self,
                "WaveRouter",
                f"Aucun périphérique de sortie détecté.\n{error or ''}",
            )

    # ------------------------------------------------------------------
    # Page : Réglages
    # ------------------------------------------------------------------
    def _build_settings_page(self, layout: QVBoxLayout) -> None:
        layout.addWidget(
            PageHeader("Réglages", "Configuration du backend audio et du comportement de l'app.")
        )
        settings = self.config_manager.config.settings

        backend_card = Card()
        backend_card.body().addWidget(label("Backend audio", "h3"))
        backend_card.body().addWidget(label("Chemin vers SoundVolumeView.exe", "small"))

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.svv_edit = QLineEdit(settings.soundvolumeview_path)
        self.svv_edit.setMinimumHeight(34)
        path_row.addWidget(self.svv_edit, 1)
        path_row.addWidget(button("Parcourir...", "", self._browse_svv))
        path_row.addWidget(button("Télécharger", "", self._open_download))
        backend_card.body().addLayout(path_row)

        default_row = QHBoxLayout()
        default_row.setSpacing(10)
        default_row.addWidget(label("Canal proposé par défaut", "body"))
        self.default_channel_edit = QLineEdit(settings.default_channel)
        self.default_channel_edit.setPlaceholderText("Ex: Games!")
        self.default_channel_edit.setMinimumHeight(34)
        self.default_channel_edit.setMaximumWidth(280)
        default_row.addWidget(self.default_channel_edit)
        default_row.addStretch(1)
        backend_card.body().addLayout(default_row)
        layout.addWidget(backend_card)

        behavior_card = Card()
        behavior_card.body().addWidget(label("Comportement", "h3"))

        interval_row = QHBoxLayout()
        interval_row.setSpacing(10)
        interval_row.addWidget(label("Intervalle de vérification (secondes)", "body"))
        self.poll_spin = QDoubleSpinBox()
        self.poll_spin.setRange(0.5, 60.0)
        self.poll_spin.setSingleStep(0.5)
        self.poll_spin.setDecimals(1)
        self.poll_spin.setValue(settings.poll_interval)
        self.poll_spin.setMinimumHeight(32)
        self.poll_spin.setMaximumWidth(100)
        interval_row.addWidget(self.poll_spin)
        interval_row.addStretch(1)
        behavior_card.body().addLayout(interval_row)

        self.notif_check = QCheckBox("Afficher une notification lors d'un routage")
        self.notif_check.setChecked(settings.notifications_enabled)
        self.autodetect_check = QCheckBox("Proposer automatiquement les nouveaux jeux détectés")
        self.autodetect_check.setChecked(settings.auto_detect_games)
        self.autostart_check = QCheckBox("Lancer WaveRouter au démarrage de Windows")
        self.autostart_check.setChecked(settings.autostart)
        self.minimize_check = QCheckBox("Réduire dans la barre système à la fermeture")
        self.minimize_check.setChecked(settings.minimize_to_tray_on_close)
        self.debug_check = QCheckBox("Mode debug / verbose (diagnostic de la détection)")
        self.debug_check.setChecked(settings.debug)
        for box in (
            self.notif_check,
            self.autodetect_check,
            self.autostart_check,
            self.minimize_check,
            self.debug_check,
        ):
            behavior_card.body().addWidget(box)
        layout.addWidget(behavior_card)

        save_row = QHBoxLayout()
        save_row.addWidget(button("Enregistrer les réglages", "primary", self._save_settings))
        self.settings_status = label("", "success")
        save_row.addWidget(self.settings_status)
        save_row.addStretch(1)
        layout.addLayout(save_row)
        layout.addStretch(1)

    def _open_download(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl(SOUNDVOLUMEVIEW_DOWNLOAD_URL))

    def _browse_svv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner SoundVolumeView.exe", "", "SoundVolumeView.exe;;Tous les fichiers (*)"
        )
        if path:
            self.svv_edit.setText(os.path.normpath(path))

    def _reconcile_autostart(self) -> None:
        """
        Aligne la case « démarrage automatique » sur l'état réel du registre.

        Deux dérives sont corrigées ici. L'entrée peut avoir été supprimée en
        dehors de l'application, auquel cas la case resterait cochée sans que
        rien ne démarre. Elle peut aussi désigner un ancien emplacement après
        un déplacement ou un renommage du dossier : la clé existe toujours,
        l'application se croit configurée, mais plus rien ne se lance. On la
        réécrit alors vers l'exécutable courant.
        """
        settings = self.config_manager.config.settings

        if autostart.is_stale():
            try:
                autostart.set_enabled(True)
                self.logger.info(
                    "Démarrage automatique réparé : il désignait un emplacement obsolète."
                )
            except OSError as exc:
                self.logger.error(f"Démarrage automatique non réparable : {exc}")

        actual = autostart.is_enabled()
        if actual == settings.autostart:
            return
        settings.autostart = actual
        self.autostart_check.setChecked(actual)
        self._save_config()

    def _save_settings(self) -> None:
        settings = self.config_manager.config.settings
        settings.soundvolumeview_path = self.svv_edit.text().strip()
        settings.default_channel = self.default_channel_edit.text().strip()
        settings.poll_interval = float(self.poll_spin.value())
        settings.notifications_enabled = self.notif_check.isChecked()
        settings.auto_detect_games = self.autodetect_check.isChecked()
        settings.minimize_to_tray_on_close = self.minimize_check.isChecked()
        settings.debug = self.debug_check.isChecked()

        wants_autostart = self.autostart_check.isChecked()
        if wants_autostart != settings.autostart:
            try:
                autostart.set_enabled(wants_autostart)
                settings.autostart = wants_autostart
            except OSError as exc:
                self.autostart_check.setChecked(settings.autostart)
                QMessageBox.critical(
                    self, "WaveRouter", f"Impossible de modifier le démarrage automatique :\n{exc}"
                )

        self._save_config()
        self.logger.debug = settings.debug
        self.settings_status.setText("Réglages enregistrés.")
        # Le message s'efface seul : laissé en place, il finirait par décrire
        # un état qui n'est plus celui du formulaire affiché.
        from PySide6.QtCore import QTimer

        QTimer.singleShot(4000, lambda: self.settings_status.setText(""))
        self.logger.info("Réglages mis à jour.")
        self.refresh_channels_async()

    # ------------------------------------------------------------------
    # Page : Logs
    # ------------------------------------------------------------------
    def _build_logs_page(self, layout: QVBoxLayout) -> None:
        header = PageHeader("Logs", "Historique complet des événements de l'application.")
        header.add_action(button("Ouvrir le dossier des logs", "", self._open_logs_folder))
        header.add_action(button("Effacer l'affichage", "", lambda: self.log_view.clear()))
        layout.addWidget(header)

        card = Card()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(_MAX_LOG_BLOCKS)
        card.body().addWidget(self.log_view)
        layout.addWidget(card, 1)

    def _load_log_history(self) -> None:
        """Réaffiche les derniers événements du fichier au lancement."""
        lines = self.logger.read_recent_lines()
        if lines:
            self.log_view.setPlainText("\n".join(lines))
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum()
            )

    def _open_logs_folder(self) -> None:
        from waverouter.config import get_logs_dir

        try:
            os.startfile(get_logs_dir())  # nosec - dossier local uniquement
        except OSError as exc:
            QMessageBox.critical(self, "WaveRouter", f"Impossible d'ouvrir le dossier :\n{exc}")

    def _append_log(self, line: str) -> None:
        """
        Ajoute une ligne au panneau de logs.

        Le panneau « Routages effectués » du tableau de bord n'est
        volontairement pas alimenté ici : il ne liste que les routages
        confirmés. Y déverser tous les logs ferait apparaître chaque routage
        deux fois.
        """
        self.log_view.appendPlainText(line)

    def log_line(self, line: str) -> None:
        """Point d'entrée du logger, appelable depuis n'importe quel thread."""
        self.log_received.emit(line)

    # ------------------------------------------------------------------
    # Surveillance
    # ------------------------------------------------------------------
    def _toggle_monitor(self) -> None:
        self.monitor.toggle_pause()  # notifie l'interface via son callback

    def refresh_monitor_state(self) -> None:
        """
        Resynchronise tous les indicateurs d'état de la surveillance.

        Appelée aussi bien après un clic dans la fenêtre qu'après une bascule
        depuis la barre système : les deux chemins doivent aboutir au même
        affichage.
        """
        paused = self.monitor.is_paused
        self.status_dot.set_color(theme.WARNING if paused else theme.SUCCESS)
        self.status_label.setText("En pause" if paused else "Surveillance active")
        self.status_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-weight: 700; font-size: {theme.SIZE_SMALL}px;"
        )
        self.toggle_button.setText("Reprendre" if paused else "Mettre en pause")
        self.refresh_dashboard()

    # ------------------------------------------------------------------
    # Fermeture / réduction dans la barre système
    # ------------------------------------------------------------------
    def prepare_quit(self) -> None:
        """Autorise la fermeture définitive (demandée depuis la barre système)."""
        self._really_quit = True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._really_quit or not self.config_manager.config.settings.minimize_to_tray_on_close:
            event.accept()
            return
        event.ignore()
        self.hide()
        self.on_close_to_tray()

    def show_and_focus(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
