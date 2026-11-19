# -*- coding: utf-8 -*-
"""
Constructel Bridge - mise en forme de la fenetre d'accueil 2.0 (2.0.2).

Une feuille de style Qt (QSS) posee sur la seule fenetre d'accueil
(``HomeDialog``, objectName ``bridgeHome``) ; chaque regle vise un widget du
Bridge par son objectName ou sa propriete ``bridgeRole``, jamais un type nu :
rien ne deborde sur QGIS ni sur un dialogue heberge (assistant du Check-in,
menu des presets, saisie d'un nom).

Aucune couleur codee en dur : tout vient de la palette de QGIS (theme clair
ou sombre, surbrillance bleue ou verte). Les teintes intermediaires (fond
d'une tuile cochee, bordure discrete, texte attenue) sont des melanges de
deux couleurs de cette palette ; sans palette lisible (doublures de test),
les roles ``palette(...)`` de Qt les remplacent.

Roles (propriete dynamique ``bridgeRole``) :
  panel       cadre d'une etape ou d'une section (QFrame)
  badge       pastille ronde du numero d'etape
  stepTitle   titre d'etape ou de section (majuscules par la police)
  tile        tuile de preset (QToolButton), etat fin par ``tileState``
  toggle      bouton de perimetre (operateur) ; ``neutral`` pour « Aucun »
  primary     bouton principal (« Charger »)
  link        bouton texte (Mes presets, tout, rien)
  disclosure  ligne repliable « ▸ Options »
  seg         bouton de langue (FR · EN · PT)
  chip        pastille d'operateur
  muted       texte secondaire
"""

from __future__ import annotations

ROLE = "bridgeRole"
TILE_STATE = "tileState"


def set_role(widget, role: str) -> None:
    widget.setProperty(ROLE, role)


def set_state(widget, name: str, value: str) -> None:
    """Change une propriete lue par la feuille de style et fait relire le
    style au widget (Qt ne le fait pas seul pour une propriete dynamique)."""
    widget.setProperty(name, value)
    style = getattr(widget, "style", None)
    if callable(style):
        current = style()
        if current is not None:
            current.unpolish(widget)
            current.polish(widget)


def uppercase(label) -> None:
    """Majuscules a l'affichage seulement (le texte reste la traduction)."""
    font = label.font()
    font.setCapitalization(font.Capitalization.AllUppercase)
    font.setBold(True)
    label.setFont(font)


# -- couleurs derivees de la palette ------------------------------------------------------

def _rgb(color) -> tuple:
    return color.red(), color.green(), color.blue()


def _mix(first: tuple, second: tuple, ratio: float) -> tuple:
    return tuple(round(a + (b - a) * ratio) for a, b in zip(first, second))


def _css(rgb: tuple) -> str:
    return "rgb({}, {}, {})".format(*rgb)


def _lightness(rgb: tuple) -> float:
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def palette_colors(palette) -> dict:
    """Couleurs nommees de la feuille de style, tirees de *palette* (QPalette),
    ou roles ``palette(...)`` si *palette* est illisible."""
    fallback = {
        "highlight": "palette(highlight)", "on_highlight": "palette(highlighted-text)",
        "base": "palette(base)", "window": "palette(window)", "text": "palette(text)",
        "tint": "palette(alternate-base)", "tint_soft": "palette(alternate-base)",
        "tint_hover": "palette(alternate-base)", "border": "palette(mid)", "border_strong": "palette(dark)",
        "muted": "palette(mid)", "neutral": "palette(dark)", "on_neutral": "palette(window)",
        "link": "palette(highlight)", "highlight_hover": "palette(highlight)",
        "highlight_pressed": "palette(dark)", "disabled_bg": "palette(button)", "panel": "palette(base)",
    }
    try:
        roles = palette.ColorRole
        get = palette.color
        highlight = _rgb(get(roles.Highlight))
        on_highlight = _rgb(get(roles.HighlightedText))
        base = _rgb(get(roles.Base))
        window = _rgb(get(roles.Window))
        text = _rgb(get(roles.WindowText))
    except Exception:  # noqa: BLE001 -- pas de QPalette (doublures) : roles Qt
        return fallback
    dark = _lightness(window) < 0.5
    white, black = (255, 255, 255), (0, 0, 0)
    return {
        "highlight": _css(highlight),
        "on_highlight": _css(on_highlight),
        "base": _css(base),
        "window": _css(window),
        "text": _css(text),
        "panel": _css(_mix(base, window, 0.25) if dark else base),
        "tint": _css(_mix(base, highlight, 0.30 if dark else 0.16)),
        "tint_soft": _css(_mix(base, highlight, 0.12 if dark else 0.06)),
        "tint_hover": _css(_mix(base, highlight, 0.18 if dark else 0.09)),
        "border": _css(_mix(window, text, 0.20)),
        "border_strong": _css(_mix(window, text, 0.38)),
        "muted": _css(_mix(text, window, 0.42)),
        "neutral": _css(_mix(window, text, 0.55)),
        "on_neutral": _css(window),
        "link": _css(_mix(highlight, white, 0.40) if dark else _mix(highlight, black, 0.10)),
        "highlight_hover": _css(_mix(highlight, white, 0.12)),
        "highlight_pressed": _css(_mix(highlight, black, 0.15)),
        "disabled_bg": _css(_mix(window, text, 0.15)),
    }


_TEMPLATE = """
QFrame#bridgeSide {{
    background: {panel}; border: 1px solid {border}; border-radius: 6px;
}}
QListWidget#bridgeNav {{ background: transparent; border: none; outline: 0; }}
QListWidget#bridgeNav::item {{
    padding: 7px 6px; margin: 1px 0px; border: none; border-left: 3px solid transparent;
    border-radius: 0px;
}}
QListWidget#bridgeNav::item:hover {{ background: {tint_hover}; }}
QListWidget#bridgeNav::item:selected {{
    background: {tint}; color: {text}; border-left: 3px solid {highlight};
}}

QFrame[bridgeRole="panel"] {{
    background: {panel}; border: 1px solid {border}; border-radius: 6px;
}}

QLabel[bridgeRole="badge"] {{
    background: {highlight}; color: {on_highlight}; border-radius: 9px;
    min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px;
    font-weight: bold; qproperty-alignment: AlignCenter;
}}
QLabel[bridgeRole="muted"], QCheckBox[bridgeRole="muted"] {{ color: {muted}; }}
QLabel[bridgeRole="chip"] {{
    border: 1px solid {border_strong}; border-radius: 7px; padding: 0px 6px; color: {text};
}}

QToolButton[bridgeRole="tile"] {{
    background: {base}; color: {text}; border: 1px solid {border}; border-radius: 5px;
    padding: 6px 4px; min-height: 40px;
}}
QToolButton[bridgeRole="tile"]:hover {{ border-color: {highlight}; }}
QToolButton[bridgeRole="tile"]:checked {{
    background: {tint}; border: 1px solid {highlight}; font-weight: bold;
}}
QToolButton[bridgeRole="tile"][tileState="partial"] {{
    background: {tint_soft}; border: 1px dashed {highlight};
}}
QToolButton[bridgeRole="tile"]:disabled {{
    background: transparent; color: {muted}; border: 1px dotted {border};
}}

QPushButton[bridgeRole="toggle"], QPushButton[bridgeRole="neutral"], QPushButton[bridgeRole="seg"] {{
    background: transparent; color: {text}; border: 1px solid {border_strong}; border-radius: 4px;
    padding: 4px 12px; min-width: 0px;
}}
QPushButton[bridgeRole="seg"] {{ padding: 1px 7px; }}
QPushButton[bridgeRole="toggle"]:hover, QPushButton[bridgeRole="neutral"]:hover,
QPushButton[bridgeRole="seg"]:hover {{ border-color: {highlight}; }}
QPushButton[bridgeRole="toggle"]:checked, QPushButton[bridgeRole="seg"]:checked {{
    background: {highlight}; color: {on_highlight}; border-color: {highlight}; font-weight: bold;
}}
QPushButton[bridgeRole="neutral"]:checked {{
    background: {neutral}; color: {on_neutral}; border-color: {neutral}; font-weight: bold;
}}
QPushButton[bridgeRole="toggle"]:disabled, QPushButton[bridgeRole="neutral"]:disabled,
QPushButton[bridgeRole="seg"]:disabled {{ color: {muted}; border-color: {border}; }}

QPushButton[bridgeRole="primary"] {{
    background: {highlight}; color: {on_highlight}; border: 1px solid {highlight}; border-radius: 4px;
    font-weight: bold; padding: 6px 30px; min-width: 110px;
}}
QPushButton[bridgeRole="primary"]:hover {{ background: {highlight_hover}; }}
QPushButton[bridgeRole="primary"]:pressed {{ background: {highlight_pressed}; }}
QPushButton[bridgeRole="primary"]:disabled {{
    background: {disabled_bg}; color: {muted}; border-color: {border};
}}

QToolButton[bridgeRole="link"], QPushButton[bridgeRole="link"] {{
    background: transparent; border: none; color: {link}; padding: 0px 2px; min-width: 0px;
}}
QToolButton[bridgeRole="link"]:hover, QPushButton[bridgeRole="link"]:hover {{ text-decoration: underline; }}
QToolButton[bridgeRole="link"]:disabled, QPushButton[bridgeRole="link"]:disabled {{ color: {muted}; }}
QToolButton[bridgeRole="link"]::menu-indicator {{ image: none; width: 0px; }}

QPushButton[bridgeRole="disclosure"] {{
    background: transparent; border: none; border-top: 1px solid {border}; color: {text};
    padding: 5px 2px; text-align: left; min-width: 0px;
}}
QPushButton[bridgeRole="disclosure"]:hover {{ color: {link}; }}
QPushButton[bridgeRole="disclosure"]:disabled {{ color: {muted}; }}

QTreeWidget#bridgeLayers {{ background: {panel}; border: none; }}
"""


def home_style_sheet(palette) -> str:
    """Feuille de style de la fenetre d'accueil pour *palette* (QPalette de
    la fenetre ; None ou illisible : roles ``palette(...)``)."""
    return _TEMPLATE.format(**palette_colors(palette))
