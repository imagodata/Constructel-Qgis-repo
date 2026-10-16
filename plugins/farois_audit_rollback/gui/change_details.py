"""Formatage des valeurs avant/après d'un changement (logique pure) et dialogue de détail.

La partie pure ne dépend ni de QGIS ni de Qt ; les imports Qt du dialogue sont
paresseux pour que ce module reste importable (et testable) sans interface.
"""

import json

NONE_TEXT = "∅"
GEOMETRY_TEXT = "géométrie"
GEOMETRY_CHANGED_TEXT = "géométrie modifiée"
VALUE_LIMIT = 40
CELL_LIMIT = 200
GEOMETRY_KEYS = {"geom"}
TECHNICAL_COLUMNS = {"id", "created_at", "updated_at"}
ARROW = " → "


def _as_dict(values):
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except ValueError:
            return {}
    return values if isinstance(values, dict) else {}


def _is_geometry(key, value):
    if key in GEOMETRY_KEYS:
        return True
    return isinstance(value, str) and value.lstrip().startswith(("SRID=", '{"type":'))


def _text(value):
    if value is None:
        return NONE_TEXT
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _short(text, limit):
    return text if len(text) <= limit else text[:limit] + "…"


def _is_update(entry):
    return entry.operation not in ("INSERT", "DELETE")


def _update_fields(entry, before, after):
    columns = list(entry.changed_columns or ())
    if not columns:
        columns = sorted(
            key for key in before.keys() | after.keys() if before.get(key) != after.get(key)
        )
    return columns


def _all_keys(before, after):
    return list(before) + [key for key in after if key not in before]


def columns_label(entry):
    """Texte de la colonne « Colonnes » (changed_columns reste inchangé)."""
    if entry.changed_columns:
        return ", ".join(entry.changed_columns)
    return {"INSERT": "création", "DELETE": "suppression"}.get(entry.operation, "")


def _side(key, value, update, present):
    if not present:
        return NONE_TEXT
    if _is_geometry(key, value):
        return GEOMETRY_CHANGED_TEXT if update else GEOMETRY_TEXT
    return _text(value)


def change_rows(entry, all_fields=False):
    """Lignes (champ, avant, après) du dialogue de détail, valeurs complètes."""
    before, after = _as_dict(entry.before), _as_dict(entry.after)
    update = _is_update(entry)
    if update and not all_fields:
        keys = _update_fields(entry, before, after)
    elif all_fields:
        keys = _all_keys(before, after) or _update_fields(entry, before, after)
    else:
        source = after if entry.operation == "INSERT" else before
        keys = [key for key, value in source.items() if value is not None]
    rows = []
    for key in keys:
        old, new = before.get(key), after.get(key)
        if not update:
            # Un INSERT n'a pas d'avant, un DELETE pas d'après.
            old = old if entry.operation == "DELETE" else None
            new = new if entry.operation == "INSERT" else None
        rows.append(
            (
                key,
                _side(key, old, update, old is not None),
                _side(key, new, update, new is not None),
            )
        )
    return rows


def _summary_lines(entry, limit):
    before, after = _as_dict(entry.before), _as_dict(entry.after)
    lines = []
    if _is_update(entry):
        for key in _update_fields(entry, before, after):
            old, new = before.get(key), after.get(key)
            if _is_geometry(key, old) or _is_geometry(key, new):
                lines.append(f"{key} : {GEOMETRY_CHANGED_TEXT}")
                continue
            old_text, new_text = _text(old), _text(new)
            if limit:
                old_text, new_text = _short(old_text, limit), _short(new_text, limit)
            lines.append(f"{key} : {old_text}{ARROW}{new_text}")
        return lines
    source = after if entry.operation == "INSERT" else before
    for key, value in source.items():
        if value is None or key in TECHNICAL_COLUMNS or _is_geometry(key, value):
            continue
        text = _text(value)
        lines.append(f"{key} : {_short(text, limit) if limit else text}")
    return lines


def summary_text(entry, full=False):
    """Texte de la colonne « Avant → après ».

    Cellule : valeurs tronquées à 40 caractères, texte à 200 ; ``full=True`` donne
    le texte non tronqué, un champ par ligne (infobulle).
    """
    if full:
        return "\n".join(_summary_lines(entry, 0))
    text = " ; ".join(line.replace("\n", " ") for line in _summary_lines(entry, VALUE_LIMIT))
    return _short(text, CELL_LIMIT)


def build_dialog(entry, parent=None):
    """Construit le dialogue Champ | Avant | Après (Qt importé à l'appel)."""
    try:
        from qgis.PyQt.QtWidgets import (
            QCheckBox,
            QDialog,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
        )
        from qgis.PyQt.QtCore import Qt
    except ImportError:  # pragma: no cover - hors QGIS
        from PyQt5.QtWidgets import (
            QCheckBox,
            QDialog,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
        )
        from PyQt5.QtCore import Qt

    dialog = QDialog(parent)
    dialog.setWindowTitle("Farois — Détail du changement")
    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel(
            f"{entry.operation} — {entry.table_name} — {entry.label} "
            f"(par {entry.username})"
        )
    )
    table = QTableWidget(0, 3)
    table.setHorizontalHeaderLabels(["Champ", "Avant", "Après"])
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.horizontalHeader().setStretchLastSection(True)
    layout.addWidget(table)
    show_all = QCheckBox("Afficher tous les champs")
    layout.addWidget(show_all)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    close = QPushButton("Fermer")
    close.clicked.connect(dialog.accept)
    buttons.addWidget(close)
    layout.addLayout(buttons)

    def fill(*_args):
        rows = change_rows(entry, all_fields=show_all.isChecked())
        table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setToolTip(value)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()

    show_all.toggled.connect(fill)
    fill()
    dialog.table, dialog.show_all, dialog.close_button = table, show_all, close
    dialog.resize(640, 420)
    return dialog


def show_change_details(entry, parent=None):
    dialog = build_dialog(entry, parent)
    dialog.exec_()
    return dialog
