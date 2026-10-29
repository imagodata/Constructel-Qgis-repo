"""Minimal stand-in for qgis.PyQt.QtWidgets under plain pytest.

Widgets record state (text, read-only, enabled) and the few signals the
plugin connects (textChanged, toggled, clicked, accepted/rejected) call
their slots synchronously, so dialog LOGIC can be asserted without a Qt
event loop. Layout and painting are no-ops.
"""


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self, slot=None):
        if slot is None:
            self._slots = []
        elif slot in self._slots:
            self._slots.remove(slot)
        else:
            raise TypeError("not connected")

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _Widget:
    def __init__(self, *_args, **_kwargs):
        self._enabled = True
        self._tooltip = ""
        self._visible = True

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def isEnabled(self):
        return self._enabled

    def setToolTip(self, text):
        self._tooltip = text

    def toolTip(self):
        return self._tooltip

    def setFocus(self, *_args):
        pass

    def setFixedWidth(self, *_args):
        pass

    def setMinimumWidth(self, *_args):
        pass

    def setAlignment(self, *_args):
        pass

    def setVisible(self, visible):
        self._visible = bool(visible)

    def isVisible(self):
        return self._visible

    def setWordWrap(self, *_args):
        pass

    def setStyleSheet(self, *_args):
        pass


class QAction(_Widget):
    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.triggered = _Signal()
        self._text = _args[1] if len(_args) > 1 else ""

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text

    def setIcon(self, *_args):
        pass


class QDialog(_Widget):
    class DialogCode:
        Accepted = 1
        Rejected = 0

    Accepted = DialogCode.Accepted
    Rejected = DialogCode.Rejected

    def __init__(self, parent=None):
        super().__init__()
        self._title = ""
        self.result_code = None

    def setWindowTitle(self, title):
        self._title = title

    def windowTitle(self):
        return self._title

    def accept(self):
        self.result_code = self.Accepted

    def reject(self):
        self.result_code = self.Rejected

    def exec(self):
        return self.result_code if self.result_code is not None else self.Rejected


class QInputDialog:
    pass


class QMenu(_Widget):
    def addAction(self, *_args):
        pass

    def addSeparator(self):
        pass


class QMessageBox:
    @staticmethod
    def critical(*_args, **_kwargs):
        pass

    @staticmethod
    def warning(*_args, **_kwargs):
        pass

    @staticmethod
    def information(*_args, **_kwargs):
        pass


class QToolButton(_Widget):
    class ToolButtonPopupMode:
        MenuButtonPopup = 1

    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.clicked = _Signal()

    def setIcon(self, *_args):
        pass

    def setMenu(self, *_args):
        pass

    def setPopupMode(self, *_args):
        pass


class QLabel(_Widget):
    def __init__(self, text="", *_args, **_kwargs):
        super().__init__()
        self._text = text

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text


class QLineEdit(_Widget):
    class EchoMode:
        Normal = 0
        Password = 2

    def __init__(self, text="", *_args, **_kwargs):
        super().__init__()
        self._text = text
        self._read_only = False
        self._echo = self.EchoMode.Normal
        self._placeholder = ""
        self.textChanged = _Signal()

    def setText(self, text):
        self._text = text
        self.textChanged.emit(text)

    def text(self):
        return self._text

    def setReadOnly(self, read_only):
        self._read_only = bool(read_only)

    def isReadOnly(self):
        return self._read_only

    def setEchoMode(self, mode):
        self._echo = mode

    def echoMode(self):
        return self._echo

    def setPlaceholderText(self, text):
        self._placeholder = text

    def placeholderText(self):
        return self._placeholder


class QSpinBox(_Widget):
    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self._value = 0
        self._read_only = False

    def setRange(self, *_args):
        pass

    def setValue(self, value):
        self._value = value

    def value(self):
        return self._value

    def setReadOnly(self, read_only):
        self._read_only = bool(read_only)


class QCheckBox(_Widget):
    def __init__(self, text="", *_args, **_kwargs):
        super().__init__()
        self._checked = False
        self.toggled = _Signal()

    def setChecked(self, checked):
        self._checked = bool(checked)
        self.toggled.emit(self._checked)

    def isChecked(self):
        return self._checked


class QPushButton(_Widget):
    def __init__(self, text="", *_args, **_kwargs):
        super().__init__()
        self._text = text
        self._checkable = False
        self._checked = False
        self.toggled = _Signal()
        self.clicked = _Signal()

    def setCheckable(self, checkable):
        self._checkable = bool(checkable)

    def setChecked(self, checked):
        self._checked = bool(checked)
        self.toggled.emit(self._checked)

    def isChecked(self):
        return self._checked


class QDialogButtonBox(_Widget):
    class StandardButton:
        Ok = 1
        Cancel = 2

    Ok = StandardButton.Ok
    Cancel = StandardButton.Cancel

    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.accepted = _Signal()
        self.rejected = _Signal()
        self._buttons = {self.StandardButton.Ok: QPushButton("OK"), self.StandardButton.Cancel: QPushButton("Cancel")}

    def button(self, which):
        return self._buttons.get(which)


class _Layout:
    def __init__(self, *_args, **_kwargs):
        self.items = []

    def addWidget(self, widget, *_args):
        self.items.append(widget)

    def addLayout(self, layout, *_args):
        self.items.append(layout)

    def addRow(self, *args):
        self.items.append(args)


class QFormLayout(_Layout):
    pass


class QHBoxLayout(_Layout):
    pass


class QVBoxLayout(_Layout):
    pass
