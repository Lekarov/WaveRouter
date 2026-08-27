"""
Système de design de WaveRouter : palette, typographies et feuille de style
Qt appliquée à toute l'application.

Esprit inchangé depuis la version 1 : sombre, épuré, "control center" façon
logiciels de streaming (Wave Link, OBS). Qt permet en revanche ce que le
canevas Tk ne savait pas rendre : ombres portées, transitions au survol,
coins arrondis nets et mise à l'échelle correcte sur écran haute densité.

Toute la mise en forme passe par la feuille QSS ci-dessous plutôt que par
des couleurs posées widget par widget : un seul endroit à modifier pour
changer l'apparence de l'application entière.
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
ACCENT_PRESSED = "#6B4CE0"
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

SIZE_H1 = 22
SIZE_H2 = 16
SIZE_H3 = 13
SIZE_BODY = 13
SIZE_SMALL = 11


_ICON_CACHE: dict[str, str] = {}


def _polyline_icon(name: str, size: int, color: str, points: list[tuple[float, float]]) -> str:
    """
    Peint une polyligne dans une image et retourne son chemin.

    Qt n'accepte pas d'image en ligne dans une feuille de style : `url()`
    exige un fichier ou une ressource compilée, et un triangle tracé en
    bordures CSS, qui fonctionne sur le web, ne donne rien ici. Les quelques
    pictogrammes réclamés par la feuille sont donc peints au premier
    lancement et conservés dans le dossier de configuration.

    Les coordonnées sont exprimées sur une grille de `size` unités.
    """
    if name in _ICON_CACHE:
        return _ICON_CACHE[name]

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    from waverouter.config import get_config_dir

    cache_dir = get_config_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{name}.png"

    scale = 4
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidth(2 * scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline([QPointF(x * scale, y * scale) for x, y in points])
    painter.end()
    pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(path))

    # QSS attend des séparateurs avant, y compris sur Windows.
    _ICON_CACHE[name] = str(path).replace("\\", "/")
    return _ICON_CACHE[name]


def check_icon_path() -> str:
    """Coche blanche des cases à cocher."""
    return _polyline_icon("check", 18, "#FFFFFF", [(4.5, 9.5), (7.8, 12.8), (13.5, 5.8)])


def arrow_icon_path() -> str:
    """Chevron des menus déroulants."""
    return _polyline_icon("arrow_down", 12, TEXT_SECONDARY, [(3, 4.8), (6, 7.8), (9, 4.8)])


STYLESHEET = f"""
/* ---------- Base ----------
   Aucune règle de fond n'est posée sur QWidget : en Qt, une feuille de style
   s'applique au widget visé ET à toute sa descendance, si bien qu'un fond
   générique écraserait celui de chaque bouton et de chaque carte. Les fonds
   sont donc déclarés widget par widget. */
QWidget {{
    color: {TEXT_PRIMARY};
    font-family: "{FONT_FAMILY}";
    font-size: {SIZE_BODY}px;
}}
QMainWindow, QDialog, QStackedWidget {{
    background-color: {BG_APP};
}}

/* ---------- Rôles de texte ---------- */
QLabel[role="h1"]      {{ font-size: {SIZE_H1}px; font-weight: 700; color: {TEXT_PRIMARY}; }}
QLabel[role="h2"]      {{ font-size: {SIZE_H2}px; font-weight: 700; color: {TEXT_PRIMARY}; }}
QLabel[role="h3"]      {{ font-size: {SIZE_H3}px; font-weight: 700; color: {TEXT_PRIMARY}; }}
QLabel[role="body"]    {{ font-size: {SIZE_BODY}px; color: {TEXT_SECONDARY}; }}
QLabel[role="small"]   {{ font-size: {SIZE_SMALL}px; color: {TEXT_SECONDARY}; }}
QLabel[role="muted"]   {{ font-size: {SIZE_SMALL}px; color: {TEXT_MUTED}; }}
QLabel[role="danger"]  {{ font-size: {SIZE_SMALL}px; color: {DANGER}; }}
QLabel[role="success"] {{ font-size: {SIZE_SMALL}px; color: {SUCCESS}; }}
QLabel[role="statValue"] {{ font-size: {SIZE_H2}px; font-weight: 700; }}
QLabel[role="brand"]   {{ font-size: {SIZE_H2}px; font-weight: 700; color: {TEXT_PRIMARY}; }}

/* ---------- Conteneurs ---------- */
QFrame#Sidebar {{
    background-color: {BG_SIDEBAR};
}}
QFrame[role="card"] {{
    background-color: {BG_CARD};
    border-radius: {RADIUS_CARD}px;
}}
QFrame[role="cardAlt"] {{
    background-color: {BG_CARD_ALT};
    border-radius: {RADIUS_CARD}px;
}}

/* Fiche de jeu. La teinte et la bordure réagissent au survol, ce que le
   canevas Tk ne savait pas faire sur un conteneur entier. Un jeu en cours
   d'exécution se signale par une bordure d'accent, visible d'un coup d'œil
   au milieu de la grille. */
QFrame[role="gameCard"] {{
    background-color: {BG_CARD};
    border-radius: {RADIUS_CARD}px;
    border: 1px solid {BORDER_SOFT};
}}
QFrame[role="gameCard"]:hover {{
    background-color: {BG_CARD_HOVER};
    border: 1px solid {TEXT_MUTED};
}}
QFrame[role="gameCard"][running="yes"] {{
    border: 1px solid {ACCENT};
    background-color: {BG_CARD};
}}
QFrame[role="gameCard"][running="yes"]:hover {{
    background-color: {BG_CARD_HOVER};
}}

/* ---------- Boutons ---------- */
/* La bordure est indispensable : posé sur une carte, un bouton secondaire
   n'aurait sinon presque aucun contraste avec elle. */
QPushButton {{
    background-color: {BG_CARD_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 8px 14px;
    font-size: {SIZE_BODY}px;
}}
QPushButton:hover  {{ background-color: {BG_CARD_HOVER}; border-color: {TEXT_MUTED}; }}
QPushButton:pressed {{ background-color: {BG_INPUT}; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: {BORDER_SOFT}; }}

QPushButton[role="primary"] {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover   {{ background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:pressed {{ background-color: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}

QPushButton[role="ghost"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {TEXT_SECONDARY};
    padding: 6px 10px;
}}
QPushButton[role="ghost"]:hover {{
    background-color: {BG_CARD_HOVER};
    color: {TEXT_PRIMARY};
}}

QPushButton[role="link"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {ACCENT};
    padding: 4px 8px;
    font-size: {SIZE_SMALL}px;
}}
QPushButton[role="link"]:hover {{ color: {ACCENT_HOVER}; }}

/* Icônes d'action d'une ligne de jeu */
QPushButton[role="iconAction"], QPushButton[role="iconDanger"] {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_BUTTON}px;
    padding: 0px;
}}
QPushButton[role="iconAction"]:hover {{
    background-color: {BG_CARD_ALT};
    border-color: {BORDER};
}}
QPushButton[role="iconDanger"]:hover {{
    background-color: {DANGER_SOFT};
    border-color: {DANGER};
}}

/* Navigation latérale */
QPushButton[role="nav"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {TEXT_SECONDARY};
    text-align: left;
    padding: 10px 14px;
    border-radius: {RADIUS_BUTTON}px;
}}
QPushButton[role="nav"]:hover {{
    background-color: {BG_CARD_HOVER};
    color: {TEXT_PRIMARY};
}}
QPushButton[role="nav"]:checked {{
    background-color: {ACCENT_SOFT};
    color: {TEXT_PRIMARY};
    font-weight: 600;
}}

/* ---------- Champs de saisie ---------- */
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_INPUT}px;
    padding: 7px 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit::placeholder {{ color: {TEXT_MUTED}; }}

QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: url("__ARROW_ICON__");
    width: 12px;
    height: 12px;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_INPUT}px;
    selection-background-color: {ACCENT_SOFT};
    color: {TEXT_PRIMARY};
    padding: 4px;
    outline: none;
}}

/* ---------- Cases à cocher ---------- */
QCheckBox {{
    spacing: 10px;
    color: {TEXT_PRIMARY};
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {BORDER};
    background-color: {BG_INPUT};
}}
QCheckBox::indicator:hover {{ border: 1px solid {ACCENT}; }}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    image: url("__CHECK_ICON__");
}}

/* ---------- Listes (remplacent le ttk.Treeview de la version 1) ---------- */
QTreeWidget, QListWidget {{
    background-color: transparent;
    border: none;
    outline: none;
    color: {TEXT_PRIMARY};
}}
QTreeWidget::item, QListWidget::item {{
    padding: 7px 4px;
    border-radius: 6px;
}}
QTreeWidget::item:hover, QListWidget::item:hover {{
    background-color: {BG_CARD_HOVER};
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {TEXT_PRIMARY};
}}
QHeaderView::section {{
    background-color: transparent;
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 4px;
    font-size: {SIZE_SMALL}px;
    font-weight: 600;
}}

/* ---------- Zones de texte ---------- */
QPlainTextEdit, QTextEdit {{
    background-color: transparent;
    border: none;
    color: {TEXT_SECONDARY};
    font-family: "{FONT_FAMILY_MONO}", "Consolas", monospace;
    font-size: 12px;
    selection-background-color: {ACCENT};
}}

/* ---------- Barres de défilement ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BG_CARD_ALT};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {BG_CARD_ALT};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {TEXT_MUTED}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ---------- Divers ---------- */
QToolTip {{
    background-color: {BG_CARD_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
}}
QMenu {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 24px 7px 12px;
    border-radius: 6px;
    color: {TEXT_PRIMARY};
}}
QMenu::item:selected {{ background-color: {ACCENT_SOFT}; }}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 5px 8px;
}}
"""


def stylesheet() -> str:
    """
    Feuille de style prête à appliquer, pictogrammes résolus.

    À n'appeler qu'une fois QApplication créée : les pictogrammes sont peints
    avec QPainter, ce qui exige une application Qt vivante.
    """
    return STYLESHEET.replace("__CHECK_ICON__", check_icon_path()).replace(
        "__ARROW_ICON__", arrow_icon_path()
    )
