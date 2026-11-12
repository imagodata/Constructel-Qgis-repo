"""Garde Python 3.9 (QGIS 3.28) : une annotation `X | Y` n'est evaluable
qu'a partir de 3.10 ; sans `from __future__ import annotations` elle leve
TypeError a l'import. On l'interdit donc dans tout module du paquet qui ne
porte pas l'import differe (plan 2026-11-12, tache 1, decision K10)."""
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "constructel_bridge"


def _has_future_annotations(tree):
    return any(
        isinstance(n, ast.ImportFrom) and n.module == "__future__"
        and any(a.name == "annotations" for a in n.names)
        for n in tree.body
    )


def _annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for a in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
                if a is not None and a.annotation is not None:
                    yield a.annotation
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def _has_bitor(annotation):
    return any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(annotation))


def test_pep604_annotations_need_future_import():
    offenders = {}
    for path in sorted(list(PKG.glob("*.py")) + list(PKG.glob("i18n/*.py"))):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _has_future_annotations(tree):
            continue
        lines = sorted({a.lineno for a in _annotations(tree) if _has_bitor(a)})
        if lines:
            offenders[str(path.relative_to(PKG))] = lines
    assert offenders == {}


def test_planned_modules_carry_the_future_import():
    # D16 : modules du plan deja touches ; les nouveaux modules s'ajoutent ici.
    for name in ("bridge_plugin.py", "bridge_project_init.py", "bridge_sketcher.py", "bridge_operators.py"):
        tree = ast.parse((PKG / name).read_text(encoding="utf-8"))
        assert _has_future_annotations(tree), name
