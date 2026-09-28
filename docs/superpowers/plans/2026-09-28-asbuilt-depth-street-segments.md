# Segments d'axe de rue par profondeur As-Built — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Étendre le script Processing QGIS `geocode_asbuilt_depth` (dépôt `qgis_repo`) et la base `farois_ftth` (dépôt `Farois`) pour générer, à chaque run, des segments d'axe de rue colorés (moitié/moitié) entre points de profondeur As-Built consécutifs, simplifier la catégorisation à 3 classes fixes, persister les non-géocodés, et synchroniser les styles en base.

**Architecture:** Une migration Farois (432) ajoute 2 tables (`public.geofiber_asbuilt_ungeocoded`, `public.geofiber_asbuilt_depth_segments`) et une fonction `SECURITY DEFINER` (`public.fn_asbuilt_locate_on_road`) qui accroche un point sur `ref.osm_roads` sans donner à `bureau_etudes` d'accès direct au schéma `ref`. Le script `geocode_asbuilt_depth.py` (une seule connexion DB, `be`) relit l'intégralité des points existants à chaque run, localise chacun sur son axe de rue, apparie les points adjacents (triés par abscisse curviligne) en segments à 2 moitiés colorées, et resynchronise (upsert + suppression des orphelins) la table segments.

**Tech Stack:** PostgreSQL/PostGIS (Farois), PyQGIS 3.28+ / QGIS Processing (script), pytest (fonctions pures des deux côtés).

**Spec:** `docs/superpowers/specs/2026-09-28-asbuilt-depth-street-segments-design.md` (dépôt `qgis_repo`)

## Global Constraints

- Toute nouvelle table/fonction reste dans le schéma `public` — `bureau_etudes` n'a et ne doit garder AUCUN accès direct à `ref`/`infra`/`osiris`/`chantier`/`audit`/`esb`/`staging` (invariant de sécurité, mig Farois 335).
- Une seule connexion DB dans le script : `be`. Pas de connexion `wyre`.
- Politique best-effort non bloquante partout côté script : jamais lever d'exception qui casse le run, toujours `feedback.pushWarning`/`pushInfo` et continuer.
- Le CSV non-géocodés existant (paramètre `UNGEOCODED`) reste inchangé — la table est un ajout, pas un remplacement.
- `saveStyleToDatabase(..., useAsDefault=True, ...)` pour la couche points ET la couche segments.
- Seuils fixes (plus de paramètre UI) : manquante `< 10 cm`, rouge `< 50 cm`, orange `< 55 cm`, vert `>= 55 cm`.
- Pointillé (`is_long`) si longueur segment `>= 100.0` mètres.
- PK `public.geofiber_asbuilt_depth_segments` = `(point_a_intervention_id, point_b_intervention_id, half)` ; segments de bout de route via sentinels `__ROAD_START__` / `__ROAD_END__` (jamais NULL — colonne PK).
- Resynchro complète à CHAQUE run : recalcul sur l'état COMPLET de `public.geofiber_asbuilt_depth_points` (pas seulement le lot du run), puis upsert + suppression des lignes orphelines de `geofiber_asbuilt_depth_segments`.

## Review Focus

- Adresse sans numéro de rue extractible (`address_raw` vide, garbage, ou déjà sans numéro) — `extract_street_name` ne doit jamais lever, doit se replier proprement (Task 7).
- Deux points géocodés à la position exacte identique sur le même axe — segment de longueur 0 : ne doit ni planter la géométrie ni être marqué `is_long` (Task 6).
- Groupe `road_key` à un seul point (aucun voisin) — doit produire 2 segments de bout de route (vers chaque extrémité), pas une exception d'index (Task 6).
- Ré-exécution du script sans nouvelle donnée — la resynchro doit être idempotente (mêmes clés, pas d'accumulation de doublons) (Task 8).
- Échec de connexion/permission sur `fn_asbuilt_locate_on_road` (ex. `GRANT EXECUTE` manquant) — ne doit PAS déclencher la suppression de tous les segments existants (la resynchro orpheline ne doit purger que sur un recalcul réellement abouti) (Task 8).

---

## Task 1: Migration Farois 432 — tables + fonction de localisation + droits

**Files:**
- Create: `~/projects/Farois/sql/migrations/432_asbuilt_ungeocoded_and_street_segments.sql`
- Create: `~/projects/Farois/sql/migrations/432r_rollback_asbuilt_ungeocoded_and_street_segments.sql`
- Test: `~/projects/Farois/tests/unit/test_migration_432_static.py`

**Interfaces:**
- Produces (SQL, schéma `public`) :
  - `public.geofiber_asbuilt_ungeocoded(intervention_id TEXT PK, work_order, address_raw, postal_code, place, depth_raw, geocode_query, source_message TEXT, created_at/updated_at TIMESTAMPTZ)`
  - `public.geofiber_asbuilt_depth_segments(point_a_intervention_id TEXT, point_b_intervention_id TEXT, half TEXT CHECK IN ('a','b'), depth_category TEXT, is_long BOOLEAN, length_m DOUBLE PRECISION, road_key TEXT, geom GEOMETRY(LineString,31370), created_at/updated_at TIMESTAMPTZ, PK (point_a_intervention_id, point_b_intervention_id, half))`
  - `public.fn_asbuilt_locate_on_road(p_point geometry, p_street_name text, p_search_radius numeric DEFAULT 40.0) RETURNS TABLE(road_key text, position_m numeric, projected_point geometry, road_length_m numeric, road_start geometry, road_end geometry)` — `SECURITY DEFINER`, exécutable par `bureau_etudes` (`GRANT EXECUTE`), lit `ref.osm_roads` avec les droits de son propriétaire `ftth_admin`.

Cette tâche est autonome (pas de dépendance sur les tâches suivantes) et testable seule : une fois appliquée, `fn_asbuilt_locate_on_road` est appelable manuellement en psql.

- [ ] **Step 1: Écrire la migration**

```sql
-- ============================================================================
-- migrations/432_asbuilt_ungeocoded_and_street_segments.sql
-- ============================================================================
-- Date: 2026-09-28
-- Auteur: Simon (chantier 3 - segments d'axe de rue As-Built)
--
-- CONTEXTE (spec dans le depot qgis_repo :
--   docs/superpowers/specs/2026-09-28-asbuilt-depth-street-segments-design.md) :
--   Chantier 3 du script Processing geocode_asbuilt_depth. Ajoute :
--     1. public.geofiber_asbuilt_ungeocoded — adresses non geocodees (en plus
--        du CSV existant, pas un remplacement)
--     2. public.geofiber_asbuilt_depth_segments — segments d'axe de rue entre
--        points de profondeur consecutifs (2 moities par paire), colonnes
--        1:1 avec ce que le script produira (chantier 3, hors perimetre ici)
--     3. public.fn_asbuilt_locate_on_road — localise un point sur
--        ref.osm_roads (accroche + abscisse curviligne + bornes de la route)
--
-- SECURITY DEFINER, PAS de nouveau GRANT de table sur ref :
--   bureau_etudes (mig 335) n'a et ne doit garder aucun acces direct a
--   ref/infra/osiris/chantier/audit/esb/staging. fn_asbuilt_locate_on_road
--   est SECURITY DEFINER, possedee par ftth_admin (qui a acces a ref) :
--   bureau_etudes peut l'EXECUTER sans jamais avoir SELECT sur ref.osm_roads.
--   REVOKE ALL FROM PUBLIC puis GRANT EXECUTE explicite a bureau_etudes,
--   verifie en fin de fichier.
--
-- AUCUN NOUVEAU GRANT DE TABLE REQUIS pour les 2 tables : la mig 335 a deja
--   pose ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT,
--   UPDATE ON TABLES TO bureau_etudes, qui couvre toute nouvelle table de
--   public creee par ftth_admin.
--
-- ROLLBACK : 432r_rollback_asbuilt_ungeocoded_and_street_segments.sql
-- ============================================================================

\set ON_ERROR_STOP on

\echo ''
\echo '=========================================================================='
\echo '   432 - ungeocoded + depth_segments + fn_asbuilt_locate_on_road'
\echo '=========================================================================='
\echo ''

BEGIN;

-- ── 0. Extension requise pour le matching de nom insensible aux accents ────
CREATE EXTENSION IF NOT EXISTS unaccent;

-- ── 1. Table des adresses non geocodees ─────────────────────────────────────
-- Colonnes 1:1 avec UNGEOCODED_CSV_HEADER (geocode_asbuilt_depth.py, depot
-- qgis_repo). PK = intervention_id, meme cle que geofiber_asbuilt_depth_points
-- (upsert ON CONFLICT cote script).

CREATE TABLE IF NOT EXISTS public.geofiber_asbuilt_ungeocoded (
    intervention_id TEXT PRIMARY KEY,
    work_order      TEXT,
    address_raw     TEXT,
    postal_code     TEXT,
    place           TEXT,
    depth_raw       TEXT,
    geocode_query   TEXT,
    source_message  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.geofiber_asbuilt_ungeocoded IS
    'Adresses As-Built non geocodees (echec Nominatim), persistees en plus du CSV UNGEOCODED existant. Cle de dedoublonnage = intervention_id.';

CREATE OR REPLACE FUNCTION public.fn_geofiber_asbuilt_ungeocoded_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_geofiber_asbuilt_ungeocoded_updated_at
    ON public.geofiber_asbuilt_ungeocoded;
CREATE TRIGGER trg_geofiber_asbuilt_ungeocoded_updated_at
    BEFORE UPDATE ON public.geofiber_asbuilt_ungeocoded
    FOR EACH ROW
    EXECUTE FUNCTION public.fn_geofiber_asbuilt_ungeocoded_updated_at();

ALTER TABLE public.geofiber_asbuilt_ungeocoded OWNER TO ftth_admin;
ALTER FUNCTION public.fn_geofiber_asbuilt_ungeocoded_updated_at() OWNER TO ftth_admin;

\echo '  + public.geofiber_asbuilt_ungeocoded (PK intervention_id)'

-- ── 2. Table des segments d'axe de rue ──────────────────────────────────────
-- 2 lignes par paire de points adjacents (half='a'/'b'), ou 1 ligne pour un
-- segment de bout de route (point_b_intervention_id = sentinel, half='a'
-- toujours). Sentinels jamais confondables avec un vrai intervention_id
-- (numerique, cf. _INTERVENTION_RE cote script).

CREATE TABLE IF NOT EXISTS public.geofiber_asbuilt_depth_segments (
    point_a_intervention_id TEXT NOT NULL,
    -- Segment de bout de route : sentinel '__ROAD_START__'/'__ROAD_END__'
    -- au lieu d'un intervention_id reel.
    point_b_intervention_id TEXT NOT NULL,
    half                     TEXT NOT NULL CHECK (half IN ('a', 'b')),
    depth_category           TEXT,
    is_long                  BOOLEAN NOT NULL DEFAULT FALSE,
    length_m                 DOUBLE PRECISION,
    road_key                 TEXT,
    geom                     GEOMETRY(LineString, 31370),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (point_a_intervention_id, point_b_intervention_id, half)
);

COMMENT ON TABLE public.geofiber_asbuilt_depth_segments IS
    'Segments d''axe de rue entre points de profondeur As-Built consecutifs (2 moities par paire) ou segments de bout de route (point_b sentinel __ROAD_START__/__ROAD_END__). Resynchronisee integralement a chaque run du script (upsert + suppression des orphelins).';
COMMENT ON COLUMN public.geofiber_asbuilt_depth_segments.point_b_intervention_id IS
    'intervention_id du point B, ou sentinel __ROAD_START__/__ROAD_END__ pour un segment de bout de route (jamais NULL : colonne de la PK).';
COMMENT ON COLUMN public.geofiber_asbuilt_depth_segments.is_long IS
    'Longueur totale (A-B ou point-bout de route) >= 100m -> pointillé cote style.';

CREATE INDEX IF NOT EXISTS idx_geofiber_asbuilt_depth_segments_geom_gist
    ON public.geofiber_asbuilt_depth_segments USING GIST (geom);

CREATE OR REPLACE FUNCTION public.fn_geofiber_asbuilt_depth_segments_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_geofiber_asbuilt_depth_segments_updated_at
    ON public.geofiber_asbuilt_depth_segments;
CREATE TRIGGER trg_geofiber_asbuilt_depth_segments_updated_at
    BEFORE UPDATE ON public.geofiber_asbuilt_depth_segments
    FOR EACH ROW
    EXECUTE FUNCTION public.fn_geofiber_asbuilt_depth_segments_updated_at();

ALTER TABLE public.geofiber_asbuilt_depth_segments OWNER TO ftth_admin;
ALTER FUNCTION public.fn_geofiber_asbuilt_depth_segments_updated_at() OWNER TO ftth_admin;

\echo '  + public.geofiber_asbuilt_depth_segments (PK composite, GIST geom)'

-- ── 3. Fonction de localisation sur ref.osm_roads (SECURITY DEFINER) ───────

CREATE OR REPLACE FUNCTION public.fn_asbuilt_locate_on_road(
    p_point         geometry,
    p_street_name   text,
    p_search_radius numeric DEFAULT 40.0
)
RETURNS TABLE (
    road_key        text,
    position_m      numeric,
    projected_point geometry,
    road_length_m   numeric,
    road_start      geometry,
    road_end        geometry
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_name_norm text;
    v_merged    geometry;
BEGIN
    IF p_point IS NULL OR p_street_name IS NULL OR btrim(p_street_name) = '' THEN
        RETURN;
    END IF;
    v_name_norm := lower(unaccent(btrim(p_street_name)));

    SELECT ST_LineMerge(ST_Collect(r.geom))
    INTO v_merged
    FROM ref.osm_roads r
    WHERE ST_DWithin(r.geom, p_point, p_search_radius)
      AND (
            lower(unaccent(COALESCE(r.name, ''))) = v_name_norm
         OR lower(unaccent(COALESCE(r.name_fr, ''))) = v_name_norm
         OR lower(unaccent(COALESCE(r.name_nl, ''))) = v_name_norm
      );

    -- NULL (aucun troncon nomme dans le rayon), ou fusion non simple
    -- (branche/boucle -> MultiLineString) : pas d'abscisse curviligne fiable,
    -- on ne devine pas -> aucune ligne retournee (equivaut a NULL cote
    -- appelant, cf. spec).
    IF v_merged IS NULL OR GeometryType(v_merged) <> 'LINESTRING' THEN
        RETURN;
    END IF;

    road_length_m := ST_Length(v_merged);
    IF road_length_m IS NULL OR road_length_m = 0 THEN
        RETURN;
    END IF;

    road_key        := v_name_norm;
    position_m      := ST_LineLocatePoint(v_merged, p_point) * road_length_m;
    projected_point := ST_ClosestPoint(v_merged, p_point);
    road_start      := ST_StartPoint(v_merged);
    road_end        := ST_EndPoint(v_merged);
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION public.fn_asbuilt_locate_on_road(geometry, text, numeric) IS
    'Accroche un point (31370) sur le(s) troncon(s) ref.osm_roads du nom donne (accents/casse ignores), dans le rayon donne, fusionnes en une ligne. Retourne abscisse curviligne + point projete + bornes de la route. SECURITY DEFINER (ftth_admin) : appelable par bureau_etudes sans SELECT direct sur ref.osm_roads. NULL/vide si aucun troncon ne matche ou fusion non simple. Chantier 3 (mig 432).';

REVOKE ALL ON FUNCTION public.fn_asbuilt_locate_on_road(geometry, text, numeric) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.fn_asbuilt_locate_on_road(geometry, text, numeric) TO bureau_etudes;
ALTER FUNCTION public.fn_asbuilt_locate_on_road(geometry, text, numeric) OWNER TO ftth_admin;

\echo '  + public.fn_asbuilt_locate_on_road (SECURITY DEFINER, EXECUTE -> bureau_etudes)'

INSERT INTO esb.applied_migrations (migration_name, applied_at, description)
VALUES (
    '432_asbuilt_ungeocoded_and_street_segments',
    clock_timestamp(),
    'Chantier 3 geocode_asbuilt_depth : table geofiber_asbuilt_ungeocoded (adresses non geocodees, complement du CSV), table geofiber_asbuilt_depth_segments (segments d''axe de rue 2-moities entre points consecutifs), fonction SECURITY DEFINER fn_asbuilt_locate_on_road (accroche ref.osm_roads sans GRANT direct a bureau_etudes).'
)
ON CONFLICT (migration_name) DO NOTHING;

COMMIT;

-- ── Verification (hors transaction) ────────────────────────────────────────

\echo ''
\echo 'bureau_etudes peut executer fn_asbuilt_locate_on_road (attendu : t) :'
SELECT has_function_privilege(
    'bureau_etudes',
    'public.fn_asbuilt_locate_on_road(geometry, text, numeric)',
    'EXECUTE'
) AS can_execute;

\echo ''
\echo 'bureau_etudes n''a AUCUN acces direct a ref (attendu : f) :'
SELECT has_schema_privilege('bureau_etudes', 'ref', 'USAGE') AS ref_usage;

\echo ''
\echo 'Droits sur les 2 nouvelles tables (attendu : t | t | t | f, x2) :'
SELECT 'geofiber_asbuilt_ungeocoded' AS table_name,
       has_table_privilege('bureau_etudes', 'public.geofiber_asbuilt_ungeocoded', 'SELECT') AS sel,
       has_table_privilege('bureau_etudes', 'public.geofiber_asbuilt_ungeocoded', 'INSERT') AS ins,
       has_table_privilege('bureau_etudes', 'public.geofiber_asbuilt_ungeocoded', 'UPDATE') AS upd,
       has_table_privilege('bureau_etudes', 'public.geofiber_asbuilt_ungeocoded', 'DELETE') AS del
UNION ALL
SELECT 'geofiber_asbuilt_depth_segments',
       has_table_privilege('bureau_etudes', 'public.geofiber_asbuilt_depth_segments', 'SELECT'),
       has_table_privilege('bureau_etudes', 'public.geofiber_asbuilt_depth_segments', 'INSERT'),
       has_table_privilege('bureau_etudes', 'public.geofiber_asbuilt_depth_segments', 'UPDATE'),
       has_table_privilege('bureau_etudes', 'public.geofiber_asbuilt_depth_segments', 'DELETE');

\echo ''
\echo '=== [mig 432] termine ==='
```

- [ ] **Step 2: Écrire le rollback**

```sql
-- ============================================================================
-- migrations/432r_rollback_asbuilt_ungeocoded_and_street_segments.sql
-- ============================================================================
-- Rollback de 432_asbuilt_ungeocoded_and_street_segments.sql.
--
-- DESTRUCTIF : DROP TABLE supprime les segments/non-geocodes deja generes.
--   Dumper avant si besoin :
--     docker exec ftth-postgres pg_dump -U ftth_admin -d farois_ftth \
--       -t public.geofiber_asbuilt_ungeocoded \
--       -t public.geofiber_asbuilt_depth_segments > /tmp/asbuilt_432_before_rollback.sql
--
-- Aucune manipulation de role ici (contrairement au rollback 335) : ce
--   rollback est rejouable par le runner standard sous ftth_admin.
-- ============================================================================

\set ON_ERROR_STOP on

\echo ''
\echo '=== [rollback 432] ungeocoded + depth_segments + fn_asbuilt_locate_on_road ==='

BEGIN;

DROP FUNCTION IF EXISTS public.fn_asbuilt_locate_on_road(geometry, text, numeric);

DROP TRIGGER IF EXISTS trg_geofiber_asbuilt_depth_segments_updated_at
    ON public.geofiber_asbuilt_depth_segments;
DROP TABLE IF EXISTS public.geofiber_asbuilt_depth_segments;
DROP FUNCTION IF EXISTS public.fn_geofiber_asbuilt_depth_segments_updated_at();

DROP TRIGGER IF EXISTS trg_geofiber_asbuilt_ungeocoded_updated_at
    ON public.geofiber_asbuilt_ungeocoded;
DROP TABLE IF EXISTS public.geofiber_asbuilt_ungeocoded;
DROP FUNCTION IF EXISTS public.fn_geofiber_asbuilt_ungeocoded_updated_at();

DELETE FROM esb.applied_migrations
WHERE migration_name = '432_asbuilt_ungeocoded_and_street_segments';

\echo '  tables, triggers, fonctions et fonction de localisation supprimes'

COMMIT;

\echo '=== [rollback 432] termine ==='
```

- [ ] **Step 3: Écrire le test statique**

```python
"""Contrats statiques de la migration 432 (ungeocoded + depth_segments +
fn_asbuilt_locate_on_road, chantier 3 geocode_asbuilt_depth).

Verifie la structure SQL (bornes transactionnelles, presence des objets,
GRANT/REVOKE, enregistrement de la migration) sans executer contre une base
vivante. Le comportement de fn_asbuilt_locate_on_road est couvert par
tests/sql/test_asbuilt_road_locate.sql (base jetable).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "sql/migrations/432_asbuilt_ungeocoded_and_street_segments.sql"
ROLLBACK = ROOT / "sql/migrations/432r_rollback_asbuilt_ungeocoded_and_street_segments.sql"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _executable(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_migration_transactionnelle_et_enregistree():
    sql = _executable(_read(MIGRATION))
    assert "\\set ON_ERROR_STOP on" in sql
    assert re.search(r"^BEGIN;", sql, re.M) and re.search(r"^COMMIT;", sql, re.M)
    assert "INSERT INTO esb.applied_migrations" in sql
    assert "'432_asbuilt_ungeocoded_and_street_segments'" in sql
    assert "ON CONFLICT (migration_name) DO NOTHING" in sql


def test_tables_dans_public_uniquement():
    sql = _executable(_read(MIGRATION))
    assert "CREATE TABLE IF NOT EXISTS public.geofiber_asbuilt_ungeocoded" in sql
    assert "CREATE TABLE IF NOT EXISTS public.geofiber_asbuilt_depth_segments" in sql
    # Invariant de securite mig 335 : aucun GRANT sur un autre schema que public.
    for other_schema in ("infra", "osiris", "ref", "chantier", "audit", "esb", "staging"):
        assert f"GRANT" not in sql or f"SCHEMA {other_schema}" not in sql


def test_pk_segments_composite_avec_sentinels():
    sql = _executable(_read(MIGRATION))
    assert "PRIMARY KEY (point_a_intervention_id, point_b_intervention_id, half)" in sql
    assert "point_b_intervention_id TEXT NOT NULL" in sql
    assert "CHECK (half IN ('a', 'b'))" in sql
    assert "__ROAD_START__" in sql and "__ROAD_END__" in sql


def test_fonction_security_definer_avec_execute_controle():
    sql = _executable(_read(MIGRATION))
    assert "CREATE OR REPLACE FUNCTION public.fn_asbuilt_locate_on_road(" in sql
    assert "SECURITY DEFINER" in sql
    assert "SET search_path = public, pg_temp" in sql
    assert (
        "REVOKE ALL ON FUNCTION public.fn_asbuilt_locate_on_road"
        "(geometry, text, numeric) FROM PUBLIC" in sql
    )
    assert (
        "GRANT EXECUTE ON FUNCTION public.fn_asbuilt_locate_on_road"
        "(geometry, text, numeric) TO bureau_etudes" in sql
    )
    assert "ALTER FUNCTION public.fn_asbuilt_locate_on_road" in sql
    assert "ref.osm_roads" in sql


def test_pas_de_grant_de_table_supplementaire():
    # La mig 335 a deja pose ALTER DEFAULT PRIVILEGES sur public : aucun
    # nouveau GRANT SELECT/INSERT/UPDATE de table n'est necessaire ici.
    sql = _executable(_read(MIGRATION))
    assert "GRANT SELECT" not in sql
    assert "ALTER DEFAULT PRIVILEGES" not in sql


def test_rollback_supprime_tout_sans_toucher_au_role():
    sql = _executable(_read(ROLLBACK))
    assert "DROP FUNCTION IF EXISTS public.fn_asbuilt_locate_on_road" in sql
    assert "DROP TABLE IF EXISTS public.geofiber_asbuilt_depth_segments" in sql
    assert "DROP TABLE IF EXISTS public.geofiber_asbuilt_ungeocoded" in sql
    assert "DROP ROLE" not in sql  # bureau_etudes est partage, ne doit pas etre touche ici
    assert "DELETE FROM esb.applied_migrations" in sql
    assert "'432_asbuilt_ungeocoded_and_street_segments'" in sql
```

- [ ] **Step 4: Lancer le test statique**

Run: `cd ~/projects/Farois && python -m pytest tests/unit/test_migration_432_static.py -v`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit (worktree isolé, cf. mémoire "repo Farois partagé/vivant")**

```bash
cd ~/projects/Farois
git checkout -b feat/asbuilt-street-segments-mig432
git add sql/migrations/432_asbuilt_ungeocoded_and_street_segments.sql \
        sql/migrations/432r_rollback_asbuilt_ungeocoded_and_street_segments.sql \
        tests/unit/test_migration_432_static.py
git commit -m "feat(asbuilt): mig 432 - ungeocoded, depth_segments, fn_asbuilt_locate_on_road"
```

---

## Task 2: Bootstrap du suivi git de la collection `asbuilt_depth_geocoder`

**Contexte découvert pendant le brainstorming :** `asbuilt_depth_geocoder.zip` existe sur le serveur mais n'a **jamais** été poussé dans `resource-repo.git` (le dépôt bare qui fait autorité — `git --git-dir=resource-repo.git ls-tree -r HEAD` ne contient aucun fichier `asbuilt*`) ni enregistré dans `metadata.ini`. Le zip a été déposé hors du flux documenté. Risque concret : relancer `scripts/build_resource_zips.sh` supprimerait ce zip comme "orphelin" (aucun répertoire source `collections/asbuilt_depth_geocoder/` en face). Cette tâche importe l'état actuel dans git AVANT toute modification, pour disposer d'un historique/diff sur tout ce chantier — même patron que le chantier précédent (`docs/superpowers/plans/2026-08-03-geofiber-depth-upsert.md`, clone de travail `resource-repo-work/`).

**Files:**
- Create (clone de travail, non un nouveau dépôt) : `~/projects/qgis_repo/resource-repo-work/` (clone de `resource-repo.git`)
- Create: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`
- Create: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/style/depth_category.qml`

**Interfaces:** Aucune (import brut, pas de changement de comportement).

- [ ] **Step 1: Cloner le dépôt bare**

```bash
cd ~/projects/qgis_repo
git clone http://192.168.160.31:9082/ resource-repo-work
```

- [ ] **Step 2: Importer le contenu actuel du zip servi (déjà extrait pendant le brainstorming)**

```bash
mkdir -p resource-repo-work/collections/asbuilt_depth_geocoder
cp -r /tmp/asbuilt_inspect/processing resource-repo-work/collections/asbuilt_depth_geocoder/
cp -r /tmp/asbuilt_inspect/style resource-repo-work/collections/asbuilt_depth_geocoder/
```

(Si `/tmp/asbuilt_inspect` n'existe plus : `python3 -m zipfile -e ~/projects/qgis_repo/resource-repo/collections/asbuilt_depth_geocoder.zip resource-repo-work/collections/asbuilt_depth_geocoder/` extrait directement à la bonne place.)

- [ ] **Step 3: Vérifier que le contenu importé est identique au zip actuellement servi (aucune dérive avant de commencer)**

```bash
cd ~/projects/qgis_repo
diff -r resource-repo-work/collections/asbuilt_depth_geocoder /tmp/asbuilt_inspect
```

Expected: pas de sortie (répertoires identiques).

- [ ] **Step 4: Commit baseline et push**

```bash
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder
git commit -m "import: baseline asbuilt_depth_geocoder (etat production, jamais suivi jusqu'ici)"
git push
```

- [ ] **Step 5: Vérifier que le hook post-receive régénère le zip à l'identique (round-trip sans effet de bord)**

```bash
ssh sdadmin@192.168.160.31 "diff <(python3 -m zipfile -l ~/projects/qgis_repo/resource-repo/collections/asbuilt_depth_geocoder.zip) <(python3 -m zipfile -l /tmp/asbuilt_inspect_ziplist_before.txt 2>/dev/null || true)"
```

Plus simplement : comparer la liste des fichiers du zip régénéré à celle obtenue au tout début de l'investigation (`python3 -m zipfile -l asbuilt_depth_geocoder.zip` -> `processing/geocode_asbuilt_depth.py` + `style/depth_category.qml`, tailles proches). Une divergence de structure de fichiers (pas de taille — le hook recompresse) signale un problème d'import.

---

## Task 3: Simplification des seuils (3 classes fixes, plus de paramètres UI)

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/style/depth_category.qml`
- Test (temporaire, non commité — exclu de la publication, cf. Task 1 du chantier précédent) : `~/projects/qgis_repo/resource-repo-work/tests/asbuilt_depth_geocoder/test_categorize_depth.py`

**Interfaces:**
- Produces: `categorize_depth(depth_cm: Optional[float]) -> str` (signature changée : ne prend plus `thresholds` — seuils fixes) ; constantes `THRESHOLD_MISSING_CM = 10.0`, `THRESHOLD_ORANGE_CM = 50.0`, `THRESHOLD_VERT_CM = 55.0` ; `DEPTH_COLORS = {"manquante": "#999999", "rouge": "#D7263D", "orange": "#F4A300", "vert": "#2A9D3D"}` (retrait de `"jaune"`) ; `DEPTH_CATEGORY_LABELS: dict[str, str]` (constante, plus une fonction de seuils) ; `DEPTH_SUMMARY_ORDER = ("vert", "orange", "rouge", "manquante")`.

- [ ] **Step 1: Écrire le test pytest pur (hors QGIS)**

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/asbuilt_depth_geocoder/test_categorize_depth.py -v`
Expected: FAIL (`categorize_depth` prend encore `thresholds`, `"jaune"` encore présent).

- [ ] **Step 3: Modifier `categorize_depth` et les constantes**

Dans `geocode_asbuilt_depth.py`, remplacer le bloc constantes (autour de `DEPTH_COLORS`/`DEPTH_SUMMARY_ORDER`) :

```python
THRESHOLD_MISSING_CM = 10.0
THRESHOLD_ORANGE_CM = 50.0
THRESHOLD_VERT_CM = 55.0

DEPTH_COLORS = {
    "manquante": "#999999",
    "rouge": "#D7263D",
    "orange": "#F4A300",
    "vert": "#2A9D3D",
}

DEPTH_SUMMARY_ORDER = ("vert", "orange", "rouge", "manquante")

DEPTH_CATEGORY_LABELS = {
    "manquante": "Manquante — non mesurée",
    "rouge": f"Rouge — non conforme (< {THRESHOLD_ORANGE_CM:g} cm)",
    "orange": f"Orange — limite ({THRESHOLD_ORANGE_CM:g}–{THRESHOLD_VERT_CM:g} cm)",
    "vert": f"Vert — conforme (≥ {THRESHOLD_VERT_CM:g} cm)",
}
```

Supprimer la dataclass `DepthThresholds` (plus utilisée). Remplacer `categorize_depth` :

```python
def categorize_depth(depth_cm: Optional[float]) -> str:
    """Catégorise une profondeur (cm) en manquante/rouge/orange/vert (seuils fixes)."""
    if depth_cm is None or depth_cm < THRESHOLD_MISSING_CM:
        return "manquante"
    if depth_cm < THRESHOLD_ORANGE_CM:
        return "rouge"
    if depth_cm < THRESHOLD_VERT_CM:
        return "orange"
    return "vert"
```

Supprimer `depth_category_labels()` (remplacée par la constante `DEPTH_CATEGORY_LABELS` ci-dessus). Supprimer `_relabel_depth_renderer()` en entier : elle réalignait les libellés du `.qml` sur des seuils utilisateur qui n'existent plus — le `.qml` mis à jour (Step 5) porte désormais directement les bons libellés, plus rien à réaligner à l'exécution.

Mettre à jour tous les appelants :
- `_build_depth_renderer(thresholds)` -> `_build_depth_renderer()` (boucle sur `("manquante", "rouge", "orange", "vert")`, labels via `DEPTH_CATEGORY_LABELS`)
- `_apply_depth_style(layer, thresholds, feedback=None)` -> `_apply_depth_style(layer, feedback=None)` : supprimer l'appel à `_relabel_depth_renderer` (fonction supprimée), garder le chargement du `.qml` + repli Python
- `_build_attribute_values(rec, thresholds, query, status, hit)` -> `_build_attribute_values(rec, query, status, hit)` : `categorize_depth(depth_cm)` sans `thresholds`
- `_DepthLayerStyler.__init__(self, thresholds)` -> `__init__(self)` (plus rien à stocker), `postProcessLayer` appelle `_apply_depth_style(layer, feedback)`
- Dans `initAlgorithm` : supprimer les 3 blocs `self.addParameter(QgsProcessingParameterNumber(self.THRESHOLD_GREEN/YELLOW/ORANGE, ...))` (garder aucun seuil paramétrable — `THRESHOLD_MISSING` disparaît aussi, remplacé par la constante `THRESHOLD_MISSING_CM`). Supprimer les attributs de classe `THRESHOLD_GREEN`, `THRESHOLD_YELLOW`, `THRESHOLD_ORANGE`, `THRESHOLD_MISSING`.
- Dans `processAlgorithm` : supprimer la construction `thresholds = DepthThresholds(...)` et toute variable `thresholds` passée en aval ; `_apply_depth_style(layer, feedback)`, `_build_attribute_values(rec, query, status, hit)`, `_DepthLayerStyler()` sans argument.
- Dans `shortHelpString` : remplacer "Catégories : manquante (gris), rouge, orange, jaune, vert selon les seuils paramétrables." par "Catégories (seuils fixes) : manquante (< 10 cm), rouge (< 50 cm), orange (< 55 cm), vert (≥ 55 cm)."

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/asbuilt_depth_geocoder/test_categorize_depth.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Mettre à jour `style/depth_category.qml`**

Ouvrir `collections/asbuilt_depth_geocoder/style/depth_category.qml`, supprimer la règle/catégorie dont le filtre est `"depth_category" = 'jaune'` (structure `RuleRenderer` — une `<rule>` par catégorie, cf. `_relabel_depth_renderer` original qui itérait `renderer.rootRule().children()`), et mettre à jour le libellé (`label="..."`) des règles restantes pour qu'il corresponde exactement à `DEPTH_CATEGORY_LABELS` (Step 3) — plus de réalignement à l'exécution, le `.qml` est maintenant la source unique et définitive des libellés.

- [ ] **Step 6: Grep de contrôle — plus aucune référence à "jaune"/"YELLOW"/"DepthThresholds"**

Run: `cd ~/projects/qgis_repo/resource-repo-work && grep -rniE 'jaune|yellow|DepthThresholds|THRESHOLD_GREEN|THRESHOLD_YELLOW' collections/asbuilt_depth_geocoder/`
Expected: aucune sortie.

- [ ] **Step 7: Commit dans le clone de travail (pas de push — Task 9 regroupe la publication finale)**

```bash
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder
git commit -m "feat(asbuilt): seuils fixes (rouge/orange/vert), suppression des parametres UI"
```

---

## Task 4: Synchronisation du style en base (`layer_styles`, `useAsDefault=True`)

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`

**Interfaces:**
- Consumes: `_apply_depth_style(layer, feedback=None)` (Task 3)
- Produces: `_sync_style_to_db(layer, name: str, description: str, feedback) -> bool`

- [ ] **Step 1: Ajouter la fonction, juste après `_apply_depth_style`**

```python
    def _sync_style_to_db(layer, name: str, description: str, feedback) -> bool:
        """Ecrit le style courant de ``layer`` dans layer_styles (useAsDefault=True).

        Best-effort, non bloquant (meme politique que _apply_depth_style et
        _upsert_geocoded_records) : un echec loggue une info sans jamais faire
        echouer le run. Ne fonctionne que si layer est connectee en direct sur
        postgres (c'est le cas pour les couches upsertees via 'be', cf.
        _upsert_geocoded_records / _upsert_segment_records).
        """
        try:
            ok, err = layer.saveStyleToDatabase(name, description, True, "")
        except Exception as exc:  # pragma: no cover - defensif
            feedback.pushInfo(f"Style non synchronise en base pour « {name} » ({exc}).")
            return False
        if not ok:
            feedback.pushInfo(f"Style non synchronise en base pour « {name} » ({err}).")
        return bool(ok)
```

- [ ] **Step 2: Appeler `_sync_style_to_db` après l'upsert des points géocodés, dans `processAlgorithm`**

Juste après l'appel existant à `self._upsert_geocoded_records(geocoded_for_db, feedback)`, dans la même section (`if push_to_be:`), ajouter :

```python
                if push_to_be and geocoded_for_db:
                    be_points_layer = self._open_be_points_layer(feedback)
                    if be_points_layer is not None:
                        _apply_depth_style(be_points_layer, feedback)
                        _sync_style_to_db(
                            be_points_layer,
                            "depth_category",
                            "Style profondeur As-Built (points) — géré par geocode_asbuilt_depth, ne pas éditer manuellement.",
                            feedback,
                        )
```

Extraire l'ouverture de couche postgres (déjà dupliquée dans `_upsert_geocoded_records`, lignes `base_uri = be_connection.tableUri(...)` / `QgsDataSourceUri` / `QgsVectorLayer(..., "postgres")`) dans une méthode partagée :

```python
        def _open_be_layer(self, schema: str, table: str, geom_column: str, wkb_type, feedback):
            """Ouvre schema.table via la connexion 'be', geometrie forcee (cf. commentaire
            historique sur tableUri() dans _upsert_geocoded_records : ne pas faire confiance
            a l'auto-detection sur cette connexion)."""
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            if be_connection is None:
                feedback.pushWarning(
                    f"Connexion QGIS 'be' introuvable — {schema}.{table} non accessible."
                )
                return None
            try:
                base_uri = be_connection.tableUri(schema, table)
                ds_uri = QgsDataSourceUri(base_uri)
                ds_uri.setGeometryColumn(geom_column)
                ds_uri.setSrid(OUTPUT_CRS.split(":")[-1])
                ds_uri.setWkbType(wkb_type)
                layer = QgsVectorLayer(ds_uri.uri(False), table, "postgres")
            except Exception as exc:
                feedback.pushWarning(f"Connexion a {schema}.{table} via 'be' impossible ({exc}).")
                return None
            if not layer.isValid() or not layer.isSpatial():
                feedback.pushWarning(f"Couche {schema}.{table} invalide via 'be'.")
                return None
            return layer

        def _open_be_points_layer(self, feedback):
            return self._open_be_layer(
                BE_TABLE_SCHEMA, BE_TABLE_NAME, BE_GEOM_COLUMN, QgsWkbTypes.Point, feedback
            )
```

Refactoriser `_upsert_geocoded_records` pour appeler `self._open_be_layer(BE_TABLE_SCHEMA, BE_TABLE_NAME, BE_GEOM_COLUMN, QgsWkbTypes.Point, feedback)` au lieu de dupliquer la résolution de connexion (supprime la duplication introduite par Task 5/8 qui réutilisent le même helper).

- [ ] **Step 3: Test manuel (pas de mock PyQGIS pratique ici — comportement vérifié à l'exécution réelle, Task 9)**

Documenté dans le plan, pas de pytest pur possible : `saveStyleToDatabase` nécessite une vraie couche postgres QGIS. Couvert par la vérification manuelle de Task 9 Step 4 (relecture `layer_styles` après un run réel).

- [ ] **Step 4: Commit**

```bash
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py
git commit -m "feat(asbuilt): sync style points vers layer_styles (useAsDefault=True)"
```

---

## Task 5: Table des non-géocodés (`_upsert_ungeocoded_records`)

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`

**Interfaces:**
- Consumes: `self._open_be_layer(...)` (Task 4), `InterventionRecord` (existant)
- Produces: `self._upsert_ungeocoded_records(entries, feedback)` où `entries: list[tuple[InterventionRecord, str]]` (même forme que `build_ungeocoded_rows`)

- [ ] **Step 1: Ajouter les constantes de table, à côté de `BE_TABLE_NAME`**

```python
    UNGEOCODED_TABLE_SCHEMA = "public"
    UNGEOCODED_TABLE_NAME = "geofiber_asbuilt_ungeocoded"

    _UNGEOCODED_FIELD_SPECS = [
        ("intervention_id", QVariant.String),
        ("work_order", QVariant.String),
        ("address_raw", QVariant.String),
        ("postal_code", QVariant.String),
        ("place", QVariant.String),
        ("depth_raw", QVariant.String),
        ("geocode_query", QVariant.String),
        ("source_message", QVariant.String),
    ]
```

- [ ] **Step 2: Ajouter `_upsert_ungeocoded_records`, calquée sur `_upsert_geocoded_records`**

```python
        def _upsert_ungeocoded_records(self, entries, feedback):
            """Upsert les adresses non geocodees dans public.geofiber_asbuilt_ungeocoded.

            ``entries`` : (InterventionRecord, query) — meme forme que
            build_ungeocoded_rows. Best-effort, meme politique que
            _upsert_geocoded_records : ne fait jamais echouer le run.
            """
            if not entries:
                feedback.pushInfo("Base 'be' : aucune adresse non geocodee a pousser.")
                return
            layer = self._open_be_layer(
                self.UNGEOCODED_TABLE_SCHEMA, self.UNGEOCODED_TABLE_NAME,
                geom_column=None, wkb_type=None, feedback=feedback,
            ) if False else self._open_be_nonspatial_layer(
                self.UNGEOCODED_TABLE_SCHEMA, self.UNGEOCODED_TABLE_NAME, feedback
            )
            if layer is None:
                return
            fields = layer.fields()
            id_field = QgsExpression.quotedColumnRef("intervention_id")
            inserted = updated = failed = 0
            for rec, query in entries:
                values = {
                    "intervention_id": rec.intervention,
                    "work_order": rec.work_order,
                    "address_raw": rec.address,
                    "postal_code": rec.postal_code,
                    "place": rec.place,
                    "depth_raw": rec.depth_raw,
                    "geocode_query": query,
                    "source_message": rec.source_message,
                }
                id_value = QgsExpression.quotedValue(values["intervention_id"])
                request = QgsFeatureRequest()
                request.setFilterExpression(f"{id_field} = {id_value}")
                existing = list(layer.getFeatures(request))

                layer.startEditing()
                ok = False
                try:
                    if existing:
                        fid = existing[0].id()
                        attr_map = {
                            fields.indexOf(name): value
                            for name, value in values.items()
                            if name != "intervention_id"
                        }
                        ok = layer.changeAttributeValues(fid, attr_map)
                    else:
                        feat = QgsFeature(fields)
                        for name, value in values.items():
                            feat.setAttribute(name, value)
                        ok = layer.addFeature(feat)
                    ok = ok and layer.commitChanges()
                except Exception as exc:
                    feedback.reportError(
                        f"Echec upsert non-geocode {values['intervention_id']} : {exc}",
                        fatalError=False,
                    )
                    ok = False

                if ok:
                    updated += 1 if existing else 0
                    inserted += 0 if existing else 1
                else:
                    failed += 1
                    for err in layer.commitErrors():
                        feedback.reportError(
                            f"Non-geocode {values['intervention_id']} : {err}",
                            fatalError=False,
                        )
                    layer.rollBack()

            feedback.pushInfo(
                f"Base 'be' (non-geocodes) : {inserted} creee(s), {updated} mise(s) a jour, "
                f"{failed} echec(s) sur {len(entries)}."
            )
```

- [ ] **Step 3: Ajouter `_open_be_nonspatial_layer` (table sans géométrie — `tableUri` suffit, pas besoin du contournement `QgsDataSourceUri`/geometry column du helper spatial)**

```python
        def _open_be_nonspatial_layer(self, schema: str, table: str, feedback):
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            if be_connection is None:
                feedback.pushWarning(
                    f"Connexion QGIS 'be' introuvable — {schema}.{table} non accessible."
                )
                return None
            try:
                layer = QgsVectorLayer(be_connection.tableUri(schema, table), table, "postgres")
            except Exception as exc:
                feedback.pushWarning(f"Connexion a {schema}.{table} via 'be' impossible ({exc}).")
                return None
            if not layer.isValid():
                feedback.pushWarning(f"Couche {schema}.{table} invalide via 'be'.")
                return None
            return layer
```

Supprimer la branche morte `if False else` introduite Step 2 (artefact d'écriture) — appeler directement `self._open_be_nonspatial_layer(...)`.

- [ ] **Step 4: Appeler `_upsert_ungeocoded_records` dans `processAlgorithm`, juste après l'appel à `_upsert_geocoded_records`**

```python
                if push_to_be:
                    self._upsert_ungeocoded_records(ungeocoded, feedback)
```

(`ungeocoded` est déjà construite dans `processAlgorithm`, cf. code existant lu pendant le brainstorming — liste de `(InterventionRecord, query)`.)

- [ ] **Step 5: Commit**

```bash
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py
git commit -m "feat(asbuilt): persistance des adresses non geocodees (public.geofiber_asbuilt_ungeocoded)"
```

---

## Task 6: Fonctions pures d'appariement des segments (`build_segment_halves`)

Aucune dépendance PyQGIS — la partie la plus délicate du chantier (algorithme non trivial), entièrement testable hors QGIS.

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`
- Test (temporaire, non commité) : `~/projects/qgis_repo/resource-repo-work/tests/asbuilt_depth_geocoder/test_build_segment_halves.py`

**Interfaces:**
- Produces:
  - `LONG_SEGMENT_THRESHOLD_M = 100.0`
  - `ROAD_START_SENTINEL = "__ROAD_START__"`, `ROAD_END_SENTINEL = "__ROAD_END__"`
  - `@dataclass RoadLocation(intervention_id: str, depth_category: str, road_key: str, position_m: float, x: float, y: float)`
  - `@dataclass RoadExtent(length_m: float, start_x: float, start_y: float, end_x: float, end_y: float)`
  - `@dataclass SegmentHalf(point_a_intervention_id: str, point_b_intervention_id: str, half: str, depth_category: str, is_long: bool, length_m: float, road_key: str, start_x: float, start_y: float, end_x: float, end_y: float)`
  - `build_segment_halves(locations: list[RoadLocation], road_extents: dict[str, RoadExtent]) -> list[SegmentHalf]`

- [ ] **Step 1: Écrire les tests (couvre les 3 items du Review Focus qui concernent cette fonction)**

```python
# resource-repo-work/tests/asbuilt_depth_geocoder/test_build_segment_halves.py
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    RoadLocation, RoadExtent, SegmentHalf,
    build_segment_halves, ROAD_START_SENTINEL, ROAD_END_SENTINEL,
    LONG_SEGMENT_THRESHOLD_M,
)


def _extent(length_m, start=(0.0, 0.0), end=None):
    end = end or (length_m, 0.0)
    return RoadExtent(length_m=length_m, start_x=start[0], start_y=start[1],
                       end_x=end[0], end_y=end[1])


def test_paire_adjacente_produit_deux_moities():
    locs = [
        RoadLocation("1", "rouge", "rue x", position_m=0.0, x=0.0, y=0.0),
        RoadLocation("2", "vert", "rue x", position_m=40.0, x=40.0, y=0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(100.0)})
    pair_halves = [h for h in halves if h.point_b_intervention_id == "2"]
    assert len(pair_halves) == 2
    a = next(h for h in pair_halves if h.half == "a")
    b = next(h for h in pair_halves if h.half == "b")
    assert a.depth_category == "rouge" and a.start_x == 0.0 and a.end_x == 20.0
    assert b.depth_category == "vert" and b.start_x == 20.0 and b.end_x == 40.0
    assert a.length_m == 40.0 and b.length_m == 40.0  # longueur totale de la paire, pas de la moitie
    assert not a.is_long and not b.is_long


def test_pointille_si_longueur_superieure_ou_egale_100m():
    locs = [
        RoadLocation("1", "rouge", "rue x", position_m=0.0, x=0.0, y=0.0),
        RoadLocation("2", "vert", "rue x", position_m=100.0, x=100.0, y=0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(200.0)})
    pair_halves = [h for h in halves if h.point_b_intervention_id == "2"]
    assert all(h.is_long for h in pair_halves)


def test_points_gris_deja_exclus_en_amont_ne_cassent_pas_la_chaine():
    # 'manquante' est filtre par l'appelant (cf. Task 7) avant meme d'arriver
    # ici : A et C, adjacents dans la liste fournie, forment un segment normal.
    locs = [
        RoadLocation("A", "rouge", "rue x", position_m=0.0, x=0.0, y=0.0),
        RoadLocation("C", "vert", "rue x", position_m=60.0, x=60.0, y=0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(100.0)})
    assert {h.point_b_intervention_id for h in halves if h.point_a_intervention_id == "A"} == {"C", ROAD_END_SENTINEL}


def test_segment_longueur_zero_ne_plante_pas_et_nest_pas_pointille():
    locs = [
        RoadLocation("1", "rouge", "rue x", position_m=10.0, x=10.0, y=0.0),
        RoadLocation("2", "vert", "rue x", position_m=10.0, x=10.0, y=0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(50.0)})
    pair_halves = [h for h in halves if h.point_b_intervention_id == "2"]
    assert len(pair_halves) == 2
    assert all(h.length_m == 0.0 and not h.is_long for h in pair_halves)


def test_point_isole_produit_deux_segments_de_bout_de_route():
    locs = [RoadLocation("1", "orange", "rue x", position_m=30.0, x=30.0, y=0.0)]
    halves = build_segment_halves(locs, {"rue x": _extent(80.0)})
    assert len(halves) == 2
    targets = {h.point_b_intervention_id for h in halves}
    assert targets == {ROAD_START_SENTINEL, ROAD_END_SENTINEL}
    assert all(h.half == "a" and h.depth_category == "orange" for h in halves)
    start_seg = next(h for h in halves if h.point_b_intervention_id == ROAD_START_SENTINEL)
    end_seg = next(h for h in halves if h.point_b_intervention_id == ROAD_END_SENTINEL)
    assert start_seg.length_m == 30.0
    assert end_seg.length_m == 50.0


def test_road_key_sans_extent_ignore_les_bouts_de_route_sans_planter():
    locs = [RoadLocation("1", "vert", "rue inconnue", position_m=5.0, x=5.0, y=0.0)]
    halves = build_segment_halves(locs, {})
    assert halves == []


def test_deux_groupes_de_road_key_independants():
    locs = [
        RoadLocation("1", "rouge", "rue a", position_m=0.0, x=0.0, y=0.0),
        RoadLocation("2", "vert", "rue a", position_m=10.0, x=10.0, y=0.0),
        RoadLocation("3", "orange", "rue b", position_m=0.0, x=0.0, y=100.0),
    ]
    extents = {"rue a": _extent(10.0), "rue b": _extent(5.0, start=(0.0, 100.0), end=(5.0, 100.0))}
    halves = build_segment_halves(locs, extents)
    assert {h.point_a_intervention_id for h in halves} == {"1", "3"}
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/asbuilt_depth_geocoder/test_build_segment_halves.py -v`
Expected: FAIL (`ImportError` — rien n'existe encore).

- [ ] **Step 3: Implémenter, dans la section « Fonctions PURES » (avant le bloc `if HAS_QGIS:`)**

```python
import math
from collections import defaultdict

LONG_SEGMENT_THRESHOLD_M = 100.0
ROAD_START_SENTINEL = "__ROAD_START__"
ROAD_END_SENTINEL = "__ROAD_END__"


@dataclass
class RoadLocation:
    """Un point de profondeur localise sur son axe de rue (fn_asbuilt_locate_on_road)."""

    intervention_id: str
    depth_category: str
    road_key: str
    position_m: float
    x: float
    y: float


@dataclass
class RoadExtent:
    """Bornes de la ligne de route fusionnee pour un road_key donne."""

    length_m: float
    start_x: float
    start_y: float
    end_x: float
    end_y: float


@dataclass
class SegmentHalf:
    """Une moitie de segment d'axe de rue (ou un segment de bout de route, half='a' seul).

    ``length_m`` est la longueur TOTALE du segment (A-B ou point-bout de
    route), identique sur les 2 moities d'une meme paire — pas la longueur
    de la moitie elle-meme.
    """

    point_a_intervention_id: str
    point_b_intervention_id: str  # intervention_id reel, ou ROAD_START_SENTINEL/ROAD_END_SENTINEL
    half: str  # 'a' ou 'b'
    depth_category: str
    is_long: bool
    length_m: float
    road_key: str
    start_x: float
    start_y: float
    end_x: float
    end_y: float


def build_segment_halves(locations, road_extents) -> list:
    """Construit les moities de segments d'axe de rue.

    ``locations`` : points DEJA filtres (categorie != 'manquante') et
    localises via fn_asbuilt_locate_on_road (un road_key manquant/vide est
    filtre par l'appelant, cf. Task 7). ``road_extents`` : dict road_key ->
    RoadExtent (bornes de la route fusionnee, pour les segments de bout de
    route). Fonction PURE, aucune dependance PyQGIS.
    """
    by_road = defaultdict(list)
    for loc in locations:
        by_road[loc.road_key].append(loc)

    halves: list[SegmentHalf] = []
    for road_key, points in by_road.items():
        ordered = sorted(points, key=lambda p: p.position_m)

        for a, b in zip(ordered, ordered[1:]):
            length = math.hypot(b.x - a.x, b.y - a.y)
            is_long = length >= LONG_SEGMENT_THRESHOLD_M
            mid_x, mid_y = (a.x + b.x) / 2.0, (a.y + b.y) / 2.0
            halves.append(SegmentHalf(
                point_a_intervention_id=a.intervention_id,
                point_b_intervention_id=b.intervention_id,
                half="a", depth_category=a.depth_category, is_long=is_long,
                length_m=length, road_key=road_key,
                start_x=a.x, start_y=a.y, end_x=mid_x, end_y=mid_y,
            ))
            halves.append(SegmentHalf(
                point_a_intervention_id=a.intervention_id,
                point_b_intervention_id=b.intervention_id,
                half="b", depth_category=b.depth_category, is_long=is_long,
                length_m=length, road_key=road_key,
                start_x=mid_x, start_y=mid_y, end_x=b.x, end_y=b.y,
            ))

        extent = road_extents.get(road_key)
        if extent is None:
            continue
        first, last = ordered[0], ordered[-1]
        for point, sentinel, (end_x, end_y) in (
            (first, ROAD_START_SENTINEL, (extent.start_x, extent.start_y)),
            (last, ROAD_END_SENTINEL, (extent.end_x, extent.end_y)),
        ):
            length = math.hypot(end_x - point.x, end_y - point.y)
            halves.append(SegmentHalf(
                point_a_intervention_id=point.intervention_id,
                point_b_intervention_id=sentinel,
                half="a", depth_category=point.depth_category,
                is_long=length >= LONG_SEGMENT_THRESHOLD_M,
                length_m=length, road_key=road_key,
                start_x=point.x, start_y=point.y, end_x=end_x, end_y=end_y,
            ))
    return halves
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/asbuilt_depth_geocoder/test_build_segment_halves.py -v`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py
git commit -m "feat(asbuilt): fonction pure build_segment_halves (appariement + bouts de route)"
```

---

## Task 7: Localisation des points sur l'axe de rue (`fn_asbuilt_locate_on_road` via `be`)

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`
- Test (temporaire, non commité) : `~/projects/qgis_repo/resource-repo-work/tests/asbuilt_depth_geocoder/test_extract_street_name.py`

**Interfaces:**
- Consumes: `RoadLocation`, `RoadExtent` (Task 6)
- Produces: `fix_szett_artifact(text: str) -> str` (pure) ; `extract_street_name(address_raw: Optional[str]) -> str` (pure, applique `fix_szett_artifact`) ; `self._locate_points_on_road(self, rows, feedback) -> tuple[list[RoadLocation], dict[str, RoadExtent], bool]` — le 3e élément (`had_connection_error`) est `True` si au moins un appel a échoué pour une raison de connexion/permission (par opposition à « aucun tronçon ne matche », qui est un résultat légitime) ; consommé par Task 8 pour ne PAS purger les segments sur un recalcul non fiable (cf. Review Focus).

- [ ] **Step 1: Écrire le test pytest pur pour `extract_street_name`**

```python
# resource-repo-work/tests/asbuilt_depth_geocoder/test_extract_street_name.py
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import extract_street_name


def test_numero_simple():
    assert extract_street_name("Rue de la Gare 12") == "Rue de la Gare"


def test_numero_boite_notation_belge():
    assert extract_street_name("Rue de la Gare 12/3") == "Rue de la Gare"


def test_numero_avec_lettre():
    assert extract_street_name("Avenue Louise 145A") == "Avenue Louise"


def test_sans_numero_repli_sur_la_chaine_entiere():
    assert extract_street_name("Rue de la Gare") == "Rue de la Gare"


def test_vide_ou_none():
    assert extract_street_name(None) == ""
    assert extract_street_name("") == ""
    assert extract_street_name("   ") == ""


def test_szett_suivi_de_s_parasite_est_nettoye():
    # Le ß allemand vaut deja "ss" : un 's' immediatement apres est une
    # duplication parasite observee en donnees reelles (export BeOn).
    assert extract_street_name("Malmedyer Straßse 12") == "Malmedyer Straße"


def test_szett_sans_s_parasite_est_inchange():
    assert extract_street_name("Malmedyer Straße 12") == "Malmedyer Straße"


def test_szett_suivi_de_S_majuscule_est_nettoye():
    assert extract_street_name("Kaiserstraßse") == "Kaiserstraße"
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/asbuilt_depth_geocoder/test_extract_street_name.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implémenter `fix_szett_artifact` et `extract_street_name`, dans la section fonctions pures (à côté de `normalize_place`)**

```python
_HOUSE_NUMBER_RE = re.compile(r"^(.*?)\s+\d+[a-zA-Z]?(?:[/\-]\S+)?\s*$")
_SZETT_DOUBLE_S_RE = re.compile(r"ß[sS]")


def fix_szett_artifact(text: str) -> str:
    """Corrige l'artefact 'ßs'/'ßS' -> 'ß'.

    Le ß allemand (Eszett) vaut deja phonetiquement 'ss' ; un 's' immediatement
    apres est une duplication parasite observee en donnees reelles (export
    BeOn, adresses germanophones de la region), ex. « Malmedyer Straßse » au
    lieu de « Malmedyer Straße ». Ne touche PAS un 's' plus loin dans le mot
    (seulement collé au ß).
    """
    if not text:
        return text
    return _SZETT_DOUBLE_S_RE.sub("ß", text)


def extract_street_name(address_raw: Optional[str]) -> str:
    """Extrait le nom de rue d'une adresse brute belge (tronque le numero/boite final).

    Notation belge : ``"Rue de la Gare 12"`` / ``"Rue de la Gare 12/3"`` ->
    ``"Rue de la Gare"``. Pas de numero detecte en fin de chaine (deja sans
    numero, ou format non reconnu) -> la chaine est renvoyee telle quelle
    (repli permissif : le matching de nom cote SQL est normalise/insensible
    a la casse ; un residu de numero non tronque fera simplement echouer le
    matching plutot que de planter). Applique fix_szett_artifact avant tout
    le reste (l'artefact peut apparaitre n'importe ou dans le nom de rue).
    """
    if not address_raw:
        return ""
    text = fix_szett_artifact(address_raw.strip())
    if not text:
        return ""
    match = _HOUSE_NUMBER_RE.match(text)
    return match.group(1).strip() if match else text
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/asbuilt_depth_geocoder/test_extract_street_name.py -v`
Expected: 8 tests PASS.

- [ ] **Step 5: Appliquer la même correction à la construction de la requête Nominatim (`build_geocode_query`, code existant)**

Dans `build_geocode_query`, avant toute autre normalisation de l'adresse en entrée (première ligne utile de la fonction), ajouter :

```python
    address = fix_szett_artifact(address)
```

Même artefact, même correction — le géocodage Nominatim souffre du même problème que le matching de rue pour les segments, cause commune (export BeOn), pas la peine de dupliquer la logique.

- [ ] **Step 6: Lancer la suite pytest existante du script pour vérifier l'absence de régression**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/asbuilt_depth_geocoder/ -v -k "geocode_query or szett or street_name"`
Expected: PASS (aucun test existant sur `build_geocode_query` ne porte sur un « ß » suivi de « s », donc aucune régression attendue — à confirmer par la lecture des tests déjà présents avant cette étape, s'il y en a d'exécutés localement).

- [ ] **Step 7: Implémenter `_locate_points_on_road`, méthode de `GeocodeAsBuiltDepthAlgorithm`**

```python
        def _locate_points_on_road(self, rows, feedback):
            """Localise chaque ligne (dict avec intervention_id/depth_category/address_raw/x/y)
            sur son axe de rue via public.fn_asbuilt_locate_on_road (connexion 'be').

            Retourne (locations, road_extents, had_connection_error). Un point sans nom de
            rue extractible, ou sans troncon matchant, est silencieusement omis (pas une
            erreur — cf. spec). had_connection_error=True seulement sur un echec de
            connexion/permission (feedback.reportError), jamais sur une absence de match.
            """
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            if be_connection is None:
                feedback.pushWarning(
                    "Connexion QGIS 'be' introuvable — segments d'axe de rue non calcules."
                )
                return [], {}, True

            locations: list[RoadLocation] = []
            road_extents: dict[str, RoadExtent] = {}
            had_connection_error = False

            for row in rows:
                street_name = extract_street_name(row["address_raw"])
                if not street_name:
                    continue
                street_literal = QgsExpression.quotedValue(street_name)
                sql = (
                    "SELECT road_key, position_m, "
                    "ST_X(projected_point), ST_Y(projected_point), "
                    "road_length_m, ST_X(road_start), ST_Y(road_start), "
                    "ST_X(road_end), ST_Y(road_end) "
                    "FROM public.fn_asbuilt_locate_on_road("
                    f"ST_SetSRID(ST_MakePoint({row['x']!r}, {row['y']!r}), 31370), "
                    f"{street_literal})"
                )
                try:
                    result = be_connection.executeSql(sql)
                except Exception as exc:
                    feedback.reportError(
                        f"fn_asbuilt_locate_on_road indisponible pour "
                        f"{row['intervention_id']} : {exc}",
                        fatalError=False,
                    )
                    had_connection_error = True
                    continue
                if not result:
                    continue  # aucun troncon nomme dans le rayon : omission normale
                (road_key, position_m, px, py,
                 road_length_m, sx, sy, ex, ey) = result[0]
                locations.append(RoadLocation(
                    intervention_id=row["intervention_id"],
                    depth_category=row["depth_category"],
                    road_key=road_key, position_m=float(position_m),
                    x=float(px), y=float(py),
                ))
                road_extents.setdefault(road_key, RoadExtent(
                    length_m=float(road_length_m),
                    start_x=float(sx), start_y=float(sy),
                    end_x=float(ex), end_y=float(ey),
                ))

            feedback.pushInfo(
                f"Segments : {len(locations)} point(s) localise(s) sur un axe de rue "
                f"sur {len(rows)} fourni(s)."
            )
            return locations, road_extents, had_connection_error
```

- [ ] **Step 8: Commit**

```bash
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py
git commit -m "feat(asbuilt): fix_szett_artifact + extract_street_name + _locate_points_on_road (fn_asbuilt_locate_on_road via be)"
```

---

## Task 8: Resynchronisation complète des segments (relecture, upsert, purge des orphelins)

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`
- Create: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/style/depth_segments.qml`
- Test (temporaire, non commité) : `~/projects/qgis_repo/resource-repo-work/tests/asbuilt_depth_geocoder/test_segment_sync_plan.py`

**Interfaces:**
- Consumes: `build_segment_halves` (Task 6), `_locate_points_on_road` (Task 7), `_open_be_layer`/`_sync_style_to_db` (Task 4)
- Produces: `plan_segment_sync(fresh: list[SegmentHalf], existing_keys: set[tuple[str, str, str]]) -> tuple[list[SegmentHalf], list[tuple[str, str, str]]]` (pure — sépare « à upsert » de « à supprimer ») ; `self._sync_segments(feedback)` (orchestration QGIS) ; nouveau paramètre `OUTPUT_SEGMENTS`.

- [ ] **Step 1: Écrire le test pytest pur pour `plan_segment_sync` (couvre l'idempotence et la non-purge, items 4 et 5 du Review Focus)**

```python
# resource-repo-work/tests/asbuilt_depth_geocoder/test_segment_sync_plan.py
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import SegmentHalf, plan_segment_sync


def _half(a, b, half):
    return SegmentHalf(
        point_a_intervention_id=a, point_b_intervention_id=b, half=half,
        depth_category="vert", is_long=False, length_m=10.0, road_key="rue x",
        start_x=0.0, start_y=0.0, end_x=10.0, end_y=0.0,
    )


def test_premiere_synchro_tout_en_upsert_rien_a_supprimer():
    fresh = [_half("1", "2", "a"), _half("1", "2", "b")]
    to_upsert, to_delete = plan_segment_sync(fresh, existing_keys=set())
    assert len(to_upsert) == 2
    assert to_delete == []


def test_rerun_sans_changement_est_idempotent():
    fresh = [_half("1", "2", "a"), _half("1", "2", "b")]
    existing = {("1", "2", "a"), ("1", "2", "b")}
    to_upsert, to_delete = plan_segment_sync(fresh, existing_keys=existing)
    assert len(to_upsert) == 2  # upsert = toujours rejoue (ON CONFLICT DO UPDATE cote SQL)
    assert to_delete == []


def test_segment_disparu_est_marque_a_supprimer():
    fresh = [_half("1", "2", "a"), _half("1", "2", "b")]
    existing = {("1", "2", "a"), ("1", "2", "b"), ("2", "3", "a"), ("2", "3", "b")}
    to_upsert, to_delete = plan_segment_sync(fresh, existing_keys=existing)
    assert sorted(to_delete) == [("2", "3", "a"), ("2", "3", "b")]
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/asbuilt_depth_geocoder/test_segment_sync_plan.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implémenter `plan_segment_sync`, juste après `build_segment_halves`**

```python
def plan_segment_sync(fresh, existing_keys):
    """Separe les moities fraichement calculees en (a upsert, a supprimer).

    ``fresh`` : liste de SegmentHalf issue de build_segment_halves (cet appel).
    ``existing_keys`` : cles (point_a_intervention_id, point_b_intervention_id,
    half) actuellement en base. Fonction PURE. L'upsert est TOUJOURS rejoue pour
    toute cle de ``fresh`` (idempotent cote SQL via ON CONFLICT DO UPDATE) ; la
    suppression ne vise QUE les cles presentes en base mais absentes de
    ``fresh`` (segments devenus obsoletes — point re-geocode ailleurs, etc.).
    """
    fresh_keys = {
        (h.point_a_intervention_id, h.point_b_intervention_id, h.half) for h in fresh
    }
    to_delete = sorted(existing_keys - fresh_keys)
    return list(fresh), to_delete
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/asbuilt_depth_geocoder/test_segment_sync_plan.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Ajouter le paramètre `OUTPUT_SEGMENTS` dans `initAlgorithm`**

```python
            self.addParameter(
                QgsProcessingParameterFeatureSink(
                    self.OUTPUT_SEGMENTS,
                    self.tr("Segments d'axe de rue (optionnel)"),
                    type=QgsProcessing.TypeVectorLine,
                    optional=True,
                )
            )
```

(Attribut de classe `OUTPUT_SEGMENTS = "OUTPUT_SEGMENTS"` à ajouter à côté de `OUTPUT`.)

- [ ] **Step 6: Implémenter `_sync_segments`, orchestration complète**

```python
        SEGMENTS_TABLE_SCHEMA = "public"
        SEGMENTS_TABLE_NAME = "geofiber_asbuilt_depth_segments"

        _SEGMENT_FIELD_SPECS = [
            ("point_a_intervention_id", QVariant.String),
            ("point_b_intervention_id", QVariant.String),
            ("half", QVariant.String),
            ("depth_category", QVariant.String),
            ("is_long", QVariant.Bool),
            ("length_m", QVariant.Double),
            ("road_key", QVariant.String),
        ]

        def _sync_segments(self, feedback):
            """Recalcule et resynchronise integralement les segments d'axe de rue.

            Relit TOUT public.geofiber_asbuilt_depth_points (pas seulement le lot de
            ce run — cf. spec §4 "synchro complete"), localise chaque point valide sur
            son axe de rue, reconstruit les moities via build_segment_halves, puis
            upsert + supprime les orphelins dans public.geofiber_asbuilt_depth_segments.
            Best-effort : si _locate_points_on_road signale une erreur de connexion,
            AUCUNE suppression n'est jouee (cf. Review Focus - ne pas purger sur un
            recalcul non fiable), seul l'upsert du lot obtenu est tente.
            """
            points_layer = self._open_be_points_layer(feedback)
            if points_layer is None:
                return []

            rows = []
            for feat in points_layer.getFeatures():
                category = feat["depth_category"]
                if category == "manquante" or not category:
                    continue
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                pt = geom.asPoint()
                rows.append({
                    "intervention_id": feat["intervention_id"],
                    "depth_category": category,
                    "address_raw": feat["address_raw"],
                    "x": pt.x(), "y": pt.y(),
                })

            locations, road_extents, had_connection_error = self._locate_points_on_road(
                rows, feedback
            )
            fresh = build_segment_halves(locations, road_extents)

            segments_layer = self._open_be_layer(
                self.SEGMENTS_TABLE_SCHEMA, self.SEGMENTS_TABLE_NAME,
                BE_GEOM_COLUMN, QgsWkbTypes.LineString, feedback,
            )
            if segments_layer is None:
                return fresh

            existing_keys = set()
            for feat in segments_layer.getFeatures():
                existing_keys.add((
                    feat["point_a_intervention_id"],
                    feat["point_b_intervention_id"],
                    feat["half"],
                ))
            to_upsert, to_delete = plan_segment_sync(fresh, existing_keys)
            if had_connection_error:
                to_delete = []
                feedback.pushWarning(
                    "Localisation partiellement en echec — purge des segments "
                    "obsoletes desactivee par prudence pour ce run."
                )

            fields = segments_layer.fields()
            inserted = updated = failed = 0
            for half in to_upsert:
                key_expr = (
                    f"{QgsExpression.quotedColumnRef('point_a_intervention_id')} = "
                    f"{QgsExpression.quotedValue(half.point_a_intervention_id)} AND "
                    f"{QgsExpression.quotedColumnRef('point_b_intervention_id')} = "
                    f"{QgsExpression.quotedValue(half.point_b_intervention_id)} AND "
                    f"{QgsExpression.quotedColumnRef('half')} = "
                    f"{QgsExpression.quotedValue(half.half)}"
                )
                request = QgsFeatureRequest()
                request.setFilterExpression(key_expr)
                existing = list(segments_layer.getFeatures(request))
                geom = QgsGeometry.fromPolylineXY([
                    QgsPointXY(half.start_x, half.start_y),
                    QgsPointXY(half.end_x, half.end_y),
                ])
                values = {
                    "point_a_intervention_id": half.point_a_intervention_id,
                    "point_b_intervention_id": half.point_b_intervention_id,
                    "half": half.half,
                    "depth_category": half.depth_category,
                    "is_long": half.is_long,
                    "length_m": half.length_m,
                    "road_key": half.road_key,
                }
                segments_layer.startEditing()
                ok = False
                try:
                    if existing:
                        fid = existing[0].id()
                        attr_map = {fields.indexOf(k): v for k, v in values.items()}
                        ok = segments_layer.changeAttributeValues(fid, attr_map)
                        ok = segments_layer.changeGeometry(fid, geom) and ok
                    else:
                        feat = QgsFeature(fields)
                        for k, v in values.items():
                            feat.setAttribute(k, v)
                        feat.setGeometry(geom)
                        ok = segments_layer.addFeature(feat)
                    ok = ok and segments_layer.commitChanges()
                except Exception as exc:
                    feedback.reportError(f"Echec upsert segment {key_expr} : {exc}", fatalError=False)
                    ok = False
                if ok:
                    updated += 1 if existing else 0
                    inserted += 0 if existing else 1
                else:
                    failed += 1
                    segments_layer.rollBack()

            deleted = 0
            for point_a, point_b, half_name in to_delete:
                key_expr = (
                    f"{QgsExpression.quotedColumnRef('point_a_intervention_id')} = "
                    f"{QgsExpression.quotedValue(point_a)} AND "
                    f"{QgsExpression.quotedColumnRef('point_b_intervention_id')} = "
                    f"{QgsExpression.quotedValue(point_b)} AND "
                    f"{QgsExpression.quotedColumnRef('half')} = "
                    f"{QgsExpression.quotedValue(half_name)}"
                )
                request = QgsFeatureRequest()
                request.setFilterExpression(key_expr)
                ids = [f.id() for f in segments_layer.getFeatures(request)]
                if not ids:
                    continue
                segments_layer.startEditing()
                if segments_layer.deleteFeatures(ids) and segments_layer.commitChanges():
                    deleted += 1
                else:
                    segments_layer.rollBack()

            feedback.pushInfo(
                f"Segments : {inserted} creee(s), {updated} mise(s) a jour, "
                f"{deleted} supprimee(s) (orphelins), {failed} echec(s)."
            )
            _apply_segments_style(segments_layer, feedback)
            _sync_style_to_db(
                segments_layer, "depth_segments",
                "Style segments d'axe de rue As-Built — géré par geocode_asbuilt_depth, ne pas éditer manuellement.",
                feedback,
            )
            return fresh
```

- [ ] **Step 7: Ajouter `_apply_segments_style` (même patron que `_apply_depth_style`, source de vérité = `style/depth_segments.qml`)**

```python
    def _depth_segments_style_qml_path(profile_dir):
        candidates = []
        if profile_dir:
            candidates.append(
                os.path.join(profile_dir, "resource_sharing", "asbuilt_depth_geocoder",
                              "style", "depth_segments.qml")
            )
        candidates.append(
            os.path.join(os.path.dirname(__file__), "..", "style", "depth_segments.qml")
        )
        for path in candidates:
            if path and os.path.isfile(path):
                return path
        return None

    def _apply_segments_style(layer, feedback=None) -> bool:
        try:
            profile_dir = QgsApplication.qgisSettingsDirPath()
        except Exception:
            profile_dir = None
        qml_path = _depth_segments_style_qml_path(profile_dir)
        if qml_path is not None:
            try:
                loaded = _named_style_loaded_ok(layer.loadNamedStyle(qml_path))
            except Exception as exc:
                loaded = False
                if feedback is not None:
                    feedback.pushInfo(f"Style segments non charge ({exc}).")
            if loaded:
                return True
        if feedback is not None:
            feedback.pushInfo("Style segments : repli sur un renderer categorise minimal.")
        categories = []
        for value, color in DEPTH_COLORS.items():
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.LineGeometry)
            symbol.setColor(QColor(color))
            categories.append(QgsRendererCategory(value, symbol, DEPTH_CATEGORY_LABELS.get(value, value)))
        layer.setRenderer(QgsCategorizedSymbolRenderer("depth_category", categories))
        return False
```

(`_depth_style_qml_path`/`_named_style_loaded_ok` existent déjà pour `depth_category.qml` — même mécanisme de résolution de chemin, dupliqué ici pour `depth_segments.qml` en suivant le même nom de fichier voisin.)

- [ ] **Step 8: Créer `style/depth_segments.qml`**

Renderer catégorisé QGIS sur `depth_category` (4 valeurs : manquante/rouge/orange/vert — `manquante` n'apparaîtra jamais en pratique puisque filtrée avant localisation, mais gardée pour cohérence visuelle avec `depth_category.qml`), ligne pleine par défaut, avec une **règle** supplémentaire (le renderer catégorisé QGIS seul ne gère pas de pointillé conditionnel — utiliser un `RuleRenderer` à la place, même structure que `depth_category.qml` d'origine avant simplification) : pour chaque catégorie, une sous-règle `"is_long" = false` (ligne pleine, `penstyle: solid`) et une sous-règle `"is_long" = true` (`penstyle: dash`), même couleur. Construire ce fichier en dupliquant la structure `<renderer-v2 type="RuleRenderer">` de `depth_category.qml` (Task 3 Step 5) : remplacer chaque `<rule filter="&quot;depth_category&quot; = 'X'">` unique par 2 règles filles (`... AND "is_long" = false` / `... AND "is_long" = true`), symbole `Line` (pas `Marker`), `penstyle` différent entre les deux.

- [ ] **Step 9: Appeler `_sync_segments` dans `processAlgorithm` et charger `OUTPUT_SEGMENTS` si demandé**

Après l'appel à `self._upsert_ungeocoded_records(ungeocoded, feedback)` :

```python
                if push_to_be:
                    fresh_segments = self._sync_segments(feedback)
                    # Sink optionnel : QgsProcessingParameterFeatureSink(optional=True) est
                    # absent de `parameters` (ou vaut None) si l'utilisateur ne l'a pas
                    # renseigne — meme idiome que SUMMARY/UNGEOCODED (QgsProcessingParameterFileDestination
                    # optional=True) deja dans ce fichier, adapte au sink.
                    if parameters.get(self.OUTPUT_SEGMENTS):
                        seg_sink, seg_dest = self.parameterAsSink(
                            parameters, self.OUTPUT_SEGMENTS, context,
                            _build_segment_output_fields(), QgsWkbTypes.LineString,
                            QgsCoordinateReferenceSystem(OUTPUT_CRS),
                        )
                        for half in fresh_segments:
                            geom = QgsGeometry.fromPolylineXY([
                                QgsPointXY(half.start_x, half.start_y),
                                QgsPointXY(half.end_x, half.end_y),
                            ])
                            feat = QgsFeature(_build_segment_output_fields())
                            feat.setGeometry(geom)
                            for name in ("point_a_intervention_id", "point_b_intervention_id",
                                         "half", "depth_category", "is_long", "length_m", "road_key"):
                                feat.setAttribute(name, getattr(half, name))
                            seg_sink.addFeature(feat, QgsFeatureSink.FastInsert)
                        outputs[self.OUTPUT_SEGMENTS] = seg_dest
```

Ajouter le helper `_build_segment_output_fields()` (même patron que `_build_output_fields`, à partir de `_SEGMENT_FIELD_SPECS`).

- [ ] **Step 10: Commit**

```bash
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py \
        collections/asbuilt_depth_geocoder/style/depth_segments.qml
git commit -m "feat(asbuilt): resynchro complete des segments (upsert + purge orphelins), couche OUTPUT_SEGMENTS"
```

---

## Task 9: Publication (metadata.ini, push, rebuild zip)

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/metadata.ini`

**Interfaces:** Aucune — publication uniquement.

- [ ] **Step 1: Enregistrer la collection dans `metadata.ini`** (actuellement absente — trouvé pendant le brainstorming : le zip est servi mais invisible dans le catalogue Resource Sharing)

```ini
[general]
collections=sketchy_sketches,cadastral_style,constructel_svg,merge_gpkg_by_jms,asbuilt_depth_geocoder

[asbuilt_depth_geocoder]
name=Géocodeur As-Built (profondeur de pose)
author=Equipe SIG Constructel
email=sig@constructel.fr
tags=processing, geocodage, as-built, profondeur, segments, constructel
description=Geocode les rapports As-Built GeoFiber, categorise par profondeur de pose (rouge/orange/vert) et genere les segments d'axe de rue entre points consecutifs.
qgis_minimum_version=3.28
qgis_maximum_version=3.99
```

- [ ] **Step 2: Lancer toute la suite pytest locale une dernière fois**

Run: `cd ~/projects/qgis_repo/resource-repo-work && python -m pytest tests/ -v`
Expected: tous les tests des Tasks 3/6/7/8 PASS (les tests sont hors `collections/`, donc non zippés — cf. note Task 3).

- [ ] **Step 3: Commit et push**

```bash
cd ~/projects/qgis_repo/resource-repo-work
git add metadata.ini
git commit -m "chore(asbuilt): enregistrement dans metadata.ini (collection jusqu'ici absente du catalogue)"
git push
```

- [ ] **Step 4: Vérifier le rebuild automatique du zip côté serveur, et la présence de la nouvelle collection dans le catalogue servi**

```bash
ssh sdadmin@192.168.160.31 "python3 -m zipfile -l ~/projects/qgis_repo/resource-repo/collections/asbuilt_depth_geocoder.zip"
ssh sdadmin@192.168.160.31 "grep -A2 '^\[general\]' ~/projects/qgis_repo/resource-repo/metadata.ini"
```

Expected : le zip contient `processing/geocode_asbuilt_depth.py`, `style/depth_category.qml`, `style/depth_segments.qml` ; `metadata.ini` liste `asbuilt_depth_geocoder`.

- [ ] **Step 5: Test d'intégration réel (hors pytest — nécessite QGIS Desktop)**

Depuis un poste QGIS connecté à `be` : lancer l'algorithme sur un petit dossier de test, `PUSH_TO_BE` activé, vérifier :
- `public.geofiber_asbuilt_depth_points` et `public.geofiber_asbuilt_ungeocoded` à jour
- `public.geofiber_asbuilt_depth_segments` contient les paires attendues + segments de bout de route
- `layer_styles` contient une entrée `useasdefault=true` pour les 2 couches (`SELECT f_table_name, stylename, useasdefault FROM layer_styles WHERE f_table_schema='public' AND f_table_name IN ('geofiber_asbuilt_depth_points','geofiber_asbuilt_depth_segments');`)
- Relancer l'algorithme SANS nouvelle donnée : le nombre de lignes dans `geofiber_asbuilt_depth_segments` ne change pas (idempotence, Review Focus item 4)

---

## Notes d'exécution

- Task 1 (Farois) et Tasks 2-9 (qgis_repo) sont indépendantes jusqu'à la vérification finale (Task 9 Step 5) : la migration 432 peut être appliquée en base de test dès que committée, sans attendre le script.
- Le déploiement de la migration 432 en PRODUCTION (application effective sur `farois_ftth`) est HORS PÉRIMÈTRE de ce plan — suit la routine habituelle (`farois-prod-deploy-routine`, cf. mémoire), sur décision explicite de Simon.
- Tasks 3 à 8 modifient le même fichier (`geocode_asbuilt_depth.py`) séquentiellement dans le même clone `resource-repo-work/` — exécuter dans l'ordre, ne pas paralléliser.
