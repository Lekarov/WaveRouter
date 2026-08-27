"""
Composants d'interface réutilisables.

Regroupe ici tout ce qui se répète d'une page à l'autre : cartes, cartes de
statistique, badges, en-têtes, boutons de navigation, ainsi que la
fabrication des icônes. Les pages n'ont alors plus qu'à assembler.
"""

from __future__ import annotations

from typing import Callable

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from waverouter.ui import theme


# ----------------------------------------------------------------------
# Fabriques élémentaires
# ----------------------------------------------------------------------
def label(text: str, role: str = "body", parent: QWidget | None = None) -> QLabel:
    """Étiquette dont l'apparence est décidée par la feuille de style."""
    widget = QLabel(text, parent)
    widget.setProperty("role", role)
    return widget


def button(
    text: str, role: str = "", on_click: Callable[[], None] | None = None
) -> QPushButton:
    widget = QPushButton(text)
    if role:
        widget.setProperty("role", role)
    widget.setCursor(Qt.PointingHandCursor)
    if on_click:
        widget.clicked.connect(lambda: on_click())
    return widget


def icon_button(kind: str, role: str, tooltip: str, on_click: Callable[[], None]) -> QPushButton:
    """
    Bouton d'action carré portant une icône dessinée.

    Les glyphes Unicode employés en version 1 ("✎", "✕") dépendaient de la
    police installée et se rendaient de travers. Les tracer soi-même garantit
    le même dessin partout, à n'importe quelle densité d'écran.
    """
    widget = button("", role, on_click)
    widget.setFixedSize(32, 32)
    widget.setToolTip(tooltip)
    color = theme.DANGER if role == "iconDanger" else theme.TEXT_SECONDARY
    widget.setIcon(QIcon(glyph_pixmap(kind, 16, color)))
    return widget


def glyph_pixmap(kind: str, size: int, color: str) -> QPixmap:
    """Dessine un pictogramme simple ("pencil" ou "cross") au trait."""
    scale = 4
    full = size * scale
    pixmap = QPixmap(full, full)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidth(int(1.6 * scale))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)

    u = full / 16.0  # unité de grille, pour raisonner sur un carré de 16
    if kind == "cross":
        painter.drawLine(4 * u, 4 * u, 12 * u, 12 * u)
        painter.drawLine(12 * u, 4 * u, 4 * u, 12 * u)
    else:  # crayon
        painter.drawLine(3.5 * u, 12.5 * u, 4.6 * u, 9.6 * u)   # pointe
        painter.drawLine(4.6 * u, 9.6 * u, 10.6 * u, 3.6 * u)   # corps
        painter.drawLine(10.6 * u, 3.6 * u, 12.4 * u, 5.4 * u)  # tête
        painter.drawLine(12.4 * u, 5.4 * u, 6.4 * u, 11.4 * u)
        painter.drawLine(6.4 * u, 11.4 * u, 3.5 * u, 12.5 * u)
    painter.end()

    return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def vspace(height: int) -> QWidget:
    spacer = QWidget()
    spacer.setFixedHeight(height)
    return spacer


class Card(QFrame):
    """
    Panneau arrondi, éventuellement souligné par une ombre portée.

    L'ombre est ce qui donne la profondeur du rendu « control center » ;
    elle reste optionnelle car un effet graphique par widget coûte cher
    lorsqu'on en empile plusieurs dizaines dans une liste défilante.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        role: str = "card",
        shadow: bool = True,
        padding: tuple[int, int, int, int] = (20, 18, 20, 18),
        spacing: int = 10,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", role)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*padding)
        self._layout.setSpacing(spacing)
        if shadow:
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(24)
            effect.setOffset(0, 4)
            effect.setColor(QColor(0, 0, 0, 110))
            self.setGraphicsEffect(effect)

    def body(self) -> QVBoxLayout:
        return self._layout


class StatCard(Card):
    """Carte du tableau de bord : un intitulé discret, une valeur en avant."""

    def __init__(self, title: str, value: str = "", color: str = theme.ACCENT) -> None:
        super().__init__(padding=(18, 16, 18, 16), spacing=4)
        self.setMinimumHeight(84)
        self._title = label(title, "muted")
        self._value = label(value, "statValue")
        self._value.setWordWrap(True)
        self.set_color(color)
        self.body().addWidget(self._title)
        self.body().addWidget(self._value)
        self.body().addStretch(1)

    def set_value(self, value: str, color: str | None = None) -> None:
        self._value.setText(value)
        if color:
            self.set_color(color)

    def set_color(self, color: str) -> None:
        self._value.setStyleSheet(f"color: {color};")


class Badge(QLabel):
    """Pastille colorée affichant le canal cible d'un jeu."""

    def __init__(self, text: str, active: bool = True) -> None:
        super().__init__(text)
        self.set_active(active)
        self.setAlignment(Qt.AlignCenter)

    def set_active(self, active: bool) -> None:
        fg = theme.ACCENT if active else theme.TEXT_MUTED
        bg = theme.ACCENT_SOFT if active else theme.BG_CARD_ALT
        self.setStyleSheet(
            f"color: {fg}; background-color: {bg};"
            f"border-radius: {theme.RADIUS_BADGE}px;"
            f"padding: 5px 12px; font-size: {theme.SIZE_SMALL}px; font-weight: 700;"
        )


class StatusDot(QLabel):
    """Point de couleur indiquant l'état de la surveillance."""

    def __init__(self, color: str = theme.SUCCESS) -> None:
        super().__init__()
        self.setFixedSize(10, 10)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"background-color: {color}; border-radius: 5px;")


class PageHeader(QWidget):
    """En-tête de page : titre, sous-titre, et zone d'actions à droite."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(title, "h1"))
        if subtitle:
            texts.addWidget(label(subtitle, "body"))
        row.addLayout(texts)
        row.addStretch(1)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
        row.addLayout(self._actions)

    def add_action(self, widget: QWidget) -> None:
        # Un bouton d'en-tête ne doit jamais être rétréci par le layout :
        # sans cela, son libellé se retrouve tronqué quand le titre et le
        # sous-titre occupent déjà une large part de la ligne.
        widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._actions.addWidget(widget)


class ElidedLabel(QLabel):
    """
    Étiquette qui coupe son texte avec des points de suspension.

    Qt ne le fait pas de lui-même sur un QLabel : sans cela, un titre comme
    « Icarus-3.0.21.155391-Shipping-DangerousHorizons » imposerait sa largeur
    à toute la carte qui le contient.
    """

    def __init__(self, text: str = "", role: str = "body") -> None:
        super().__init__()
        self.setProperty("role", role)
        self._full_text = text
        self.setMinimumWidth(24)
        self._refresh()

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(
            metrics.elidedText(self._full_text, Qt.ElideRight, max(24, self.width()))
        )


class GameCard(QFrame):
    """
    Fiche d'un jeu surveillé : icône, nom, processus, canal cible et actions.

    Présentée en grille plutôt qu'en liste pleine largeur : une ligne étirée
    sur toute la fenêtre laisse un large vide entre le nom et le canal, et
    donne une page sans rythme dès que plusieurs jeux sont configurés.
    """

    def __init__(
        self,
        title: str,
        process_name: str,
        channel: str,
        pixmap: QPixmap,
        enabled: bool,
        running: bool,
        on_edit: Callable[[], None],
        on_remove: Callable[[], None],
    ) -> None:
        super().__init__()
        self.setProperty("role", "gameCard")
        self.setProperty("running", "yes" if running else "no")
        self.setMinimumWidth(300)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)

        # --- Haut : icône et identité ---
        top = QHBoxLayout()
        top.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(pixmap)
        icon.setFixedSize(pixmap.width(), pixmap.height())
        icon.setAlignment(Qt.AlignCenter)
        top.addWidget(icon, 0, Qt.AlignTop)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        name = ElidedLabel(title, "small")
        name.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY if enabled else theme.TEXT_MUTED};"
            f"font-weight: 700; font-size: {theme.SIZE_BODY}px;"
        )
        name.set_full_text(title)
        texts.addWidget(name)
        process = ElidedLabel(process_name, "muted")
        process.set_full_text(process_name)
        texts.addWidget(process)
        top.addLayout(texts, 1)
        outer.addLayout(top)

        # --- Bas : canal, état, actions ---
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(Badge(channel or "aucun canal", enabled))

        if running:
            state = label("● en cours", "small")
            state.setStyleSheet(f"color: {theme.SUCCESS}; font-size: {theme.SIZE_SMALL}px;")
            bottom.addWidget(state)
        elif not enabled:
            state = label("suspendu", "muted")
            bottom.addWidget(state)

        bottom.addStretch(1)
        bottom.addWidget(icon_button("pencil", "iconAction", "Modifier", on_edit))
        bottom.addWidget(icon_button("cross", "iconDanger", "Retirer", on_remove))
        outer.addLayout(bottom)


class NavButton(QPushButton):
    """Entrée de la navigation latérale, à l'état actif persistant."""

    def __init__(self, text: str, on_click: Callable[[], None]) -> None:
        super().__init__(text)
        self.setProperty("role", "nav")
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.clicked.connect(lambda: on_click())


# ----------------------------------------------------------------------
# Icônes
# ----------------------------------------------------------------------
def pil_to_pixmap(image: Image.Image) -> QPixmap:
    """Convertit une image PIL (icône extraite d'un .exe) en QPixmap."""
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, QImage.Format_RGBA8888)
    # copy() détache le QImage du tampon Python, qui serait sinon libéré.
    return QPixmap.fromImage(qimage.copy())


def letter_icon(text: str, size: int = 32) -> QPixmap:
    """
    Icône de secours : initiale du jeu sur une pastille aux couleurs de
    l'application, dessinée avec antialiasing.
    """
    scale = 3  # rendu suréchantillonné puis réduit, pour des bords nets
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size * scale, size * scale, 8 * scale, 8 * scale)
    painter.fillPath(path, QColor(theme.ACCENT))

    painter.setPen(QColor("#FFFFFF"))
    font = QFont(theme.FONT_FAMILY, int(size * scale * 0.45))
    font.setBold(True)
    painter.setFont(font)
    letter = (text.strip()[:1] or "?").upper()
    painter.drawText(pixmap.rect(), Qt.AlignCenter, letter)
    painter.end()

    return pixmap.scaled(
        size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )


def app_icon(size: int = 64) -> QIcon:
    """Icône de l'application et de la barre système : onde stylisée."""
    scale = 4
    full = size * scale
    pixmap = QPixmap(full, full)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(theme.ACCENT))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2 * scale, 2 * scale, full - 4 * scale, full - 4 * scale)

    painter.setBrush(QColor("#FFFFFF"))
    # Trois barres façon égaliseur audio, pour évoquer le routage audio
    for x0, y0, x1, y1 in ((18, 34, 26, 46), (30, 20, 38, 46), (42, 28, 50, 46)):
        painter.drawRoundedRect(
            x0 * scale, y0 * scale, (x1 - x0) * scale, (y1 - y0) * scale,
            2 * scale, 2 * scale,
        )
    painter.end()

    return QIcon(pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
