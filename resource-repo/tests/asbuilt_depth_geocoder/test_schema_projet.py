# resource-repo/tests/asbuilt_depth_geocoder/test_schema_projet.py
"""Schéma As-Built public / projet (migration Farois 574) — collection 1.4.0.

La 1.4.0 est publiée AVANT la migration : elle détecte le schéma au début de
chaque exécution (``to_regclass('projet.geofiber_asbuilt_depth_points')``),
garde en ``public`` le comportement de la 1.3.0 et, en ``projet``, écrit les
segments et connecteurs (tables en lecture seule) par les écrivains SECURITY
DEFINER de Farois (``sql/80_security/086``), jamais par DML direct.
"""
import ast
import json
import re
import struct
import sys
from pathlib import Path

import pytest

COLLECTION = Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder"
SCRIPT = COLLECTION / "processing/geocode_asbuilt_depth.py"
sys.path.insert(0, str(COLLECTION / "processing"))
import geocode_asbuilt_depth as mod  # noqa: E402
from geocode_asbuilt_depth import (  # noqa: E402
    AsbuiltSchema, AsbuiltSchemaError, Connector, SegmentHalf,
)

PUBLIC = AsbuiltSchema(mod.SCHEMA_MODE_PUBLIC)
PROJET = AsbuiltSchema(mod.SCHEMA_MODE_PROJET)

# Message réel de la garde Farois (086, écrivain des segments).
GUARD_ERROR = (
    "ERROR:  As-Built en lecture seule pour jdupont (INSERT sur "
    "geofiber_asbuilt_depth_segments) : scope PROJET GOFIBER en ecriture requis "
    "(Farois, onglet Perimetre)"
)
ALL_FUNCTIONS = [[sig] for sig in mod.PROJET_REQUIRED_FUNCTIONS]


class FakeFeedback:
    def __init__(self, cancel_after=None):
        self.infos, self.warnings, self.errors = [], [], []
        self.cancel_after = cancel_after
        self.checks = 0

    def pushInfo(self, text):  # noqa: N802
        self.infos.append(text)

    def pushWarning(self, text):  # noqa: N802
        self.warnings.append(text)

    def reportError(self, text, fatalError=False):  # noqa: N802,N803
        self.errors.append(text)

    def setProgress(self, value):  # noqa: N802
        pass

    def isCanceled(self):  # noqa: N802
        self.checks += 1
        return self.cancel_after is not None and self.checks > self.cancel_after


class FakeDb:
    """``execute`` de la connexion 'be' : réponses par motif, appels enregistrés."""

    def __init__(self, answers=None, fail=None):
        self.calls = []
        self.answers = answers or []   # (motif, réponse | Exception)
        self.fail = fail               # sql -> Exception ou None

    def __call__(self, sql):
        self.calls.append(sql)
        if self.fail is not None:
            exc = self.fail(sql)
            if exc is not None:
                raise exc
        for pattern, answer in self.answers:
            if pattern in sql:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return [[1]]


def _projet_db(functions=ALL_FUNCTIONS, allowed=True):
    return FakeDb([
        ("to_regclass", [[True]]),
        ("oidvectortypes", functions),
        ("geofiber_asbuilt_write_allowed()", allowed if isinstance(allowed, Exception)
         else [[allowed]]),
    ])


def _payload(sql):
    """Tableau JSON passé à un écrivain (chaîne dollar-quoted)."""
    match = re.search(r"\((\$[a-z0-9]+\$)(.*)\1::jsonb\)$", sql, re.S)
    assert match, sql
    return json.loads(match.group(2))


def _decode_ewkb(hexstr):
    """EWKB hexadécimal -> (type, srid, parties) — LineString / MultiLineString."""
    data = bytes.fromhex(hexstr)
    order, wkb_type, srid = struct.unpack_from("<BII", data, 0)
    assert order == 1 and wkb_type & 0x20000000
    base, offset = wkb_type & 0xFF, 9

    def line(off):
        (n,) = struct.unpack_from("<I", data, off)
        off += 4
        pts = [struct.unpack_from("<dd", data, off + 16 * i) for i in range(n)]
        return pts, off + 16 * n

    if base == 2:
        pts, offset = line(offset)
        assert offset == len(data)
        return "LineString", srid, [pts]
    assert base == 5
    (nparts,) = struct.unpack_from("<I", data, offset)
    offset += 4
    parts = []
    for _ in range(nparts):
        sub_order, sub_type = struct.unpack_from("<BI", data, offset)
        assert sub_order == 1 and sub_type == 2  # sous-géométries sans SRID
        pts, offset = line(offset + 5)
        parts.append(pts)
    assert offset == len(data)
    return "MultiLineString", srid, parts


def _half(a, b, half="a", side="R", category="vert", length=12.5):
    return SegmentHalf(a, b, half, category, False, length, "osm:1",
                       0.0, 0.0, 10.0, 0.0, side=side)


def _geometries(*halves):
    return {mod.segment_key(h): (((150000.0, 170000.0), (150010.0, 170000.0)),)
            for h in halves}


# --- noms qualifiés -----------------------------------------------------------

def test_noms_qualifies_mode_public_identiques_a_la_130():
    assert PUBLIC.schema == "public"
    assert not PUBLIC.uses_writers
    assert PUBLIC.points == "public.geofiber_asbuilt_depth_points"
    assert PUBLIC.segments == "public.geofiber_asbuilt_depth_segments"
    assert PUBLIC.ungeocoded == "public.geofiber_asbuilt_ungeocoded"
    assert PUBLIC.connectors == "public.geofiber_asbuilt_depth_connectors"
    assert PUBLIC.function("fn_asbuilt_locate_on_road") == "public.fn_asbuilt_locate_on_road"


def test_noms_qualifies_mode_projet():
    assert PROJET.schema == "projet"
    assert PROJET.uses_writers
    assert PROJET.points == "projet.geofiber_asbuilt_depth_points"
    assert PROJET.segments == "projet.geofiber_asbuilt_depth_segments"
    assert PROJET.ungeocoded == "projet.geofiber_asbuilt_ungeocoded"
    assert PROJET.connectors == "projet.geofiber_asbuilt_depth_connectors"
    assert PROJET.function("fn_asbuilt_road_geometry") == "projet.fn_asbuilt_road_geometry"


def test_mode_inconnu_refuse():
    with pytest.raises(ValueError):
        AsbuiltSchema("wyre")


def test_requetes_de_lecture_suivent_le_schema():
    items = [(0, 1.5, 2.5, "'Rue X'")]
    assert "LATERAL public.fn_asbuilt_locate_on_road(" in mod.batch_locate_sql(items, 150.0)
    assert "LATERAL projet.fn_asbuilt_locate_on_road(" in mod.batch_locate_sql(
        items, 150.0, PROJET.schema)
    assert "LATERAL projet.fn_asbuilt_road_geometry(" in mod.batch_road_geometry_sql(
        items, 150.0, PROJET.schema)
    assert mod.store_osm_ways_sql([{"osm_id": 1}]).startswith(
        "SELECT public.fn_asbuilt_store_osm_ways($osmw$")
    assert mod.store_osm_ways_sql([{"osm_id": 1}], PROJET.schema).startswith(
        "SELECT projet.fn_asbuilt_store_osm_ways($osmw$")


def test_journal_du_mode_retenu():
    assert "public" in PUBLIC.describe() and "1.3.0" in PUBLIC.describe()
    text = PROJET.describe()
    assert "projet" in text and "574" in text
    assert "projet.fn_asbuilt_segments_upsert" in text
    assert "projet.fn_asbuilt_connectors_upsert" in text


# --- détection du schéma ------------------------------------------------------

def test_detection_mode_public_une_seule_requete():
    db = FakeDb([("to_regclass", [[False]])])
    names = mod.detect_asbuilt_schema(db)
    assert names == PUBLIC
    assert db.calls == [mod.SCHEMA_PROBE_SQL]
    assert "to_regclass('projet.geofiber_asbuilt_depth_points')" in mod.SCHEMA_PROBE_SQL


def test_detection_mode_public_si_resultat_vide_ou_null():
    assert mod.detect_asbuilt_schema(FakeDb([("to_regclass", [])])) == PUBLIC
    assert mod.detect_asbuilt_schema(FakeDb([("to_regclass", [[None]])])) == PUBLIC


def test_detection_mode_projet():
    db = _projet_db()
    names = mod.detect_asbuilt_schema(db)
    assert names == PROJET
    assert len(db.calls) == 3
    assert "pg_catalog.pg_proc" in db.calls[1]  # catalogue seul, aucun droit requis
    assert db.calls[2] == "SELECT projet.geofiber_asbuilt_write_allowed()"


def test_detection_projet_valeur_texte():
    db = _projet_db()
    db.answers[0] = ("to_regclass", [["t"]])
    db.answers[2] = ("geofiber_asbuilt_write_allowed()", [["true"]])
    assert mod.detect_asbuilt_schema(db) == PROJET


def test_detection_impossible_arrete():
    db = FakeDb([("to_regclass", RuntimeError("server closed the connection"))])
    with pytest.raises(AsbuiltSchemaError, match="Détection du schéma As-Built impossible"):
        mod.detect_asbuilt_schema(db)


def test_base_a_moitie_migree_arret_explicite():
    present = [[sig] for sig in mod.PROJET_REQUIRED_FUNCTIONS
               if not sig.startswith("fn_asbuilt_connectors")]
    db = _projet_db(functions=present)
    with pytest.raises(AsbuiltSchemaError) as info:
        mod.detect_asbuilt_schema(db)
    message = str(info.value)
    assert "moitié migrée" in message
    assert "projet.fn_asbuilt_connectors_upsert(jsonb)" in message
    assert "projet.fn_asbuilt_connectors_delete(text[])" in message
    assert "jamais directement" in message
    # Arrêt AVANT le pré-contrôle d'écriture : aucune autre requête.
    assert len(db.calls) == 2


def test_fonctions_manquantes_signatures_exactes():
    rows = [["fn_asbuilt_segments_upsert(jsonb)"], ["fn_asbuilt_segments_delete(text)"],
            ["fn_asbuilt_connectors_upsert(jsonb)"], ["fn_asbuilt_connectors_delete(text[])"],
            ["geofiber_asbuilt_write_allowed()"]]
    # Mauvaise signature = absente (surcharge inattendue).
    assert mod.missing_projet_functions(rows) == ["fn_asbuilt_segments_delete(jsonb)"]
    assert mod.missing_projet_functions(ALL_FUNCTIONS) == []
    assert mod.missing_projet_functions(None) == list(mod.PROJET_REQUIRED_FUNCTIONS)


def test_precontrole_ecriture_refusee_arrete_avant_geocodage():
    with pytest.raises(AsbuiltSchemaError) as info:
        mod.detect_asbuilt_schema(_projet_db(allowed=False))
    assert "scope PROJET GOFIBER" in str(info.value)


def test_precontrole_sans_droit_sur_le_schema():
    db = _projet_db(allowed=RuntimeError("ERROR: permission denied for schema projet"))
    with pytest.raises(AsbuiltSchemaError) as info:
        mod.detect_asbuilt_schema(db)
    assert "scope PROJET GOFIBER" in str(info.value)
    assert "permission denied for schema projet" in str(info.value)


def test_precontrole_non_concluant_avertit_et_continue():
    warnings = []
    db = _projet_db(allowed=RuntimeError("canceling statement due to statement timeout"))
    assert mod.detect_asbuilt_schema(db, warnings.append) == PROJET
    assert warnings and "non vérifiable" in warnings[0]


# --- refus 42501 ----------------------------------------------------------------

def test_refus_reconnu():
    assert mod.is_write_denied(GUARD_ERROR)
    assert mod.is_write_denied("SQLSTATE 42501")
    assert mod.is_write_denied("ERROR: permission denied for table geofiber_asbuilt_depth_points")
    assert mod.is_write_denied("ERREUR: droit refusé pour la table geofiber_asbuilt_ungeocoded")
    assert not mod.is_write_denied("duplicate key value violates unique constraint")
    assert not mod.is_write_denied("")
    assert not mod.is_write_denied(None)


def test_message_de_refus_clair():
    message = mod.write_denied_message(GUARD_ERROR)
    for expected in ("Écriture refusée", "login nominatif", "scope PROJET GOFIBER",
                     "en écriture", "Périmètre", "administrateur Farois",
                     "DESIGNER", "compte technique partagé", "Relancez"):
        assert expected in message, expected
    assert "jdupont" in message  # détail de la base repris, sur une ligne
    assert "\n" not in message
    assert "Détail" not in mod.write_denied_message()


def test_precontrole_reserve_au_mode_projet():
    with pytest.raises(ValueError):
        mod.write_allowed_sql(PUBLIC)


# --- écrivains : forme du jsonb ---------------------------------------------------

def test_ewkb_linestring_srid_31370():
    hexstr = mod.ewkb_hex_linestring([(0, 0), (1, 1)])
    # Référence PostGIS : ST_AsEWKB('SRID=31370;LINESTRING(0 0,1 1)')
    assert hexstr.startswith("01020000208A7A000002000000")
    assert _decode_ewkb(hexstr) == ("LineString", 31370, [[(0.0, 0.0), (1.0, 1.0)]])


def test_ewkb_multilinestring_srid_31370():
    parts = [[(1.0, 2.0), (3.0, 4.0)], [(5.0, 6.0), (7.0, 8.0), (9.0, 10.0)]]
    kind, srid, decoded = _decode_ewkb(mod.ewkb_hex_multilinestring(parts))
    assert (kind, srid, decoded) == ("MultiLineString", 31370, parts)


def test_ligne_segment_colonnes_exactes():
    half = _half("100", "200", side="L")
    parts = (((150000.0, 170000.0), (150010.0, 170000.0)), ((150010.0, 170000.0), (150020.0, 170001.0)))
    row = mod.segment_writer_row(half, parts, multi_column=True)
    assert set(row) == {
        "point_a_intervention_id", "point_b_intervention_id", "half", "side",
        "depth_category", "is_long", "length_m", "road_key", "geom",
    }
    assert "created_at" not in row and "updated_at" not in row
    assert row["side"] == "L"
    kind, srid, decoded = _decode_ewkb(row["geom"])
    assert kind == "MultiLineString" and srid == 31370 and len(decoded) == 2
    line = mod.segment_writer_row(half, parts[:1], multi_column=False)
    assert _decode_ewkb(line["geom"])[0] == "LineString"


def test_ligne_segment_longueur_non_finie():
    row = mod.segment_writer_row(_half("1", "2", length=float("nan")),
                                 (((0.0, 0.0), (1.0, 0.0)),))
    assert row["length_m"] is None
    json.dumps(row, allow_nan=False)


def test_ligne_connecteur():
    connector = Connector("100", "rouge", "R", "osm:1", 4.2, 1.0, 2.0, 3.0, 4.0)
    row = mod.connector_writer_row(connector)
    assert set(row) == {"intervention_id", "depth_category", "side", "road_key",
                        "length_m", "geom"}
    assert _decode_ewkb(row["geom"]) == ("LineString", 31370, [[(1.0, 2.0), (3.0, 4.0)]])


def test_dedoublonnage_par_cle_primaire_derniere_gagne():
    rows = [
        {"point_a_intervention_id": "1", "point_b_intervention_id": "2", "half": "a",
         "side": "R", "depth_category": "vert"},
        {"point_a_intervention_id": "1", "point_b_intervention_id": "2", "half": "a",
         "side": "L", "depth_category": "vert"},
        {"point_a_intervention_id": "1", "point_b_intervention_id": "2", "half": "a",
         "side": "R", "depth_category": "rouge"},
    ]
    kept, n_dupes = mod.dedupe_by_key(rows, mod.SEGMENT_PK_COLUMNS)
    assert n_dupes == 1
    assert [(r["side"], r["depth_category"]) for r in kept] == [("R", "rouge"), ("L", "vert")]


def test_cle_de_suppression_porte_toujours_le_cote():
    assert mod.segment_delete_key(("1", "2", "b", "L")) == {
        "point_a_intervention_id": "1", "point_b_intervention_id": "2",
        "half": "b", "side": "L",
    }
    for bad in (None, "", "X"):
        with pytest.raises(ValueError):
            mod.segment_delete_key(("1", "2", "a", bad))


def test_ecrivains_refuses_en_mode_public():
    for build in (mod.segments_upsert_sql, mod.segments_delete_sql,
                  mod.connectors_upsert_sql, mod.connectors_delete_sql):
        with pytest.raises(ValueError, match="mode projet"):
            build(PUBLIC, [])


def test_suppression_connecteurs_tableau_texte():
    sql = mod.connectors_delete_sql(PROJET, ["100", "l'200"])
    assert sql == ("SELECT projet.fn_asbuilt_connectors_delete("
                   "ARRAY['100', 'l''200']::text[])")


# --- écrivains : appels en mode projet ----------------------------------------------

def test_segments_via_ecrivains_seulement():
    h_new = _half("100", "200", side="R")
    h_upd = _half("100", "200", side="L")
    h_dup = _half("100", "200", side="R", category="rouge")
    db = FakeDb()
    fb = FakeFeedback()
    out = mod.write_segments_with_writers(
        db, PROJET, [(h_new, False), (h_upd, True), (h_dup, False)],
        [("300", "__ROAD_END__", "a", "L")], _geometries(h_new, h_upd), True, fb,
    )
    assert len(db.calls) == 2
    upsert, delete = db.calls
    assert upsert.startswith("SELECT projet.fn_asbuilt_segments_upsert($seg$")
    assert delete.startswith("SELECT projet.fn_asbuilt_segments_delete($segk$")
    rows = _payload(upsert)
    # Dédoublonné par (point_a, point_b, half, side) ; côtés L et R distincts.
    assert [(r["side"], r["depth_category"]) for r in rows] == [("R", "rouge"), ("L", "vert")]
    assert all(_decode_ewkb(r["geom"])[1] == 31370 for r in rows)
    assert _payload(delete) == [{"point_a_intervention_id": "300",
                                 "point_b_intervention_id": "__ROAD_END__",
                                 "half": "a", "side": "L"}]
    assert (out.inserted, out.updated, out.failed, out.deleted, out.failed_delete) == (1, 1, 0, 1, 0)
    assert fb.warnings and "en double" in fb.warnings[0]


def test_aucun_dml_direct_sur_segments_et_connecteurs():
    halves = [_half(str(100 + i), str(200 + i)) for i in range(5)]
    db = FakeDb()
    mod.write_segments_with_writers(
        db, PROJET, [(h, False) for h in halves], [("1", "2", "a", "R")],
        _geometries(*halves), True, FakeFeedback(),
    )
    connector = Connector("100", "vert", "R", "osm:1", 4.0, 0.0, 0.0, 1.0, 1.0)
    mod.write_connectors_with_writers(db, PROJET, [(connector, False)], ["101"], FakeFeedback())
    dml = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE|COPY)\b", re.I)
    for sql in db.calls:
        assert re.match(r"SELECT projet\.fn_asbuilt_(segments|connectors)_(upsert|delete)\(", sql), sql
        head = re.sub(r"\$[a-z0-9]+\$.*\$[a-z0-9]+\$", "", sql, flags=re.S)
        assert not dml.search(head), sql


def test_lots_et_reprise_ligne_a_ligne():
    halves = [_half(str(1000 + i), str(2000 + i)) for i in range(5)]
    bad = "1003"

    def fail(sql):
        if "fn_asbuilt_segments_upsert" in sql and f'"{bad}"' in sql:
            return RuntimeError("new row violates check constraint")
        return None

    db = FakeDb(fail=fail)
    fb = FakeFeedback()
    out = mod.write_segments_with_writers(
        db, PROJET, [(h, False) for h in halves], [], _geometries(*halves), True, fb,
        batch_size=2,
    )
    # Lots [1000,1001] ok, [1002,1003] échoue -> rejoué ligne à ligne, [1004] ok.
    assert out.inserted == 4 and out.failed == 1
    assert len(fb.errors) == 1 and bad in fb.errors[0]
    assert sum(1 for sql in db.calls if "segments_upsert" in sql) == 5


def test_refus_arrete_les_ecritures_et_la_purge():
    halves = [_half(str(1000 + i), str(2000 + i)) for i in range(3)]
    db = FakeDb(fail=lambda sql: RuntimeError(GUARD_ERROR))
    out = mod.write_segments_with_writers(
        db, PROJET, [(h, False) for h in halves], [("1", "2", "a", "R")],
        _geometries(*halves), True, FakeFeedback(), batch_size=2,
    )
    assert out.denied and "scope PROJET GOFIBER" in out.denied
    assert out.failed == 3 and out.inserted == 0
    assert len(db.calls) == 1  # ni lot suivant, ni reprise ligne à ligne, ni purge
    assert not any("segments_delete" in sql for sql in db.calls)


def test_cote_invalide_jamais_envoye_sans_side():
    db = FakeDb()
    fb = FakeFeedback()
    out = mod.write_segments_with_writers(
        db, PROJET, [], [("1", "2", "a", None), ("3", "4", "b", "R")], {}, True, fb,
    )
    assert out.failed_delete == 1 and out.deleted == 1
    (sql,) = db.calls
    assert _payload(sql) == [{"point_a_intervention_id": "3", "point_b_intervention_id": "4",
                              "half": "b", "side": "R"}]


def test_annulation_entre_deux_lots():
    halves = [_half(str(1000 + i), str(2000 + i)) for i in range(4)]
    db = FakeDb()
    out = mod.write_segments_with_writers(
        db, PROJET, [(h, False) for h in halves], [], _geometries(*halves), True,
        FakeFeedback(cancel_after=1), batch_size=2,
    )
    assert out.inserted == 2 and len(db.calls) == 1


def test_connecteurs_via_ecrivains():
    c1 = Connector("100", "vert", "R", "osm:1", 4.0, 0.0, 0.0, 1.0, 1.0)
    c2 = Connector("101", "rouge", "L", "osm:1", 3.0, 0.0, 0.0, 1.0, 1.0)
    db = FakeDb()
    out = mod.write_connectors_with_writers(
        db, PROJET, [(c1, False), (c2, True), (c1, False)], ["102", "102"], FakeFeedback(),
    )
    upsert, delete = db.calls
    assert [r["intervention_id"] for r in _payload(upsert)] == ["100", "101"]
    assert delete == "SELECT projet.fn_asbuilt_connectors_delete(ARRAY['102']::text[])"
    assert (out.inserted, out.updated, out.deleted, out.failed) == (1, 1, 1, 0)


def test_connecteurs_refus():
    c1 = Connector("100", "vert", "R", "osm:1", 4.0, 0.0, 0.0, 1.0, 1.0)
    db = FakeDb(fail=lambda sql: RuntimeError(GUARD_ERROR))
    out = mod.write_connectors_with_writers(db, PROJET, [(c1, False)], ["102"], FakeFeedback())
    assert out.denied and out.failed == 1 and len(db.calls) == 1


# --- garde statique du script ---------------------------------------------------------

def _source():
    return SCRIPT.read_text(encoding="utf-8")


def _is_uses_writers_test(node):
    return (isinstance(node, ast.Attribute) and node.attr == "uses_writers"
            and isinstance(node.value, ast.Attribute) and node.value.attr == "_names")


def _direct_edit_calls_outside_public_branch(func):
    """Appels d'édition de couche hors de la branche ``else`` (mode public)."""
    edit_methods = {"startEditing", "addFeature", "changeAttributeValues",
                    "changeGeometry", "deleteFeatures", "commitChanges"}
    offending = []

    def visit(node, in_public_branch):
        if isinstance(node, ast.If) and _is_uses_writers_test(node.test):
            for child in node.body:
                visit(child, False)
            for child in node.orelse:
                visit(child, True)
            return
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in edit_methods and not in_public_branch):
            offending.append((node.lineno, node.func.attr))
        for child in ast.iter_child_nodes(node):
            visit(child, in_public_branch)

    visit(func, False)
    return offending


def test_segments_et_connecteurs_edition_directe_uniquement_en_mode_public():
    tree = ast.parse(_source())
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("_sync_segments", "_sync_connectors"):
        assert name in funcs
        assert _direct_edit_calls_outside_public_branch(funcs[name]) == [], name
        # La branche projet existe bien (écrivains appelés).
        body = ast.get_source_segment(_source(), funcs[name])
        assert "with_writers(" in body


def test_aucun_schema_en_dur_dans_le_code():
    code = "\n".join(
        line for line in _source().splitlines() if not line.lstrip().startswith("#")
    )
    # Aucun nom qualifié en dur : tout passe par AsbuiltSchema.
    assert not re.search(r"\b(public|projet)\.(geofiber_asbuilt_|fn_asbuilt_)", code)
    assert "nspname = 'public'" not in code
    # Aucun SQL de DML direct sur segments / connecteurs dans le script.
    assert not re.search(
        r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+[^\s;]*(depth_segments|depth_connectors)\b",
        code, re.I,
    )
    # Plus de constantes de schéma dispersées.
    assert "TABLE_SCHEMA = " not in code


def test_aide_sans_schema_en_dur():
    match = re.search(r"def shortHelpString\(self\):(.*?)\n        def ", _source(), re.S)
    assert match
    help_text = match.group(1)
    assert "public.geofiber" not in help_text and "projet.geofiber" not in help_text
    assert "public.fn_asbuilt" not in help_text and "projet.fn_asbuilt" not in help_text
    assert "SCHÉMA" in help_text and "PROJET GOFIBER" in help_text
