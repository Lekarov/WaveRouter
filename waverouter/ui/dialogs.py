"""
Boîtes de dialogue : ajout et édition d'un jeu, détection d'une application
en cours, import de la bibliothèque installée, proposition d'un jeu
nouvellement détecté.

Les listes s'appuient sur QTreeWidget, qui suit la feuille de style de
l'application. La version 1 devait recourir à un ttk.Treeview au thème
bricolé, visiblement étranger au reste de l'interface.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from waverouter.config import GameEntry
from waverouter.game_library import InstalledGame, scan_installed_games
from waverouter.ui import theme
from waverouter.ui.widgets import Card, button, label
from waverouter.window_processes import DetectedWindow, list_visible_app_processes

_NO_CHANNEL_PLACEHOLDER = "(aucun périphérique détecté)"


def _channel_combo(channels: list[str]) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)  # un canal Wave Link peut être saisi à la main
    combo.addItems(channels or [_NO_CHANNEL_PLACEHOLDER])
    combo.setMinimumHeight(34)
    return combo


def _field(parent_layout: QVBoxLayout, text: str, widget: QWidget) -> QWidget:
    parent_layout.addWidget(label(text, "small"))
    parent_layout.addWidget(widget)
    return widget


class _BaseDialog(QDialog):
    """Fenêtre modale au thème de l'application."""

    def __init__(self, parent, title: str, width: int, height: int) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(width, height)
        self.setStyleSheet(theme.stylesheet())

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(24, 24, 24, 24)
        self._root.setSpacing(14)

    def add_title(self, title: str, subtitle: str = "") -> None:
        self._root.addWidget(label(title, "h2"))
        if subtitle:
            sub = label(subtitle, "body")
            sub.setWordWrap(True)
            self._root.addWidget(sub)


class GameDialog(_BaseDialog):
    """Ajout ou modification d'un jeu de la liste."""

    def __init__(
        self,
        parent,
        channels: list[str],
        on_confirm: Callable[[GameEntry], None],
        existing: GameEntry | None = None,
        is_duplicate: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(
            parent, "Modifier un jeu" if existing else "Ajouter un jeu", 480, 460
        )
        self._on_confirm = on_confirm
        self._is_duplicate = is_duplicate
        self._exe_path = existing.exe_path if existing else ""

        self.add_title("Modifier un jeu" if existing else "Ajouter un jeu")

        exe_row = QHBoxLayout()
        exe_row.setSpacing(8)
        self.process_edit = QLineEdit()
        self.process_edit.setPlaceholderText("jeu.exe")
        self.process_edit.setMinimumHeight(34)
        exe_row.addWidget(self.process_edit, 1)
        exe_row.addWidget(button("Parcourir...", "", self._browse_exe))
        self._root.addWidget(label("Exécutable du jeu (.exe)", "small"))
        self._root.addLayout(exe_row)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Ex: Hunt: Showdown")
        self.label_edit.setMinimumHeight(34)
        _field(self._root, "Nom du jeu (libellé)", self.label_edit)

        self.channel_combo = _channel_combo(channels)
        _field(self._root, "Canal audio cible", self.channel_combo)

        self.enabled_check = QCheckBox("Surveiller ce jeu")
        self.enabled_check.setChecked(existing.enabled if existing else True)
        self._root.addWidget(self.enabled_check)

        if existing:
            self.process_edit.setText(existing.process_name)
            self.label_edit.setText(existing.label)
            if existing.channel:
                self.channel_combo.setCurrentText(existing.channel)

        self.error_label = label("", "danger")
        self.error_label.setWordWrap(True)
        self._root.addWidget(self.error_label)
        self._root.addStretch(1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(button("Annuler", "", self.reject))
        actions.addWidget(button("Valider", "primary", self._confirm))
        self._root.addLayout(actions)

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner l'exécutable du jeu", "", "Exécutables (*.exe);;Tous les fichiers (*)"
        )
        if not path:
            return
        process_name = os.path.basename(path)
        self.process_edit.setText(process_name)
        self._exe_path = os.path.normpath(path)
        if not self.label_edit.text().strip():
            # Propose un libellé par défaut à partir du nom de fichier
            self.label_edit.setText(os.path.splitext(process_name)[0])

    def _confirm(self) -> None:
        process_name = self.process_edit.text().strip()
        game_label = self.label_edit.text().strip()
        channel = self.channel_combo.currentText().strip()

        if not process_name:
            self.error_label.setText("Le nom du processus est requis.")
            return
        if not process_name.lower().endswith(".exe"):
            self.error_label.setText(
                "Le nom du processus doit se terminer par .exe (ex: jeu.exe)."
            )
            return
        if not game_label:
            self.error_label.setText("Le libellé du jeu est requis.")
            return
        if not channel or channel == _NO_CHANNEL_PLACEHOLDER:
            self.error_label.setText("Sélectionnez un canal audio valide.")
            return
        if self._is_duplicate and self._is_duplicate(process_name):
            self.error_label.setText(
                f"{process_name} est déjà surveillé. Modifiez l'entrée existante."
            )
            return

        # Le chemin choisi sert uniquement à afficher l'icône : on le garde
        # même si le nom du processus a ensuite été corrigé à la main, cas
        # fréquent avec les jeux Unreal dont le lanceur et le processus réel
        # portent des noms différents.
        self._on_confirm(
            GameEntry(
                label=game_label,
                process_name=process_name,
                channel=channel,
                exe_path=self._exe_path,
                enabled=self.enabled_check.isChecked(),
            )
        )
        self.accept()


class QuickAddDialog(_BaseDialog):
    """Liste les applications ayant une fenêtre visible, pour un ajout rapide."""

    def __init__(
        self,
        parent,
        channels: list[str],
        on_confirm: Callable[[GameEntry], None],
        is_duplicate: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(parent, "Détecter un jeu en cours", 620, 520)
        self._channels = channels
        self._on_confirm = on_confirm
        self._is_duplicate = is_duplicate
        self._detected: list[DetectedWindow] = []

        self.add_title(
            "Détecter un jeu en cours",
            "Sélectionnez l'application à ajouter parmi celles actuellement ouvertes.",
        )

        card = Card(padding=(12, 12, 12, 12))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Fenêtre", "Processus"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemDoubleClicked.connect(lambda *_: self._confirm())
        card.body().addWidget(self.tree)
        self._root.addWidget(card, 1)

        self.status_label = label("", "muted")
        self._root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addWidget(button("Actualiser", "", self._refresh))
        actions.addStretch(1)
        actions.addWidget(button("Annuler", "", self.reject))
        actions.addWidget(button("Utiliser ce jeu", "primary", self._confirm))
        self._root.addLayout(actions)

        self._refresh()

    def _refresh(self) -> None:
        self._detected = list_visible_app_processes()
        self.tree.clear()
        for window in self._detected:
            QTreeWidgetItem(self.tree, [window.title, window.process_name])
        if self._detected:
            self.status_label.setText(f"{len(self._detected)} application(s) détectée(s).")
        else:
            self.status_label.setText(
                "Aucune fenêtre détectée. Lancez le jeu puis cliquez sur Actualiser."
            )

    def _confirm(self) -> None:
        index = self.tree.indexOfTopLevelItem(self.tree.currentItem())
        if index < 0:
            self.status_label.setText("Sélectionnez une application dans la liste.")
            return
        window = self._detected[index]
        self.accept()
        GameDialog(
            self.parent(),
            channels=self._channels,
            on_confirm=self._on_confirm,
            is_duplicate=self._is_duplicate,
            existing=GameEntry(
                label=window.title,
                process_name=window.process_name,
                channel="",
                exe_path=window.exe_path,
            ),
        ).exec()


class _ScanSignals(QObject):
    """Passerelle du thread de balayage vers le thread de l'interface."""

    done = Signal(list)
    failed = Signal(str)


class LibraryDialog(_BaseDialog):
    """
    Import des jeux installés : Steam, Epic Games, GOG, et dossiers ajoutés
    à la main pour les jeux qu'aucun launcher ne référence.

    Le balayage touche le disque, il tourne donc dans un thread dédié et
    remonte son résultat par signal Qt, qui bascule automatiquement sur le
    thread de l'interface.
    """

    def __init__(
        self,
        parent,
        channels: list[str],
        on_import: Callable[[list[GameEntry]], None],
        is_duplicate: Callable[[str], bool],
        folders: list[str] | None = None,
        on_add_folder: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(parent, "Importer mes jeux installés", 760, 600)
        self._channels = channels
        self._on_import = on_import
        self._is_duplicate = is_duplicate
        self._folders = list(folders or [])
        self._on_add_folder = on_add_folder
        self._games: list[InstalledGame] = []

        self._signals = _ScanSignals()
        self._signals.done.connect(self._populate)
        self._signals.failed.connect(self._scan_failed)

        self.add_title(
            "Importer mes jeux installés",
            "Jeux trouvés dans vos bibliothèques Steam, Epic Games et GOG. "
            "Ajoutez un dossier pour les jeux installés à la main.",
        )

        card = Card(padding=(12, 12, 12, 12))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Jeu", "Source", "Processus surveillé"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        card.body().addWidget(self.tree)
        self._root.addWidget(card, 1)

        self.folders_label = label("", "muted")
        self.folders_label.setWordWrap(True)
        self._root.addWidget(self.folders_label)

        channel_row = QHBoxLayout()
        channel_row.addWidget(label("Canal cible :", "body"))
        self.channel_combo = _channel_combo(channels)
        self.channel_combo.setMinimumWidth(240)
        channel_row.addWidget(self.channel_combo)
        channel_row.addStretch(1)
        self.status_label = label("Analyse des bibliothèques en cours...", "muted")
        channel_row.addWidget(self.status_label)
        self._root.addLayout(channel_row)

        actions = QHBoxLayout()
        actions.addWidget(button("Ajouter un dossier...", "", self._add_folder))
        actions.addWidget(button("Tout sélectionner", "", self.tree.selectAll))
        actions.addStretch(1)
        actions.addWidget(button("Fermer", "", self.reject))
        actions.addWidget(button("Importer la sélection", "primary", self._confirm))
        self._root.addLayout(actions)

        self._refresh_folders_label()
        self._start_scan()

    def _refresh_folders_label(self) -> None:
        if self._folders:
            self.folders_label.setText("Dossiers suivis : " + "   ".join(self._folders))
        else:
            self.folders_label.setText(
                "Aucun dossier personnalisé. Utilisez « Ajouter un dossier... » "
                "pour vos jeux hors launcher."
            )

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Sélectionner un dossier contenant vos jeux"
        )
        if not folder:
            return
        folder = os.path.normpath(folder)
        if self._on_add_folder and not self._on_add_folder(folder):
            self.status_label.setText("Ce dossier est déjà suivi.")
            return
        self._folders.append(folder)
        self._refresh_folders_label()
        self._start_scan()

    def _start_scan(self) -> None:
        self.status_label.setText("Analyse des bibliothèques en cours...")
        folders = list(self._folders)

        def work() -> None:
            try:
                games = scan_installed_games(extra_folders=folders)
            except Exception as exc:
                self._signals.failed.emit(str(exc))
                return
            self._signals.done.emit(games)

        threading.Thread(target=work, daemon=True, name="WaveRouterLibraryScan").start()

    def _scan_failed(self, message: str) -> None:
        self.status_label.setText(f"Analyse impossible : {message}")

    def _populate(self, games: list) -> None:
        self._games = games
        self.tree.clear()
        for game in games:
            already = self._is_duplicate(game.process_name)
            item = QTreeWidgetItem(
                self.tree,
                [
                    game.name + ("   (déjà surveillé)" if already else ""),
                    game.source,
                    game.process_name,
                ],
            )
            if already:
                item.setForeground(0, Qt.gray)
        if games:
            self.status_label.setText(f"{len(games)} jeu(x) détecté(s).")
        else:
            self.status_label.setText(
                "Aucun jeu détecté. Ajoutez un dossier ou saisissez le jeu à la main."
            )

    def _confirm(self) -> None:
        selection = self.tree.selectedItems()
        if not selection:
            self.status_label.setText("Sélectionnez au moins un jeu dans la liste.")
            return
        channel = self.channel_combo.currentText().strip()
        if not channel or channel == _NO_CHANNEL_PLACEHOLDER:
            self.status_label.setText("Sélectionnez un canal audio valide.")
            return

        entries: list[GameEntry] = []
        for item in selection:
            game = self._games[self.tree.indexOfTopLevelItem(item)]
            if self._is_duplicate(game.process_name):
                continue
            entries.append(
                GameEntry(
                    label=game.name,
                    process_name=game.process_name,
                    channel=channel,
                    exe_path=game.exe_path,
                )
            )
        if not entries:
            self.status_label.setText("Ces jeux sont déjà tous surveillés.")
            return
        self._on_import(entries)
        self.accept()


class NewGameDialog(_BaseDialog):
    """
    Proposition d'ajout d'un jeu repéré automatiquement par la surveillance.

    Trois issues : l'ajouter, l'écarter définitivement, ou remettre à plus tard.
    """

    def __init__(
        self,
        parent,
        process_name: str,
        exe_path: str,
        title: str,
        channels: list[str],
        on_add: Callable[[GameEntry], None],
        on_ignore: Callable[[str], None],
    ) -> None:
        super().__init__(parent, "Nouveau jeu détecté", 480, 380)
        self._process_name = process_name
        self._exe_path = exe_path
        self._on_add = on_add
        self._on_ignore = on_ignore

        self.add_title("Nouveau jeu détecté", f"{title}\n({process_name})")

        self.label_edit = QLineEdit(title or os.path.splitext(process_name)[0])
        self.label_edit.setMinimumHeight(34)
        _field(self._root, "Nom du jeu (libellé)", self.label_edit)

        self.channel_combo = _channel_combo(channels)
        _field(self._root, "Canal audio cible", self.channel_combo)

        self.error_label = label("", "danger")
        self._root.addWidget(self.error_label)
        self._root.addStretch(1)

        actions = QHBoxLayout()
        actions.addWidget(button("Ne plus proposer", "", self._ignore))
        actions.addStretch(1)
        actions.addWidget(button("Plus tard", "", self.reject))
        actions.addWidget(button("Ajouter", "primary", self._confirm))
        self._root.addLayout(actions)

    def _confirm(self) -> None:
        game_label = self.label_edit.text().strip()
        channel = self.channel_combo.currentText().strip()
        if not game_label:
            self.error_label.setText("Le libellé du jeu est requis.")
            return
        if not channel or channel == _NO_CHANNEL_PLACEHOLDER:
            self.error_label.setText("Sélectionnez un canal audio valide.")
            return
        self._on_add(
            GameEntry(
                label=game_label,
                process_name=self._process_name,
                channel=channel,
                exe_path=self._exe_path,
            )
        )
        self.accept()

    def _ignore(self) -> None:
        self._on_ignore(self._process_name)
        self.reject()
