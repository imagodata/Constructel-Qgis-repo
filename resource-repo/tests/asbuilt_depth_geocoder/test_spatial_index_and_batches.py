"""Optimisations : index par bbox (resultats identiques), SQL par lots, fusion Overpass."""
import math
import random
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    OsmWay, OverpassRequest, WaySpatialIndex, _locate_by_fuzzy_name, _ways_touch,
    batch_locate_sql, bbox_distance, connected_component, diagnose_unlocated,
    first_rows_by_tag, index_ways_by_name, merge_overpass_requests, nearest_way,
    normalize_street_name, polyline_bbox, project_on_polyline,
)


def _random_ways(seed, n=400):
    rnd = random.Random(seed)
    ways = []
    for wid in range(1, n + 1):
        x, y = rnd.uniform(0, 3000), rnd.uniform(0, 3000)
        coords = [(x, y)]
        for _ in range(rnd.randint(1, 4)):
            x += rnd.uniform(-80, 80)
            y += rnd.uniform(-80, 80)
            coords.append((x, y))
        name = f"rue {rnd.randint(0, 60)}" if rnd.random() < 0.85 else None
        hw = rnd.choice(["residential", "residential", "tertiary", "service", "track", "footway"])
        ways.append(OsmWay(wid, (normalize_street_name(name),) if name else (), hw, coords))
    return ways


def test_candidats_sur_ensemble_exact_et_ordre_d_origine():
    ways = _random_ways(1)
    index = WaySpatialIndex(ways, cell=150.0)
    rnd = random.Random(2)
    for _ in range(200):
        px, py, r = rnd.uniform(-100, 3100), rnd.uniform(-100, 3100), rnd.uniform(1, 400)
        got = index.candidates(px, py, r)
        truth = [w for w in ways if project_on_polyline(px, py, w.coords)[0] <= r]
        assert set(w.way_id for w in truth) <= set(w.way_id for w in got)
        assert [w.way_id for w in got] == sorted(w.way_id for w in got)  # ordre d'origine
        assert all(bbox_distance(px, py, polyline_bbox(w.coords)) <= r for w in got)


def test_equivalence_nearest_way_fuzzy_et_diagnostic_avec_ou_sans_index():
    for seed in range(3, 8):
        ways = _random_ways(seed)
        index = WaySpatialIndex(ways)
        by_name = index_ways_by_name([w for w in ways if w.names])
        rnd = random.Random(seed * 10)
        for _ in range(120):
            px, py = rnd.uniform(0, 3000), rnd.uniform(0, 3000)
            names = (f"rue {rnd.randint(0, 70)}",)
            pref = tuple(normalize_street_name(n) for n in names)
            assert repr(nearest_way(px, py, ways, preferred_names=pref)) == \
                repr(nearest_way(px, py, ways, preferred_names=pref, spatial=index))
            assert repr(_locate_by_fuzzy_name(px, py, names, ways, by_name, {})) == \
                repr(_locate_by_fuzzy_name(px, py, names, ways, by_name, {}, index))
            assert diagnose_unlocated(px, py, names, ways) == \
                diagnose_unlocated(px, py, names, ways, spatial=index)


def _naive_component(seed, candidates, tol, max_ways=500):
    pool = sorted(candidates, key=lambda w: w.way_id)
    component, seen, queue = [seed], {seed.way_id}, [seed]
    while queue and len(component) < max_ways:
        current = queue.pop(0)
        for way in pool:
            if way.way_id in seen or not _ways_touch(current, way, tol):
                continue
            seen.add(way.way_id)
            component.append(way)
            queue.append(way)
            if len(component) >= max_ways:
                break
    return sorted(component, key=lambda w: w.way_id)


def test_composante_connexe_identique_a_la_version_naive():
    for seed in range(8, 13):
        ways = [w for w in _random_ways(seed, 300) if w.names]
        by_name = index_ways_by_name(ways)
        for name, group in by_name.items():
            for tol in (1.0, 12.0, 60.0):
                assert [w.way_id for w in connected_component(group[0], group, tol)] == \
                    [w.way_id for w in _naive_component(group[0], group, tol)]


# --- SQL par lots -----------------------------------------------------------------

def test_requete_par_lot():
    sql = batch_locate_sql([(0, 1.5, 2.5, "'Rue X'"), (7, 3.0, 4.0, "'l''Église'")], 150.0)
    assert "CROSS JOIN LATERAL public.fn_asbuilt_locate_on_road(" in sql
    assert "(0, 1.5::double precision, 2.5::double precision, 'Rue X'::text)" in sql
    assert "'l''Église'::text" in sql and "WITH ORDINALITY" in sql
    assert "150.0" in sql and sql.endswith("ORDER BY v.tag, l.ord")


def test_premiere_ligne_par_tag_comme_l_appel_unitaire():
    rows = [["0", "k1", 1], [0, "k2", 2], [3, "k3", 3]]
    assert first_rows_by_tag(rows) == {0: ("k1", 1), 3: ("k3", 3)}
    assert first_rows_by_tag([]) == {}


# --- fusion des requetes Overpass ----------------------------------------------------

def _req(box, names, ids):
    return OverpassRequest(bbox=box, names=tuple(names), ids=tuple(ids))


def test_fusion_des_emprises_voisines():
    a = _req((0, 0, 1000, 1000), ["Rue A"], ["1"])
    b = _req((1200, 0, 2000, 1000), ["Rue B"], ["2"])        # a 200 m
    c = _req((5000, 0, 5500, 500), ["Rue C"], ["3"])         # loin
    merged = merge_overpass_requests([a, b, c])
    assert len(merged) == 2
    ab = next(r for r in merged if "1" in r.ids)
    assert ab.bbox == (0, 0, 2000, 1000) and ab.names == ("Rue A", "Rue B") and ab.ids == ("1", "2")


def test_pas_de_fusion_homonymes_ou_trop_grand_ou_trop_de_noms():
    a = _req((0, 0, 1000, 1000), ["Hauptstraße"], ["1"])
    b = _req((1100, 0, 2000, 1000), ["Hauptstrasse"], ["2"])  # meme nom normalise
    assert len(merge_overpass_requests([a, b])) == 2
    big = _req((0, 0, 2900, 2900), ["Rue A"], ["1"])
    near = _req((3000, 0, 3500, 500), ["Rue B"], ["2"])       # cote > 3 km
    assert len(merge_overpass_requests([big, near])) == 2
    many = _req((0, 0, 100, 100), [f"Rue {i}" for i in range(30)], ["1"])
    more = _req((150, 0, 250, 100), [f"Voie {i}" for i in range(15)], ["2"])
    assert len(merge_overpass_requests([many, more])) == 2     # 45 noms > 40
    coords = [_req((0, 0, 500, 500), [], ["1"]), _req((600, 0, 1000, 500), [], ["2"])]
    assert len(merge_overpass_requests(coords)) == 1           # requetes par coordonnees


def test_surface_bornee():
    a = _req((0, 0, 2900, 1000), ["Rue A"], ["1"])
    b = _req((0, 1200, 2900, 3000), ["Rue B"], ["2"])         # union 2,9 x 3 km = 8,7 km2 : OK
    assert len(merge_overpass_requests([a, b])) == 1
    c = _req((0, 0, 3000, 1000), ["Rue A"], ["1"])
    d = _req((0, 1100, 3000, 3100), ["Rue B"], ["2"])         # 3 x 3,1 km : trop
    assert len(merge_overpass_requests([c, d])) == 2
    assert math.isclose(2.9 * 3.0, 8.7)
