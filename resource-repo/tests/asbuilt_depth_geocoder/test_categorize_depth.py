# resource-repo-work/tests/asbuilt_depth_geocoder/test_categorize_depth.py
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import categorize_depth, DEPTH_COLORS, DEPTH_CATEGORY_LABELS


def test_categorize_depth_quatre_classes():
    assert categorize_depth(None) == "manquante"
    assert categorize_depth(5.0) == "manquante"      # < 10
    assert categorize_depth(9.99) == "manquante"
    assert categorize_depth(10.0) == "rouge"          # >= 10, < 50
    assert categorize_depth(49.99) == "rouge"
    assert categorize_depth(50.0) == "orange"         # >= 50, < 55
    assert categorize_depth(54.99) == "orange"
    assert categorize_depth(55.0) == "vert"           # >= 55
    assert categorize_depth(200.0) == "vert"


def test_plus_de_classe_jaune():
    assert "jaune" not in DEPTH_COLORS
    assert "jaune" not in DEPTH_CATEGORY_LABELS
    assert set(DEPTH_COLORS) == {"manquante", "rouge", "orange", "vert"}
