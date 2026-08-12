"""
Système de design de WaveRouter : palette de couleurs, typographies et
constantes de style partagées par toute l'interface (fenêtre principale,
dialogues, system tray).

Esprit : sombre, épuré, "control center" façon logiciels de streaming
(Wave Link, OBS) — cartes arrondies, accent violet électrique, hiérarchie
typographique claire, peu de bruit visuel.
"""

from __future__ import annotations

# --- Couleurs de fond -------------------------------------------------
BG_APP = "#0c0e13"           # Fond général de la fenêtre
BG_SIDEBAR = "#111319"        # Panneau de navigation latéral
BG_CARD = "#171a22"           # Cartes / panneaux de contenu
BG_CARD_ALT = "#1c202b"       # Cartes secondaires / lignes alternées
BG_CARD_HOVER = "#20242f"     # Survol de carte
BG_INPUT = "#1a1d26"          # Champs de saisie

# --- Bordures -----------------------------------------------------------
BORDER = "#242835"
BORDER_SOFT = "#1c1f29"

# --- Texte ---------------------------------------------------------------
TEXT_PRIMARY = "#F3F4F6"
TEXT_SECONDARY = "#9AA1B1"
TEXT_MUTED = "#5C6376"

# --- Couleur d'accent (marque WaveRouter) --------------------------------
ACCENT = "#7C5CFF"
ACCENT_HOVER = "#8F72FF"
# Tkinter ne supporte pas l'alpha en hex : les variantes "soft" sont des
# teintes pré-mélangées (accent/état à faible opacité sur BG_CARD).
ACCENT_SOFT = "#241F3D"

# --- États sémantiques ----------------------------------------------------
SUCCESS = "#22C55E"
SUCCESS_SOFT = "#16281E"
DANGER = "#EF4444"
DANGER_HOVER = "#DC3737"
DANGER_SOFT = "#2E1B1B"
WARNING = "#F59E0B"
WARNING_SOFT = "#332310"

# --- Rayons d'arrondi ------------------------------------------------------
RADIUS_CARD = 14
RADIUS_BUTTON = 10
RADIUS_BADGE = 8
RADIUS_INPUT = 8

# --- Typographies ----------------------------------------------------------
FONT_FAMILY = "Segoe UI"
FONT_FAMILY_MONO = "Cascadia Mono"

FONT_H1 = (FONT_FAMILY, 22, "bold")
FONT_H2 = (FONT_FAMILY, 16, "bold")
FONT_H3 = (FONT_FAMILY, 13, "bold")
FONT_BODY = (FONT_FAMILY, 13)
FONT_BODY_BOLD = (FONT_FAMILY, 13, "bold")
FONT_SMALL = (FONT_FAMILY, 11)
FONT_SMALL_BOLD = (FONT_FAMILY, 11, "bold")
FONT_MONO = (FONT_FAMILY_MONO, 12)


def style_treeview_dark() -> None:
    """
    Configure le style ttk.Treeview (utilisé pour la liste de fenêtres
    détectées dans QuickAddDialog) pour coller à la palette WaveRouter.
    """
    from tkinter import ttk

    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "WaveRouter.Treeview",
        background=BG_CARD,
        fieldbackground=BG_CARD,
        foreground=TEXT_PRIMARY,
        rowheight=30,
        borderwidth=0,
        font=FONT_BODY,
    )
    style.configure(
        "WaveRouter.Treeview.Heading",
        background=BG_SIDEBAR,
        foreground=TEXT_SECONDARY,
        borderwidth=0,
        font=FONT_SMALL_BOLD,
    )
    style.map(
        "WaveRouter.Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", TEXT_PRIMARY)],
    )
    style.layout("WaveRouter.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])


def nav_button_colors(active: bool) -> dict:
    """Couleurs d'un bouton de navigation latérale selon son état actif."""
    if active:
        return {
            "fg_color": ACCENT_SOFT,
            "text_color": TEXT_PRIMARY,
            "hover_color": ACCENT_SOFT,
        }
    return {
        "fg_color": "transparent",
        "text_color": TEXT_SECONDARY,
        "hover_color": BG_CARD_HOVER,
    }
