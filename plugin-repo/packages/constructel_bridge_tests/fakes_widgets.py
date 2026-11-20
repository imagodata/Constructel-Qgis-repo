"""Doublures de widgets Qt partagees (accueil 2.0, plan 2026-11-18 tache 4).

Sorties de test_bridge19_home.py pour servir aussi aux tests de la page de
chargement : le rendu Qt reel (mise en page, couleurs, arbre a trois etats)
reste a la recette manuelle. Une doublure ne modelise que ce que le plugin
lit ; les setters non modelises (``set*``) sont sans effet.

Fideles a Qt sur ce que le plugin utilise :
  * ``_Item.setCheckState`` emet ``itemChanged`` de l'arbre quand l'etat change,
    sauf si l'arbre a ses signaux bloques (``blockSignals``), comme
    ``QTreeWidget`` ; les autres setters d'item n'emettent rien (le plugin les
    appelle toujours signaux bloques) ;
  * ``_Button.setChecked`` emet ``toggled`` quand l'etat change, jamais
    ``clicked`` (reserve a l'utilisateur : le test l'emet a la main).
"""
from __future__ import annotations

import types


class _Sig:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class _W:
    """QWidget factice : etat lisible ; les setters non modelises sont sans effet."""

    def __init__(self, *args, **kwargs):
        self.layout = None
        self.enabled = True
        self.hidden = False
        self.deleted = False
        self.tooltip = ""
        self.signals_blocked = False
        self.visible = True     # setVisible ; ``hidden`` ne suit que hide()
        self.destroyed = _Sig()  # QObject.destroyed (jamais emis par la doublure)

    def setVisible(self, visible):
        self.visible = bool(visible)

    def isVisible(self):
        return self.visible

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def isEnabled(self):
        return self.enabled

    def setToolTip(self, text):
        self.tooltip = text

    def toolTip(self):
        return self.tooltip

    def blockSignals(self, block):
        """Rend l'ancien etat, comme QObject.blockSignals."""
        previous = self.signals_blocked
        self.signals_blocked = bool(block)
        return previous

    def hide(self):
        self.hidden = True

    def show(self):
        self.hidden = False

    def deleteLater(self):
        self.deleted = True

    def parentWidget(self):
        """Parente non modelisee : la doublure rend None (toutes les
        doublures passent pour des enfants directs de la fenetre)."""
        return None

    def findChildren(self, cls):
        """Descendants de classe *cls* : widgets des layouts (sous-layouts
        compris) et pages d'un QStackedWidget, comme QObject.findChildren
        (recursif)."""
        found = []

        def walk(node):
            if isinstance(node, _Layout):
                for item in node.items:
                    walk(item)
                return
            if node is not self and isinstance(node, cls):
                found.append(node)
            if getattr(node, "layout", None) is not None:
                walk(node.layout)
            if isinstance(node, _Stack):
                for page in node.pages:
                    walk(page)

        walk(self)
        return found

    def palette(self):
        """Palette non modelisee : la feuille de style de l'accueil retombe
        alors sur les roles ``palette(...)`` de Qt."""
        return None

    def font(self):
        return _Font()

    def style(self):
        return _Style()

    def __getattr__(self, name):
        if name.startswith("set"):
            return lambda *a, **k: None
        raise AttributeError(name)


class _Font:
    """QFont : setters sans effet (majuscules et gras des titres)."""

    Capitalization = types.SimpleNamespace(AllUppercase=1)

    def __getattr__(self, name):
        if name.startswith("set"):
            return lambda *a, **k: None
        raise AttributeError(name)


class _Style:
    """QStyle : relecture du style (polish) sans effet."""

    def polish(self, _widget):
        pass

    def unpolish(self, _widget):
        pass


class _Label(_W):
    def __init__(self, text="", *args):
        super().__init__(*args)
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text


class _Button(_Label):
    def __init__(self, text="", *args):
        super().__init__(text, *args)
        self.clicked = _Sig()
        self.toggled = _Sig()
        self.checkable = False
        self.checked = False
        self.auto_default = True    # QPushButton dans un QDialog : autoDefault par defaut
        self.default = False

    def setAutoDefault(self, value):
        self.auto_default = bool(value)

    def autoDefault(self):
        return self.auto_default

    def setDefault(self, value):
        self.default = bool(value)

    def isDefault(self):
        return self.default

    def setCheckable(self, checkable):
        self.checkable = bool(checkable)

    def setChecked(self, checked):
        checked = bool(checked)
        changed = checked != self.checked
        self.checked = checked
        if changed and not self.signals_blocked:
            self.toggled.emit(checked)

    def isChecked(self):
        return self.checked


class _CheckBox(_Button):
    pass


class _ToolButton(_Button):
    """QToolButton : bouton (tuile) avec menu optionnel."""

    ToolButtonPopupMode = types.SimpleNamespace(InstantPopup=2)

    def __init__(self, text="", *args):
        super().__init__(text, *args)
        self.menu = None

    def setMenu(self, menu):
        self.menu = menu


class _Action:
    def __init__(self, text=""):
        self.text = text
        self.triggered = _Sig()


class _Menu(_W):
    """QMenu : actions ajoutees par texte, declenchables par le test."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.actions = []

    def addAction(self, text="", *_args):
        action = _Action(text)
        self.actions.append(action)
        return action

    def addSeparator(self):
        pass

    def clear(self):
        self.actions = []


class _LineEdit(_Label):
    def __init__(self, text="", *args):
        super().__init__(text, *args)
        self.textChanged = _Sig()

    def setText(self, text):
        changed = text != self._text
        self._text = text
        if changed and not self.signals_blocked:
            self.textChanged.emit(text)


class _GroupBox(_W):
    def __init__(self, title="", *args):
        super().__init__(*args)
        self.title = title


class _Dialog(_W):
    """QDialog : accept / reject passent par done(), comme Qt (une fenetre
    qui surcharge done() le voit pour toute fermeture)."""

    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.closed = False
        self.result = None
        self.minimum_size = None
        self.size = None
        self.title = ""

    def done(self, result):
        self.closed = True
        self.result = result

    def accept(self):
        self.done(1)

    def reject(self):
        self.done(0)

    def exec(self):
        """Boucle modale factice : rend tout de suite (le test joue les
        gestes avant ou apres)."""
        return self.result or 0

    def setWindowTitle(self, title):
        self.title = title

    def setMinimumSize(self, width, height):
        self.minimum_size = (width, height)

    def resize(self, width, height):
        self.size = (width, height)


class _Layout:
    def __init__(self, parent=None):
        self.items = []
        if parent is not None:
            parent.layout = self

    def addWidget(self, widget, *_args):
        self.items.append(widget)

    def addLayout(self, layout, *_args):
        self.items.append(layout)

    def replaceWidget(self, old, new, *_args):
        self.items[self.items.index(old)] = new

    def removeWidget(self, widget):
        self.items.remove(widget)

    def __getattr__(self, name):
        if name.startswith(("set", "add")):
            return lambda *a, **k: None
        raise AttributeError(name)


class _Stack(_W):
    """QStackedWidget : pages empilees, page courante par index."""

    def __init__(self, *args):
        super().__init__(*args)
        self.pages = []
        self.index = -1

    def addWidget(self, widget):
        self.pages.append(widget)
        if self.index < 0:
            self.index = 0
        return len(self.pages) - 1

    def removeWidget(self, widget):
        """Comme Qt : la page sort de la pile (indices decales), sans etre detruite."""
        current = self.currentWidget()
        self.pages.remove(widget)
        self.index = self.pages.index(current) if current in self.pages else (0 if self.pages else -1)

    def setCurrentIndex(self, index):
        self.index = index

    def currentIndex(self):
        return self.index

    def currentWidget(self):
        return self.pages[self.index] if 0 <= self.index < len(self.pages) else None


class _ListWidget(_W):
    """QListWidget : lignes de texte, ligne courante."""

    def __init__(self, *args):
        super().__init__(*args)
        self.rows = []
        self.row = -1
        self.currentRowChanged = _Sig()

    def addItem(self, text):
        self.rows.append(text)

    def item(self, _row):
        """QListWidgetItem : icone, couleur et infobulle sans effet."""
        return _W()

    def clear(self):
        self.rows = []
        self.row = -1

    def count(self):
        return len(self.rows)

    def setCurrentRow(self, row):
        if row != self.row:
            self.row = row
            if not self.signals_blocked:
                self.currentRowChanged.emit(row)

    def currentRow(self):
        return self.row


def _widgets(root):
    """Widgets du sous-arbre de *root* (layouts parcourus), dans l'ordre."""
    found = []

    def walk(node):
        if isinstance(node, _Layout):
            for item in node.items:
                walk(item)
            return
        found.append(node)
        if getattr(node, "layout", None) is not None:
            walk(node.layout)

    walk(root)
    return found


def _texts(root):
    return [w.text() for w in _widgets(root) if isinstance(w, _Label)]


class _Tree(_W):
    def __init__(self, *args):
        super().__init__(*args)
        self.children = []
        self.itemChanged = _Sig()

    def clear(self):
        self.children = []


class _Item:
    # Comme QTreeWidgetItem sous PyQt : non hachable (pas de cle de dict ni d'element de set).
    __hash__ = None

    def __eq__(self, other):
        return self is other

    def __init__(self, parent, texts):
        self._text = texts[0]
        self.children = []
        self.parent = parent
        self.tree = parent if isinstance(parent, _Tree) else parent.tree
        self.flag_bits = 0
        self.state = None
        self.disabled = False
        self.value = None
        self.tip = ""
        self.expanded = False
        parent.children.append(self)

    def flags(self):
        return self.flag_bits

    def setFlags(self, flags):
        self.flag_bits = flags

    def setCheckState(self, _column, state):
        changed = state != self.state
        self.state = state
        if changed and not self.tree.signals_blocked:
            self.tree.itemChanged.emit(self, 0)

    def checkState(self, _column):
        return self.state

    def setToolTip(self, _column, text):
        self.tip = text

    def toolTip(self, _column):
        return self.tip

    def setDisabled(self, disabled):
        self.disabled = bool(disabled)

    def isDisabled(self):
        return self.disabled

    def setData(self, _column, _role, value):
        self.value = value

    def data(self, _column, _role):
        return self.value

    def setExpanded(self, expanded):
        self.expanded = bool(expanded)

    def isExpanded(self):
        return self.expanded

    def setText(self, _column, text):
        self._text = text

    def text(self, _column):
        return self._text

    def childCount(self):
        return len(self.children)

    def child(self, index):
        return self.children[index]


class _Combo(_W):
    def __init__(self, *args):
        super().__init__(*args)
        self.entries = []
        self.index = -1
        self.currentIndexChanged = _Sig()

    def addItem(self, text, data=None):
        self.entries.append((text, data))
        if self.index < 0:
            self.index = 0

    def setCurrentIndex(self, index):
        if index != self.index:
            self.index = index
            self.currentIndexChanged.emit(index)

    def currentData(self):
        return self.entries[self.index][1]


_ITEM_FLAG = types.SimpleNamespace(ItemIsUserCheckable=0x10, ItemIsAutoTristate=0x40)
_CHECK = types.SimpleNamespace(Unchecked=0, PartiallyChecked=1, Checked=2)
_ROLE = types.SimpleNamespace(UserRole=0x100)


# --- Bridge 2.1 : selecteur de personnes (autocompletion) -------------------------------------


class _Timer:
    """QTimer d'instance : ``start`` arme, le test emet ``timeout`` a la main ;
    ``singleShot`` (statique) appelle tout de suite."""

    def __init__(self, *_args):
        self.timeout = _Sig()
        self.active = False
        self.interval = 0
        self.starts = 0

    def setSingleShot(self, _single):
        pass

    def setInterval(self, msec):
        self.interval = msec

    def start(self, *_args):
        self.active = True
        self.starts += 1

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active

    @staticmethod
    def singleShot(_msec, callback):
        callback()


class _StringModel:
    def __init__(self, *_args):
        self.strings = []

    def setStringList(self, strings):
        self.strings = list(strings)

    def stringList(self):
        return list(self.strings)


class _Completer:
    class CompletionMode:
        UnfilteredPopupCompletion = 2

    def __init__(self, model=None, *_args):
        self.model = model
        self.activated = _Sig()
        self.popups = 0
        self.mode = None

    def setCompletionMode(self, mode):
        self.mode = mode

    def complete(self, *_args):
        self.popups += 1

    def __getattr__(self, name):
        if name.startswith("set"):
            return lambda *a, **k: None
        raise AttributeError(name)


class _Edit(_LineEdit):
    """QLineEdit avec ``textEdited`` (frappe) et ``clear``."""

    def __init__(self, text="", *args):
        super().__init__(text, *args)
        self.textEdited = _Sig()
        self.placeholder = ""

    def clear(self):
        self.setText("")

    def setPlaceholderText(self, text):
        self.placeholder = text

    def type(self, text):
        """Frappe de l'utilisateur : texte puis textEdited."""
        self.setText(text)
        self.textEdited.emit(text)


class _ItemTree(_Tree):
    """QTreeWidget avec widgets de cellule (setItemWidget / itemWidget)."""

    def __init__(self, *args):
        super().__init__(*args)
        self.cell_widgets = {}

    def clear(self):
        super().clear()
        self.cell_widgets = {}

    def setItemWidget(self, item, column, widget):
        self.cell_widgets[(id(item), column)] = widget

    def itemWidget(self, item, column):
        return self.cell_widgets.get((id(item), column))
