"""Styles QML OSIRIS embarques (secours quand public.layer_styles n'a rien).

Lecture statique, sans QGIS ni base. Le rendu reel est controle dans un vrai
QGIS (banc PyQGIS du depot Farois, 19/11/2026). Ces garde-fous figent :
  - aucune etiquette sur les couches OSIRIS (decision Simon du 19/11/2026) ;
  - les zones gelees ne lisent que start_date / end_date : « statut_gel »
    n'existe que dans la vue, la table osiris.frozen_zones ne l'a pas (le style
    embarque filtrait dessus : rien n'etait dessine) ;
  - les classes de fin de gel, identiques au QML de Farois (styles/).
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

STYLES = Path(__file__).resolve().parents[1] / "constructel_bridge" / "styles"
OSIRIS_QML = sorted(STYLES.glob("osiris_*.qml"))


def test_osiris_style_files_present():
    assert len(OSIRIS_QML) == 9


@pytest.mark.parametrize("qml", OSIRIS_QML, ids=lambda p: p.name)
def test_osiris_style_has_no_labels(qml):
    root = ET.parse(qml).getroot()
    assert root.get("labelsEnabled") == "0"
    assert root.find("labeling") is None


def test_frozen_zones_style_reads_only_dates():
    root = ET.parse(STYLES / "osiris_frozen_zones.qml").getroot()
    filters = [r.get("filter") for r in root.iter("rule") if r.get("filter")]
    assert filters and all("start_date" in f or "end_date" in f for f in filters)
    assert not any("statut_gel" in f or "jours_restants" in f for f in filters)


def test_frozen_zones_style_classes():
    root = ET.parse(STYLES / "osiris_frozen_zones.qml").getroot()
    rules = {r.get("label"): r for r in root.iter("rule") if r.get("symbol") is not None}
    assert list(rules) == [
        "Gel à venir (pas encore commencé)",
        "Fin du gel dans moins de 3 mois",
        "Fin du gel dans 3 à 12 mois",
        "Fin du gel dans 1 à 2 ans",
        "Fin du gel dans plus de 2 ans",
        "Fin du gel inconnue",
        "Gel expiré (masqué par défaut)",
    ]
    unchecked = [lab for lab, r in rules.items() if r.get("checkstate") == "0"]
    assert unchecked == ["Gel expiré (masqué par défaut)"]
    symbols = {s.get("name") for s in root.find("renderer-v2").find("symbols")}
    assert {r.get("symbol") for r in rules.values()} <= symbols
