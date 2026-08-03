# Upsert profondeur de pose (geofiber_asbuilt_depth_points) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire écrire (upsert) `geocode_asbuilt_depth.py` dans `public.geofiber_asbuilt_depth_points` via la connexion QGIS `be`, sans toucher à la sortie `OUTPUT` existante, puis publier la nouvelle version de la collection sur `resource-repo.git`.

**Architecture:** Une fonction pure `_build_attribute_values()` (extraite de l'actuel `_build_feature()`) fournit le dict de colonnes ; une nouvelle méthode d'instance `_upsert_geocoded_records()` résout la connexion QGIS `be` via `QgsProviderRegistry`, ouvre `public.geofiber_asbuilt_depth_points` en `QgsVectorLayer`, et upserte chaque intervention géocodée avec succès dans son propre cycle `startEditing()`/`commitChanges()` (best-effort ligne par ligne). Le tout est câblé dans `processAlgorithm()` juste après la boucle de géocodage existante.

**Tech Stack:** PyQGIS (QGIS ≥ 3.16), Python stdlib, `unittest` (pas de nouvelle dépendance ajoutée).

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-08-03-geofiber-depth-upsert-design.md` (qgis_repo, commit `5fc330e`).
- Collection Resource Sharing = mono-fichier (`geocode_asbuilt_depth.py`) : aucun nouveau fichier n'est ajouté sous `collections/asbuilt_depth_geocoder/` dans ce qui est publié/zippé.
- Aucun secret lu ni dupliqué dans le script : la connexion `be` est résolue uniquement via l'API QGIS (`QgsProviderRegistry`), jamais via `credentials.json` ni le code du plugin `constructel_bridge`.
- Seules les interventions géocodées avec succès (déjà écrites dans `OUTPUT`) sont poussées en base ; les échecs restent uniquement dans `UNGEOCODED`.
- Conflit sur `intervention_id` → écrasement complet de toutes les colonnes (sauf `intervention_id` lui-même, `created_at`, `updated_at` gérés par la base).
- Un cycle `startEditing()`/`commitChanges()` par intervention (pas un edit buffer unique pour tout le lot) : best-effort, une ligne en échec n'empêche pas les autres.
- Connexion `be` absente/hôte injoignable → avertissement (`feedback.pushWarning`), section DB sautée, `OUTPUT` reste produit normalement.
- Publication : push sur `resource-repo.git` (branche `master`) ; `version=` dans `metadata.ini` doit être bumpé (convention `AAAA.MM.JJ.N`, actuellement `2026.07.15.5`) — c'est ce qui déclenche la détection de mise à jour côté client QGIS Resource Sharing. Le hook `post-receive` resynchronise automatiquement `resource-repo/` (servi en HTTP) et reconstruit le zip.
- `qgis_minimum_version=3.16` / `qgis_maximum_version=3.99` déjà déclarés dans `metadata.ini` — ne pas introduire d'API PyQGIS plus récente que ce plancher.

---

### Task 1: Extraire `_build_attribute_values` (fonction pure) de `_build_feature`

**Files:**
- Create (temporaire, non commité — exclu volontairement de la publication) : `~/projects/qgis_repo/resource-repo-work/tests/asbuilt_depth_geocoder/test_upsert_attributes.py`
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py` (clone créé à l'étape 1 de cette tâche)

**Interfaces:**
- Produces: `_build_attribute_values(rec: InterventionRecord, thresholds: DepthThresholds, query: str, status: str, hit: NominatimHit) -> dict` — sans dépendance PyQGIS, clés = noms des colonnes de `public.geofiber_asbuilt_depth_points` (hors `geom`/`created_at`/`updated_at`) : `intervention_id`, `work_order`, `address_raw`, `postal_code`, `place`, `depth_cm`, `depth_category`, `geocode_query`, `geocode_status`, `source_message`.
- Produces: `_build_feature(fields: "QgsFields", values: dict, point: "QgsPointXY") -> "QgsFeature"` — signature changée (anciennement `(fields, rec, thresholds, query, status, point, hit)`), consommé par Task 3.

- [ ] **Step 1: Cloner le dépôt bare dans un espace de travail dédié**

```bash
ssh sdadmin@192.168.160.31 '
rm -rf ~/projects/qgis_repo/resource-repo-work
git clone ~/projects/qgis_repo/resource-repo.git ~/projects/qgis_repo/resource-repo-work
'
```

Résultat attendu : `Cloning into '"'"'/home/sdadmin/projects/qgis_repo/resource-repo-work'"'"'...` puis `done.`

- [ ] **Step 2: Écrire le test (doit échouer — `_build_attribute_values` n'existe pas encore)**

Créer `~/projects/qgis_repo/resource-repo-work/tests/asbuilt_depth_geocoder/test_upsert_attributes.py` :

```python
import importlib.util
import pathlib
import unittest

_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections" / "asbuilt_depth_geocoder" / "processing"
    / "geocode_asbuilt_depth.py"
)
_spec = importlib.util.spec_from_file_location("geocode_asbuilt_depth", _MODULE_PATH)
geocode_asbuilt_depth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(geocode_asbuilt_depth)

InterventionRecord = geocode_asbuilt_depth.InterventionRecord
DepthThresholds = geocode_asbuilt_depth.DepthThresholds
NominatimHit = geocode_asbuilt_depth.NominatimHit
_build_attribute_values = geocode_asbuilt_depth._build_attribute_values


class BuildAttributeValuesTests(unittest.TestCase):
    def test_uses_nominatim_postcode_and_city_when_present(self):
        rec = InterventionRecord(
            work_order="WO-1",
            intervention="INT-001",
            address="Rue Test 1",
            postal_code="1000",
            place="Bruxelles",
            depth_raw="0.65",
            source_message="rapport_test.msg",
        )
        hit = NominatimHit(lat=50.85, lon=4.35, postcode="1000", city="Bruxelles")
        values = _build_attribute_values(
            rec, DepthThresholds(), "query used", "ok", hit
        )
        self.assertEqual(
            values,
            {
                "intervention_id": "INT-001",
                "work_order": "WO-1",
                "address_raw": "Rue Test 1",
                "postal_code": "1000",
                "place": "Bruxelles",
                "depth_cm": 65.0,
                "depth_category": "vert",
                "geocode_query": "query used",
                "geocode_status": "ok",
                "source_message": "rapport_test.msg",
            },
        )

    def test_falls_back_to_normalized_report_fields_when_nominatim_silent(self):
        rec = InterventionRecord(
            work_order="WO-2",
            intervention="INT-002",
            address="Rue Test 2",
            postal_code=" 1050 ",
            place="ixelles/elsene",
            depth_raw="45",
            source_message="rapport_test.msg",
        )
        hit = NominatimHit(lat=50.83, lon=4.37, postcode="", city="")
        values = _build_attribute_values(rec, DepthThresholds(), "query 2", "ok", hit)
        self.assertEqual(values["postal_code"], "1050")
        self.assertEqual(values["place"], "Ixelles/Elsene")
        self.assertEqual(values["depth_cm"], 45.0)
        self.assertEqual(values["depth_category"], "rouge")

    def test_unparsable_depth_is_missing_category(self):
        rec = InterventionRecord(
            work_order="WO-3",
            intervention="INT-003",
            address="Rue Test 3",
            postal_code="1200",
            place="Woluwe",
            depth_raw="",
            source_message="rapport_test.msg",
        )
        hit = NominatimHit(lat=50.84, lon=4.44, postcode="1200", city="Woluwe")
        values = _build_attribute_values(rec, DepthThresholds(), "query 3", "ok", hit)
        self.assertIsNone(values["depth_cm"])
        self.assertEqual(values["depth_category"], "manquante")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Lancer le test, vérifier qu'il échoue**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && python3 -m unittest tests/asbuilt_depth_geocoder/test_upsert_attributes.py -v'
```

Résultat attendu : erreur — `module 'geocode_asbuilt_depth' has no attribute '_build_attribute_values'` (`AttributeError`).

- [ ] **Step 4: Implémenter `_build_attribute_values` (fonction pure)**

Dans `collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`, juste avant le bloc `if HAS_QGIS:` (actuellement précédé du commentaire `# Wrapper QGIS Processing — fin, orchestration uniquement`), insérer :

```python
def _build_attribute_values(rec, thresholds, query, status, hit):
    """Valeurs d'attributs pures dérivées d'une intervention géocodée.

    Aucune dépendance PyQGIS — réutilisée à la fois pour la ``QgsFeature``
    OUTPUT et pour l'upsert vers ``public.geofiber_asbuilt_depth_points``
    (connexion ``be``).
    """
    depth_cm = parse_depth_cm(rec.depth_raw)
    return {
        "intervention_id": rec.intervention,
        "work_order": rec.work_order,
        "address_raw": rec.address,
        # PRIORITÉ au détail d'adresse structuré Nominatim (fiable,
        # indépendant d'un désalignement de colonnes dans le rapport
        # source — cf. incident colonnes PostalCode/Place garbled) ;
        # repli sur la normalisation du champ brut sinon.
        "postal_code": hit.postcode or normalize_postal_code(rec.postal_code),
        "place": hit.city or normalize_place(rec.place),
        "depth_cm": depth_cm,
        "depth_category": categorize_depth(depth_cm, thresholds),
        "geocode_query": query,
        "geocode_status": status,
        "source_message": rec.source_message,
    }
```

- [ ] **Step 5: Refactoriser `_build_feature` pour consommer ce dict**

Remplacer (dans le bloc `if HAS_QGIS:`) :

```python
    def _build_feature(fields, rec, thresholds, query, status, point, hit):
        depth_cm = parse_depth_cm(rec.depth_raw)
        feat = QgsFeature(fields)
        feat.setGeometry(QgsGeometry.fromPointXY(point))
        feat.setAttribute("intervention_id", rec.intervention)
        feat.setAttribute("work_order", rec.work_order)
        feat.setAttribute("address_raw", rec.address)
        # postal_code/place : PRIORITÉ au détail d'adresse structuré renvoyé
        # par Nominatim (source fiable, indépendante d'un éventuel
        # désalignement de colonnes dans le rapport source — cf. incident
        # colonnes PostalCode/Place garbled). Repli sur la normalisation du
        # champ brut du rapport (normalize_postal_code/normalize_place) si
        # Nominatim n'a pas fourni ce détail pour ce résultat précis. Le
        # géocodage lui-même (build_geocode_query, plus haut dans le
        # pipeline) continue d'utiliser rec.postal_code/rec.place BRUTS,
        # volontairement inchangé.
        feat.setAttribute(
            "postal_code", hit.postcode or normalize_postal_code(rec.postal_code)
        )
        feat.setAttribute("place", hit.city or normalize_place(rec.place))
        feat.setAttribute("depth_cm", depth_cm if depth_cm is not None else None)
        feat.setAttribute("depth_category", categorize_depth(depth_cm, thresholds))
        feat.setAttribute("geocode_query", query)
        feat.setAttribute("geocode_status", status)
        feat.setAttribute("source_message", rec.source_message)
        return feat
```

par :

```python
    def _build_feature(fields, values, point):
        feat = QgsFeature(fields)
        feat.setGeometry(QgsGeometry.fromPointXY(point))
        for name, value in values.items():
            feat.setAttribute(name, value)
        return feat
```

- [ ] **Step 6: Mettre à jour l'unique site d'appel de `_build_feature`**

Dans la boucle de géocodage (`processAlgorithm`), remplacer :

```python
                else:
                    point = transform.transform(QgsPointXY(hit.lon, hit.lat))
                    feature = _build_feature(
                        fields, rec, thresholds, query, "ok", point, hit
                    )
                    sink.addFeature(feature, QgsFeatureSink.FastInsert)
```

par :

```python
                else:
                    point = transform.transform(QgsPointXY(hit.lon, hit.lat))
                    values = _build_attribute_values(rec, thresholds, query, "ok", hit)
                    feature = _build_feature(fields, values, point)
                    sink.addFeature(feature, QgsFeatureSink.FastInsert)
```

(Le reste du bloc — `known_ids.add(...)`, `place_key = ...`, etc. — ne change pas dans cette tâche.)

- [ ] **Step 7: Relancer le test, vérifier qu'il passe**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && python3 -m unittest tests/asbuilt_depth_geocoder/test_upsert_attributes.py -v'
```

Résultat attendu : `Ran 3 tests ... OK`.

- [ ] **Step 8: Vérifier la syntaxe de l'ensemble du fichier**

```bash
ssh sdadmin@192.168.160.31 'python3 -m py_compile ~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py && echo OK'
```

Résultat attendu : `OK` (le bloc `if HAS_QGIS:` est syntaxiquement vérifié même si non exécuté ici, faute de PyQGIS sur ce serveur).

- [ ] **Step 9: Commit local (pas de push — le clone reste local à ce stade)**

```bash
ssh sdadmin@192.168.160.31 '
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py
git commit -m "refactor(asbuilt_depth_geocoder): extrait _build_attribute_values (pur) de _build_feature"
'
```

---

### Task 2: Résolution de la connexion `be` + méthode d'upsert

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`

**Interfaces:**
- Consumes: rien de Task 1 directement (méthode indépendante, appelée par Task 3).
- Produces: `GeocodeAsBuiltDepthAlgorithm._upsert_geocoded_records(self, records: list[tuple[dict, "QgsPointXY"]], feedback) -> None` — consommé par Task 3. `records` = liste de `(values, point)` où `values` est le dict produit par `_build_attribute_values` (Task 1) et `point` un `QgsPointXY` déjà reprojeté en `OUTPUT_CRS`.
- Nouvelles constantes module : `BE_CONNECTION_NAME = "be"`, `BE_TABLE_SCHEMA = "public"`, `BE_TABLE_NAME = "geofiber_asbuilt_depth_points"`.

Pas de test automatisé possible pour cette tâche (code 100% PyQGIS, non exécutable hors QGIS) : vérification = compilation Python (Step 4) ; vérification fonctionnelle réelle = Task 5 (manuel, QGIS).

- [ ] **Step 1: Ajouter les imports PyQGIS manquants**

Remplacer le bloc d'import (déjà modifié seulement en apparence par Task 1 — celui-ci ajoute 3 entrées, en respectant l'ordre alphabétique existant) :

```python
    from qgis.core import (
        QgsApplication,
        QgsCategorizedSymbolRenderer,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsFeature,
        QgsFeatureSink,
        QgsField,
        QgsFields,
        QgsGeometry,
        QgsPointXY,
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingException,
        QgsProcessingLayerPostProcessorInterface,
        QgsProcessingParameterFeatureSink,
        QgsProcessingParameterFeatureSource,
        QgsProcessingParameterFile,
        QgsProcessingParameterFileDestination,
        QgsProcessingParameterNumber,
        QgsProcessingParameterString,
        QgsProcessingUtils,
        QgsProject,
        QgsRendererCategory,
        QgsSymbol,
        QgsVectorLayer,
        QgsWkbTypes,
    )
```

par :

```python
    from qgis.core import (
        QgsApplication,
        QgsCategorizedSymbolRenderer,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsExpression,
        QgsFeature,
        QgsFeatureRequest,
        QgsFeatureSink,
        QgsField,
        QgsFields,
        QgsGeometry,
        QgsPointXY,
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingException,
        QgsProcessingLayerPostProcessorInterface,
        QgsProcessingParameterFeatureSink,
        QgsProcessingParameterFeatureSource,
        QgsProcessingParameterFile,
        QgsProcessingParameterFileDestination,
        QgsProcessingParameterNumber,
        QgsProcessingParameterString,
        QgsProcessingUtils,
        QgsProject,
        QgsProviderRegistry,
        QgsRendererCategory,
        QgsSymbol,
        QgsVectorLayer,
        QgsWkbTypes,
    )
```

- [ ] **Step 2: Ajouter les constantes de connexion/table**

Remplacer :

```python
if HAS_QGIS:

    OUTPUT_CRS = "EPSG:31370"

    _FIELD_SPECS = [
```

par :

```python
if HAS_QGIS:

    OUTPUT_CRS = "EPSG:31370"
    BE_CONNECTION_NAME = "be"
    BE_TABLE_SCHEMA = "public"
    BE_TABLE_NAME = "geofiber_asbuilt_depth_points"

    _FIELD_SPECS = [
```

- [ ] **Step 3: Ajouter la méthode `_upsert_geocoded_records`**

Dans la section « helpers d'instance » de `GeocodeAsBuiltDepthAlgorithm`, juste après `_write_ungeocoded_csv` (avant `def _load_summary_layer`), insérer :

```python
        def _upsert_geocoded_records(self, records, feedback):
            """Upsert les interventions geocodees dans public.geofiber_asbuilt_depth_points via be.

            Best-effort ligne par ligne : la connexion be indisponible ou l'echec
            d'une ligne individuelle degradent (avertissement) sans jamais faire
            echouer le run — le geocodage/OUTPUT ont deja eu lieu et ne doivent
            pas etre perdus pour un probleme d'ecriture en base. Cf. spec
            docs/superpowers/specs/2026-08-03-geofiber-depth-upsert-design.md.
            """
            if not records:
                feedback.pushInfo("Base 'be' : aucune intervention geocodee a pousser.")
                return
            md = QgsProviderRegistry.instance().providerMetadata("postgres")
            be_connection = md.findConnection(BE_CONNECTION_NAME) if md else None
            if be_connection is None:
                feedback.pushWarning(
                    "Connexion QGIS 'be' introuvable — installez/activez "
                    "Constructel Bridge pour pousser les interventions en base. "
                    f"OUTPUT reste disponible, rien n'a ete ecrit dans "
                    f"{BE_TABLE_SCHEMA}.{BE_TABLE_NAME}."
                )
                return
            try:
                uri = be_connection.tableUri(BE_TABLE_SCHEMA, BE_TABLE_NAME)
                layer = QgsVectorLayer(uri, BE_TABLE_NAME, "postgres")
            except Exception as exc:
                feedback.pushWarning(
                    f"Connexion a {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} via 'be' "
                    f"impossible ({exc}) — rien n'a ete ecrit en base."
                )
                return
            if not layer.isValid():
                feedback.pushWarning(
                    f"Couche {BE_TABLE_SCHEMA}.{BE_TABLE_NAME} invalide via la "
                    "connexion 'be' — rien n'a ete ecrit en base."
                )
                return

            fields = layer.fields()
            id_field = QgsExpression.quotedColumnRef("intervention_id")
            inserted = updated = failed = 0
            for values, point in records:
                intervention_id = values["intervention_id"]
                id_value = QgsExpression.quotedValue(intervention_id)
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
                        layer.changeAttributeValues(fid, attr_map)
                        layer.changeGeometry(fid, QgsGeometry.fromPointXY(point))
                    else:
                        feat = QgsFeature(fields)
                        for name, value in values.items():
                            feat.setAttribute(name, value)
                        feat.setGeometry(QgsGeometry.fromPointXY(point))
                        layer.addFeature(feat)
                    ok = layer.commitChanges()
                except Exception as exc:
                    feedback.reportError(
                        f"Echec upsert intervention {intervention_id} : {exc}",
                        fatalError=False,
                    )
                    ok = False

                if ok:
                    if existing:
                        updated += 1
                    else:
                        inserted += 1
                else:
                    failed += 1
                    for err in layer.commitErrors():
                        feedback.reportError(
                            f"Intervention {intervention_id} : {err}",
                            fatalError=False,
                        )
                    layer.rollBack()

            feedback.pushInfo(
                f"Base 'be' : {inserted} creee(s), {updated} mise(s) a jour, "
                f"{failed} echec(s) sur {len(records)} intervention(s) geocodee(s)."
            )
```

- [ ] **Step 4: Vérifier la syntaxe**

```bash
ssh sdadmin@192.168.160.31 'python3 -m py_compile ~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py && echo OK'
```

Résultat attendu : `OK`.

- [ ] **Step 5: Relancer les tests de Task 1 (non-régression)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && python3 -m unittest tests/asbuilt_depth_geocoder/test_upsert_attributes.py -v'
```

Résultat attendu : `Ran 3 tests ... OK`.

- [ ] **Step 6: Commit local**

```bash
ssh sdadmin@192.168.160.31 '
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py
git commit -m "feat(asbuilt_depth_geocoder): resolution connexion be + upsert geofiber_asbuilt_depth_points"
'
```

---

### Task 3: Câbler l'upsert dans `processAlgorithm`

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`

**Interfaces:**
- Consumes: `_build_attribute_values` (Task 1), `_build_feature(fields, values, point)` (Task 1), `self._upsert_geocoded_records(records, feedback)` (Task 2).
- Produces: rien de nouveau consommé par une tâche suivante — dernière tâche de code de ce plan.

Pas de test automatisé (même raison que Task 2) : vérification = compilation + non-régression des tests Task 1 + Task 5 (manuel).

- [ ] **Step 1: Initialiser l'accumulateur avant la boucle de géocodage**

Remplacer :

```python
            # Adresses non géocodées accumulées pour l'export CSV optionnel
            # (cf. self.UNGEOCODED) : (InterventionRecord, requête en échec).
            ungeocoded: list[tuple[InterventionRecord, str]] = []
```

par :

```python
            # Adresses non géocodées accumulées pour l'export CSV optionnel
            # (cf. self.UNGEOCODED) : (InterventionRecord, requête en échec).
            ungeocoded: list[tuple[InterventionRecord, str]] = []
            # Interventions geocodees avec succes, pour l'upsert vers la
            # connexion 'be' (cf. self._upsert_geocoded_records) : (dict de
            # valeurs d'attributs, QgsPointXY reprojete en OUTPUT_CRS).
            geocoded_for_db: list[tuple[dict, "QgsPointXY"]] = []
```

- [ ] **Step 2: Accumuler chaque intervention géocodée avec succès**

Remplacer :

```python
                else:
                    point = transform.transform(QgsPointXY(hit.lon, hit.lat))
                    values = _build_attribute_values(rec, thresholds, query, "ok", hit)
                    feature = _build_feature(fields, values, point)
                    sink.addFeature(feature, QgsFeatureSink.FastInsert)
                    known_ids.add(rec.intervention)
```

par :

```python
                else:
                    point = transform.transform(QgsPointXY(hit.lon, hit.lat))
                    values = _build_attribute_values(rec, thresholds, query, "ok", hit)
                    feature = _build_feature(fields, values, point)
                    sink.addFeature(feature, QgsFeatureSink.FastInsert)
                    geocoded_for_db.append((values, point))
                    known_ids.add(rec.intervention)
```

- [ ] **Step 3: Appeler l'upsert après la boucle de géocodage**

Remplacer :

```python
            feedback.pushInfo(
                f"{n_ok} interventions géocodées, {n_nf} échecs, "
                f"{n_skip} déjà présentes ignorées."
            )

            # --- symbologie : deux mécanismes COMPLÉMENTAIRES ------------
```

par :

```python
            feedback.pushInfo(
                f"{n_ok} interventions géocodées, {n_nf} échecs, "
                f"{n_skip} déjà présentes ignorées."
            )

            self._upsert_geocoded_records(geocoded_for_db, feedback)

            # --- symbologie : deux mécanismes COMPLÉMENTAIRES ------------
```

- [ ] **Step 4: Vérifier la syntaxe**

```bash
ssh sdadmin@192.168.160.31 'python3 -m py_compile ~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py && echo OK'
```

Résultat attendu : `OK`.

- [ ] **Step 5: Relancer les tests de Task 1 (non-régression)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && python3 -m unittest tests/asbuilt_depth_geocoder/test_upsert_attributes.py -v'
```

Résultat attendu : `Ran 3 tests ... OK`.

- [ ] **Step 6: Commit local**

```bash
ssh sdadmin@192.168.160.31 '
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py
git commit -m "feat(asbuilt_depth_geocoder): pousse les interventions geocodees vers be en fin de run"
'
```

---

### Task 4: Publier sur `resource-repo.git`

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/metadata.ini`
- Push: `~/projects/qgis_repo/resource-repo.git` (bare, branche `master`)

**Interfaces:**
- Consumes: les 3 commits locaux de Task 1-3 dans `resource-repo-work`.
- Produces: nouvelle version publiée, servie automatiquement via le hook `post-receive` (aucune interface de code — dernière tâche de ce plan avant la vérification manuelle Task 5).

- [ ] **Step 1: Bumper la version de la collection**

Dans `~/projects/qgis_repo/resource-repo-work/metadata.ini`, section `[asbuilt_depth_geocoder]`, remplacer :

```ini
version=2026.07.15.5
```

par :

```ini
version=2026.08.03.1
```

- [ ] **Step 2: Commit local du bump de version**

```bash
ssh sdadmin@192.168.160.31 '
cd ~/projects/qgis_repo/resource-repo-work
git add metadata.ini
git commit -m "chore(asbuilt_depth_geocoder): bump version pour detection maj (upsert be, 2026.08.03.1)"
'
```

- [ ] **Step 3: Pousser sur le dépôt bare**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && git push origin master'
```

Résultat attendu : le push réussit (pas de rejet), suivi des lignes `[post-receive] ...` du hook indiquant la resynchronisation de `resource-repo/` et la reconstruction des zips.

- [ ] **Step 4: Vérifier que le dossier servi est bien synchronisé**

```bash
ssh sdadmin@192.168.160.31 '
diff ~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py \
     ~/projects/qgis_repo/resource-repo/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py \
  && echo IDENTIQUE
grep "^version=" ~/projects/qgis_repo/resource-repo/metadata.ini
unzip -p ~/projects/qgis_repo/resource-repo/collections/asbuilt_depth_geocoder.zip processing/geocode_asbuilt_depth.py | grep -c "_upsert_geocoded_records"
'
```

Résultat attendu : `IDENTIQUE`, `version=2026.08.03.1` (ligne isolée, pas de section spécifique attendue dans ce grep global — si plusieurs `version=` apparaissent dans le fichier, vérifier que celle de la section `[asbuilt_depth_geocoder]` a bien changé), et un compte `>= 1` pour `_upsert_geocoded_records` dans le zip reconstruit.

- [ ] **Step 5: Nettoyer l'espace de travail**

```bash
ssh sdadmin@192.168.160.31 'rm -rf ~/projects/qgis_repo/resource-repo-work'
```

---

### Task 5: Vérification manuelle dans QGIS (humain — non exécutable par un agent)

**Contexte :** cette tâche nécessite une session QGIS réelle avec le plugin `constructel_bridge` actif (connexion `be` configurée) et un accès réseau au serveur `192.168.160.31`. Aucun agent headless ne peut l'exécuter — à réaliser par Simon (ou toute personne disposant d'un poste QGIS sur le réseau interne Constructel).

- [ ] **Step 1:** Dans QGIS, *Extensions > Resource Sharing*, vérifier qu'une mise à jour est proposée pour « As-Built Depth Geocoder (Go Fiber) » (version `2026.08.03.1`) et l'installer.
- [ ] **Step 2:** Préparer un petit rapport de test (`.csv`, colonnes `WorkOrder;Intervention;Address;PostalCode;Place;<colonne profondeur>`) avec une ligne dont l'`Intervention` est un identifiant inédit (ex. `TEST-UPSERT-INSERT-1`).
- [ ] **Step 3:** Via `psql` (rôle `postgres`, cf. mémoire `wyre-db-psql-access`), insérer manuellement une ligne de test à mettre à jour :
  ```bash
  ssh sdadmin@192.168.160.31 '
  set -a; . ~/projects/Farois/docker/.env.secrets; set +a
  docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c \
    "INSERT INTO public.geofiber_asbuilt_depth_points (intervention_id, depth_cm) VALUES ('"'"'TEST-UPSERT-UPDATE-1'"'"', 10) ON CONFLICT (intervention_id) DO NOTHING;"
  '
  ```
  Résultat attendu : `INSERT 0 1` (ou pas d'erreur si déjà présente).
- [ ] **Step 4:** Ajouter au rapport de test une seconde ligne avec `Intervention = TEST-UPSERT-UPDATE-1` et une profondeur différente (ex. `75`).
- [ ] **Step 5:** Lancer l'algorithme *Géocoder rapport As-Built (.msg / .xlsx / .csv) par profondeur* sur ce dossier de test.
- [ ] **Step 6:** Dans le journal Processing, vérifier la ligne `Base 'be' : 1 creee(s), 1 mise(s) a jour, 0 echec(s) sur 2 intervention(s) geocodee(s).` (ou équivalent selon le nombre réel de lignes géocodées avec succès).
- [ ] **Step 7:** Vérifier en base :
  ```bash
  ssh sdadmin@192.168.160.31 '
  set -a; . ~/projects/Farois/docker/.env.secrets; set +a
  docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c \
    "SELECT intervention_id, depth_cm, (updated_at > created_at) AS updated_bumped FROM public.geofiber_asbuilt_depth_points WHERE intervention_id LIKE '"'"'TEST-UPSERT-%'"'"';"
  '
  ```
  Résultat attendu : `TEST-UPSERT-INSERT-1` présente avec la bonne profondeur ; `TEST-UPSERT-UPDATE-1` avec `depth_cm = 75` et `updated_bumped = t`.
- [ ] **Step 8:** Désactiver temporairement la connexion `be` (ou couper l'accès réseau à `192.168.160.31:5432` depuis le poste de test) et relancer l'algorithme sur un petit lot. Vérifier qu'`OUTPUT` est toujours produit et qu'un avertissement explicite (« Connexion QGIS 'be' introuvable... ») apparaît dans le journal, sans exception ni arrêt du run.
- [ ] **Step 9:** Nettoyer les lignes de test (rôle `postgres`, `bureau_etudes` n'a pas `DELETE`) :
  ```bash
  ssh sdadmin@192.168.160.31 '
  set -a; . ~/projects/Farois/docker/.env.secrets; set +a
  docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c \
    "DELETE FROM public.geofiber_asbuilt_depth_points WHERE intervention_id LIKE '"'"'TEST-UPSERT-%'"'"';"
  '
  ```
  Résultat attendu : `DELETE 2`.
