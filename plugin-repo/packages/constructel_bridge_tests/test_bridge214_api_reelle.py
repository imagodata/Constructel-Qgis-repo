"""Bridge 2.1.4 : deux appels qui passaient sur les doublures et cassaient
sur le vrai QGIS / le vrai PostgreSQL (journal de prod du 24/11).

1. ``QgsVectorLayer.isReadOnly()`` n'existe pas (QGIS 3.28 -> 4.x) : la
   methode est ``readOnly()``. L'AttributeError interrompait la boucle des
   styles par defaut des la premiere couche (« Style loading error »).
2. ``pg_catalog.unnest(a, b, c)`` : PostgreSQL ne developpe l'unnest a
   plusieurs tableaux que pour le nom NON qualifie ; qualifie, la fonction
   n'existe pas et les sources de repli du catalogue tombaient en erreur.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from constructel_bridge import bridge_operators as bo

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"


def test_plugin_never_calls_isReadOnly_on_a_layer():
    """Les couches QGIS exposent readOnly(), jamais isReadOnly() (QLineEdit
    seul l'a). Garde au niveau source : les doublures ne le verront pas."""
    offenders = []
    for path in sorted(PLUGIN_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\blayer\w*\.isReadOnly\(", line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == []


def test_catalog_query_unnests_one_array_per_call():
    """Chaque unnest qualifie ne recoit qu'un tableau ; les trois colonnes
    sont alignees par ROWS FROM."""
    q = bo.CATALOG_SOURCES_QUERY
    calls = re.findall(r"unnest\(([^()]*)\)", q)
    assert len(calls) == 3
    assert all(c.count("%s") == 1 for c in calls), calls
    assert "ROWS FROM" in q


@pytest.mark.skipif(not os.environ.get("BRIDGE_TEST_PG_DSN"),
                    reason="BRIDGE_TEST_PG_DSN non defini (PostgreSQL reel)")
def test_catalog_query_runs_on_a_real_postgresql():
    psycopg2 = pytest.importorskip("psycopg2")
    conn = psycopg2.connect(os.environ["BRIDGE_TEST_PG_DSN"])
    try:
        cur = conn.cursor()
        cur.execute(bo.CATALOG_SOURCES_QUERY, bo.catalog_sources_params())
        rows = cur.fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == ["osiris_frozen"]
    assert all(isinstance(r[1], bool) and isinstance(r[2], bool) for r in rows)
