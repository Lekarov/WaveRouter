"""
Boîtes de dialogue de l'interface : ajout/édition d'un jeu.
"""

from __future__ import annotations

import os
from tkinter import filedialog, ttk
from typing import Callable

import customtkinter as ctk

from waverouter.config import GameEntry
from waverouter.ui import theme
from waverouter.window_processes import DetectedWindow, list_visible_app_processes


class GameDialog(ctk.CTkToplevel):
    """Fenêtre modale pour ajouter ou modifier un jeu de la liste."""

    def __init__(
        self,
        master,
        channels: list[str],
        on_confirm: Callable[[GameEntry], None],
        existing: GameEntry | None = None,
    ) -> None:
        super().__init__(master)
        self.title("Modifier un jeu" if existing else "Ajouter un jeu")
        self.geometry("460x440")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_APP)
        self.transient(master)
        self.grab_set()

        self._on_confirm = on_confirm
        self._exe_path = existing.exe_path if existing else ""

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            body,
            text="Modifier un jeu" if existing else "Ajouter un jeu",
            font=theme.FONT_H2,
            text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 16))

        # --- Sélection de l'exécutable ---
        self._field_label(body, "Exécutable du jeu (.exe)")
        exe_frame = ctk.CTkFrame(body, fg_color="transparent")
        exe_frame.pack(fill="x")
        self.process_entry = self._entry(exe_frame, placeholder="jeu.exe")
        self.process_entry.pack(side="left", fill="x", expand=True)
        self._secondary_button(exe_frame, "Parcourir...", self._browse_exe, width=100).pack(
            side="left", padx=(8, 0)
        )

        # --- Libellé libre ---
        self._field_label(body, "Nom du jeu (libellé)", pady_top=16)
        self.label_entry = self._entry(body, placeholder="Ex: Hunt: Showdown")
        self.label_entry.pack(fill="x")

        # --- Canal audio cible ---
        self._field_label(body, "Canal audio cible", pady_top=16)
        self.channel_combo = ctk.CTkComboBox(
            body,
            values=channels or ["(aucun périphérique détecté)"],
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER,
            button_color=theme.BG_CARD_ALT,
            button_hover_color=theme.BG_CARD_HOVER,
            dropdown_fg_color=theme.BG_CARD,
            corner_radius=theme.RADIUS_INPUT,
        )
        self.channel_combo.pack(fill="x")
        if channels:
            self.channel_combo.set(channels[0])

        if existing:
            self.process_entry.insert(0, existing.process_name)
            self.label_entry.insert(0, existing.label)
            if existing.channel:
                self.channel_combo.set(existing.channel)

        self.error_label = ctk.CTkLabel(body, text="", font=theme.FONT_SMALL, text_color=theme.DANGER)
        self.error_label.pack(anchor="w", pady=(12, 0))

        # --- Boutons ---
        btn_frame = ctk.CTkFrame(body, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(16, 0), side="bottom")
        ctk.CTkButton(
            btn_frame,
            text="Valider",
            font=theme.FONT_BODY_BOLD,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            corner_radius=theme.RADIUS_BUTTON,
            command=self._confirm,
        ).pack(side="right")
        self._secondary_button(btn_frame, "Annuler", self.destroy).pack(side="right", padx=(0, 8))

    # -- petits helpers de style, partagés avec QuickAddDialog ------------
    @staticmethod
    def _field_label(parent, text: str, pady_top: int = 0) -> None:
        ctk.CTkLabel(parent, text=text, font=theme.FONT_SMALL_BOLD, text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", pady=(pady_top, 4)
        )

    @staticmethod
    def _entry(parent, placeholder: str = "") -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            placeholder_text=placeholder,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER,
            corner_radius=theme.RADIUS_INPUT,
        )

    @staticmethod
    def _secondary_button(parent, text: str, command, width: int | None = None) -> ctk.CTkButton:
        kwargs = {"width": width} if width else {}
        return ctk.CTkButton(
            parent,
            text=text,
            font=theme.FONT_BODY,
            fg_color=theme.BG_CARD_ALT,
            hover_color=theme.BG_CARD_HOVER,
            text_color=theme.TEXT_PRIMARY,
            corner_radius=theme.RADIUS_BUTTON,
            command=command,
            **kwargs,
        )

    def _browse_exe(self) -> None:
        path = filedialog.askopenfilename(
            title="Sélectionner l'exécutable du jeu",
            filetypes=[("Exécutables", "*.exe"), ("Tous les fichiers", "*.*")],
        )
        if not path:
            return
        process_name = os.path.basename(path)
        self.process_entry.delete(0, "end")
        self.process_entry.insert(0, process_name)
        self._exe_path = path
        if not self.label_entry.get().strip():
            # Propose un libellé par défaut à partir du nom de fichier
            guessed_label = os.path.splitext(process_name)[0]
            self.label_entry.insert(0, guessed_label)

    def _confirm(self) -> None:
        process_name = self.process_entry.get().strip()
        label = self.label_entry.get().strip()
        channel = self.channel_combo.get().strip()

        if not process_name:
            self.error_label.configure(text="Le nom du processus est requis.")
            return
        if not label:
            self.error_label.configure(text="Le libellé du jeu est requis.")
            return
        if not channel or channel == "(aucun périphérique détecté)":
            self.error_label.configure(text="Sélectionnez un canal audio valide.")
            return

        # Le chemin choisi (via Parcourir ou détection) sert uniquement à
        # afficher l'icône : on le garde même si le libellé du processus a
        # ensuite été corrigé à la main (fréquent avec les jeux Unreal, où
        # l'exécutable repéré et le process réel surveillé peuvent différer).
        self._on_confirm(
            GameEntry(
                label=label, process_name=process_name, channel=channel, exe_path=self._exe_path
            )
        )
        self.destroy()


class QuickAddDialog(ctk.CTkToplevel):
    """
    Fenêtre modale listant les applications actuellement ouvertes
    (fenêtres visibles), pour ajouter un jeu sans avoir à parcourir
    manuellement son chemin d'exécutable.
    """

    def __init__(
        self,
        master,
        channels: list[str],
        on_confirm: Callable[[GameEntry], None],
    ) -> None:
        super().__init__(master)
        self.title("Détecter un jeu en cours")
        self.geometry("540x460")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_APP)
        self.transient(master)
        self.grab_set()

        self._channels = channels
        self._on_confirm = on_confirm
        self._detected: list[DetectedWindow] = []

        theme.style_treeview_dark()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            body, text="Détecter un jeu en cours", font=theme.FONT_H2, text_color=theme.TEXT_PRIMARY
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            body,
            text="Sélectionnez l'application à ajouter parmi celles actuellement ouvertes.",
            font=theme.FONT_BODY,
            text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 16))

        # Les widgets ancrés en bas doivent être empaquetés AVANT le
        # Treeview : avec pack(), le premier widget à demander expand=True
        # capte tout l'espace restant, quel que soit son `side` — s'il est
        # empaqueté en premier, les boutons placés après lui n'ont plus de
        # place et deviennent invisibles.
        btn_frame = ctk.CTkFrame(body, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(12, 0), side="bottom")
        ctk.CTkButton(
            btn_frame,
            text="Utiliser ce jeu",
            font=theme.FONT_BODY_BOLD,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            corner_radius=theme.RADIUS_BUTTON,
            command=self._confirm,
        ).pack(side="right")
        GameDialog._secondary_button(btn_frame, "Annuler", self.destroy).pack(
            side="right", padx=(0, 8)
        )
        GameDialog._secondary_button(btn_frame, "Actualiser", self._refresh).pack(side="left")

        self.status_label = ctk.CTkLabel(
            body, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED
        )
        self.status_label.pack(anchor="w", pady=(8, 0), side="bottom")

        tree_card = ctk.CTkFrame(body, fg_color=theme.BG_CARD, corner_radius=theme.RADIUS_CARD)
        tree_card.pack(fill="both", expand=True)

        columns = ("title", "process")
        self.tree = ttk.Treeview(
            tree_card, columns=columns, show="headings", style="WaveRouter.Treeview"
        )
        self.tree.heading("title", text="Fenêtre")
        self.tree.heading("process", text="Processus")
        self.tree.column("title", width=300)
        self.tree.column("process", width=180)
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", lambda _event: self._confirm())

        self._refresh()

    def _refresh(self) -> None:
        self._detected = list_visible_app_processes()
        self.tree.delete(*self.tree.get_children())
        for index, window in enumerate(self._detected):
            self.tree.insert("", "end", iid=str(index), values=(window.title, window.process_name))
        if not self._detected:
            self.status_label.configure(
                text="Aucune fenêtre détectée. Lancez le jeu puis cliquez sur Actualiser."
            )
        else:
            self.status_label.configure(text=f"{len(self._detected)} application(s) détectée(s).")

    def _confirm(self) -> None:
        selection = self.tree.selection()
        if not selection:
            self.status_label.configure(text="Sélectionnez une application dans la liste.")
            return
        window = self._detected[int(selection[0])]
        parent = self.master
        self.destroy()
        GameDialog(
            parent,
            channels=self._channels,
            on_confirm=self._on_confirm,
            existing=GameEntry(
                label=window.title,
                process_name=window.process_name,
                channel="",
                exe_path=window.exe_path,
            ),
        )
