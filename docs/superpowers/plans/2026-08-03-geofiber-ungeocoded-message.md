# Message copiable des adresses non géocodées — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Afficher, à la fin de chaque run de `geocode_asbuilt_depth.py`, un bloc de texte dans le journal Processing listant les adresses non géocodées sous une forme compacte, prête à copier-coller et envoyer.

**Architecture:** Une fonction pure `build_ungeocoded_message(entries)` (même fichier, même section que `build_ungeocoded_rows`, aucune dépendance PyQGIS) construit le texte à partir de la liste `ungeocoded` déjà accumulée pendant la boucle de géocodage. Un seul appel `feedback.pushInfo(...)` dans `processAlgorithm`, juste avant `return outputs`.

**Tech Stack:** Python stdlib uniquement (pas de nouvelle dépendance).

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-08-03-geofiber-ungeocoded-message-design.md` (qgis_repo, commit `934bd18`).
- Collection Resource Sharing mono-fichier (`geocode_asbuilt_depth.py`) : aucun nouveau fichier n'est ajouté sous `collections/asbuilt_depth_geocoder/` dans ce qui est publié/zippé.
- Le fichier de test créé pour ce chantier n'est **volontairement pas commité** (contrainte mono-fichier de la collection) — même convention déjà appliquée et validée par Simon sur le chantier `2026-08-03-geofiber-depth-upsert` (Task 1 : disparaît après le `rm -rf` de fin de tâche, aucune couverture de régression permanente pour les fonctions pures de ce fichier — décision déjà actée, ne pas la remettre en question ici).
- Aucun changement de comportement sur `OUTPUT`, `SUMMARY`, ou le CSV `UNGEOCODED` existant : purement additif.
- `qgis_minimum_version=3.16` déjà déclaré dans `metadata.ini` — cette tâche n'utilise que la stdlib Python, aucun risque de dépassement de ce plancher.

---

### Task 1: `build_ungeocoded_message` + câblage dans `processAlgorithm`

**Files:**
- Create (temporaire, non commité — exclu volontairement de la publication) : `~/projects/qgis_repo/resource-repo-work/tests/asbuilt_depth_geocoder/test_ungeocoded_message.py`
- Modify: `~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`

**Interfaces:**
- Produces: `build_ungeocoded_message(entries: Iterable[tuple[InterventionRecord, str]]) -> str` — sans dépendance PyQGIS, aucune tâche suivante n'en dépend (dernière tâche de ce plan).

- [ ] **Step 1: Cloner le dépôt bare dans un espace de travail dédié**

```bash
ssh sdadmin@192.168.160.31 '
rm -rf ~/projects/qgis_repo/resource-repo-work
git clone ~/projects/qgis_repo/resource-repo.git ~/projects/qgis_repo/resource-repo-work
'
```

Résultat attendu : `Cloning into '"'"'/home/sdadmin/projects/qgis_repo/resource-repo-work'"'"'...` puis `done.`. Le `HEAD` du clone doit être `252d29f` (dernière version publiée, `2026.08.03.3`) — vérifier avec `git log --oneline -1`.

- [ ] **Step 2: Écrire le test (doit échouer — `build_ungeocoded_message` n'existe pas encore)**

Créer `~/projects/qgis_repo/resource-repo-work/tests/asbuilt_depth_geocoder/test_ungeocoded_message.py` :

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
build_ungeocoded_message = geocode_asbuilt_depth.build_ungeocoded_message


class BuildUngeocodedMessageTests(unittest.TestCase):
    def test_empty_entries_returns_no_failures_line(self):
        self.assertEqual(
            build_ungeocoded_message([]),
            "Aucune adresse non géocodée.",
        )

    def test_single_entry_full_fields(self):
        rec = InterventionRecord(
            work_order="WO-1234",
            intervention="45277503",
            address="Aachener Straße 14 Bte:2/1",
            postal_code="4780",
            place="Saint-Vith",
            depth_raw="60",
            source_message="rapport_test.msg",
        )
        message = build_ungeocoded_message([(rec, "query en echec")])
        self.assertEqual(
            message,
            "1 adresse(s) non géocodée(s) à vérifier :\n"
            "- WO-1234 (Intervention 45277503) : "
            "Aachener Straße 14 Bte:2/1, 4780 Saint-Vith",
        )

    def test_multiple_entries_counted_and_ordered(self):
        rec1 = InterventionRecord(
            work_order="WO-1", intervention="111", address="Rue A 1",
            postal_code="1000", place="Bruxelles", depth_raw="50",
            source_message="rapport_test.msg",
        )
        rec2 = InterventionRecord(
            work_order="WO-2", intervention="222", address="Rue B 2",
            postal_code="4000", place="Liège", depth_raw="60",
            source_message="rapport_test.msg",
        )
        message = build_ungeocoded_message([(rec1, "q1"), (rec2, "q2")])
        lines = message.splitlines()
        self.assertEqual(lines[0], "2 adresse(s) non géocodée(s) à vérifier :")
        self.assertEqual(
            lines[1], "- WO-1 (Intervention 111) : Rue A 1, 1000 Bruxelles"
        )
        self.assertEqual(
            lines[2], "- WO-2 (Intervention 222) : Rue B 2, 4000 Liège"
        )

    def test_missing_postal_code_and_place_omitted_cleanly(self):
        rec = InterventionRecord(
            work_order="WO-9", intervention="999", address="Rue Sans Ville 3",
            postal_code="", place="", depth_raw="60",
            source_message="rapport_test.msg",
        )
        message = build_ungeocoded_message([(rec, "q")])
        self.assertEqual(
            message,
            "1 adresse(s) non géocodée(s) à vérifier :\n"
            "- WO-9 (Intervention 999) : Rue Sans Ville 3",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Lancer le test, vérifier qu'il échoue**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && python3 -m unittest tests/asbuilt_depth_geocoder/test_ungeocoded_message.py -v'
```

Résultat attendu : erreur — `module 'geocode_asbuilt_depth' has no attribute 'build_ungeocoded_message'` (`AttributeError`).

- [ ] **Step 4: Implémenter `build_ungeocoded_message` (fonction pure)**

Dans `collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`, remplacer :

```python
    return rows


def _build_attribute_values(rec, thresholds, query, status, hit):
```

par :

```python
    return rows


def build_ungeocoded_message(entries) -> str:
    """Message compact, pret a copier-coller, listant les adresses non geocodees.

    ``entries`` : meme forme que build_ungeocoded_rows -- iterable de
    (InterventionRecord, query). Fonction pure, testable hors QGIS.
    """
    if not entries:
        return "Aucune adresse non géocodée."
    lines = [f"{len(entries)} adresse(s) non géocodée(s) à vérifier :"]
    for rec, _query in entries:
        location = " ".join(
            part for part in (rec.postal_code, rec.place) if part.strip()
        )
        addr_parts = [part for part in (rec.address, location) if part.strip()]
        addr = ", ".join(addr_parts)
        lines.append(f"- {rec.work_order} (Intervention {rec.intervention}) : {addr}")
    return "\n".join(lines)


def _build_attribute_values(rec, thresholds, query, status, hit):
```

(Le remplacement n'ajoute que la nouvelle fonction entre `build_ungeocoded_rows` et `_build_attribute_values` — les deux fonctions existantes ne changent pas.)

- [ ] **Step 5: Relancer le test, vérifier qu'il passe**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && python3 -m unittest tests/asbuilt_depth_geocoder/test_ungeocoded_message.py -v'
```

Résultat attendu : `Ran 4 tests ... OK`.

- [ ] **Step 6: Câbler l'appel dans `processAlgorithm`**

Remplacer :

```python
            # --- CSV des adresses non géocodées (optionnel) --------------
            if ungeocoded_path:
                written = self._write_ungeocoded_csv(
                    ungeocoded_path, ungeocoded, feedback
                )
                if written:
                    outputs[self.UNGEOCODED] = ungeocoded_path
            return outputs
```

par :

```python
            # --- CSV des adresses non géocodées (optionnel) --------------
            if ungeocoded_path:
                written = self._write_ungeocoded_csv(
                    ungeocoded_path, ungeocoded, feedback
                )
                if written:
                    outputs[self.UNGEOCODED] = ungeocoded_path

            # --- message copiable des adresses non géocodées ------------
            feedback.pushInfo(build_ungeocoded_message(ungeocoded))
            return outputs
```

- [ ] **Step 7: Vérifier la syntaxe de l'ensemble du fichier**

```bash
ssh sdadmin@192.168.160.31 'python3 -m py_compile ~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py && echo OK'
```

Résultat attendu : `OK`.

- [ ] **Step 8: Relancer le test une dernière fois (non-régression après le câblage)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && python3 -m unittest tests/asbuilt_depth_geocoder/test_ungeocoded_message.py -v'
```

Résultat attendu : `Ran 4 tests ... OK` (le câblage dans `processAlgorithm`, bloc `if HAS_QGIS:`, ne touche pas la fonction pure testée ici).

- [ ] **Step 9: Vérifier le diff avant commit**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && git diff -- collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py'
```

Doit correspondre exactement aux deux remplacements des Steps 4 et 6 — rien d'autre.

- [ ] **Step 10: Commit local (pas de push — le clone reste local à ce stade)**

```bash
ssh sdadmin@192.168.160.31 '
cd ~/projects/qgis_repo/resource-repo-work
git add collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py
git commit -m "feat(asbuilt_depth_geocoder): message copiable des adresses non geocodees en fin de run"
'
```

---

### Task 2: Publier sur `resource-repo.git`

**Files:**
- Modify: `~/projects/qgis_repo/resource-repo-work/metadata.ini`
- Push: `~/projects/qgis_repo/resource-repo.git` (bare, branche `master`)

**Interfaces:**
- Consumes: le commit local de Task 1 dans `resource-repo-work`.
- Produces: nouvelle version publiée, servie automatiquement via le hook `post-receive`.

- [ ] **Step 1: Bumper la version de la collection**

Dans `~/projects/qgis_repo/resource-repo-work/metadata.ini`, section `[asbuilt_depth_geocoder]`, remplacer :

```ini
version=2026.08.03.3
```

par :

```ini
version=2026.08.03.4
```

- [ ] **Step 2: Commit local du bump de version**

```bash
ssh sdadmin@192.168.160.31 '
cd ~/projects/qgis_repo/resource-repo-work
git add metadata.ini
git commit -m "chore(asbuilt_depth_geocoder): bump version pour detection maj (message non geocodees, 2026.08.03.4)"
'
```

- [ ] **Step 3: Pousser sur le dépôt bare**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo/resource-repo-work && git push origin master'
```

Résultat attendu : le push réussit, suivi des lignes `[post-receive] ...` du hook indiquant la resynchronisation de `resource-repo/` et la reconstruction des zips.

- [ ] **Step 4: Vérifier que le dossier servi est bien synchronisé**

```bash
ssh sdadmin@192.168.160.31 '
diff ~/projects/qgis_repo/resource-repo-work/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py \
     ~/projects/qgis_repo/resource-repo/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py \
  && echo IDENTIQUE
awk "/\[asbuilt_depth_geocoder\]/,0" ~/projects/qgis_repo/resource-repo/metadata.ini | grep "^version="
python3 -c "
import zipfile
z = zipfile.ZipFile(\"/home/sdadmin/projects/qgis_repo/resource-repo/collections/asbuilt_depth_geocoder.zip\")
content = z.read(\"processing/geocode_asbuilt_depth.py\").decode(\"utf-8\")
print(\"build_ungeocoded_message_count:\", content.count(\"def build_ungeocoded_message\"))
"
'
```

Résultat attendu : `IDENTIQUE`, `version=2026.08.03.4`, `build_ungeocoded_message_count: 1`.

- [ ] **Step 5: Nettoyer l'espace de travail**

```bash
ssh sdadmin@192.168.160.31 'rm -rf ~/projects/qgis_repo/resource-repo-work'
```

Note : ce `rm -rf` ne cible QUE `resource-repo-work` (le clone de travail jetable), jamais `resource-repo` (le dossier servi) ni `resource-repo.git` (le dépôt bare).

---

### Task 3: Vérification manuelle dans QGIS (humain — non exécutable par un agent)

- [ ] **Step 1:** Dans QGIS, *Extensions > Resource Sharing*, vérifier qu'une mise à jour est proposée pour « As-Built Depth Geocoder (Go Fiber) » (version `2026.08.03.4`) et l'installer.
- [ ] **Step 2:** Lancer l'algorithme sur un dossier de rapports contenant au moins une adresse non géocodable.
- [ ] **Step 3:** Vérifier dans le journal Processing, en fin de run, la présence du bloc `N adresse(s) non géocodée(s) à vérifier :` suivi d'une ligne par adresse en échec, au format `- WorkOrder (Intervention ID) : adresse, CP ville`.
- [ ] **Step 4:** Sélectionner ce bloc dans le journal et le coller dans un éditeur de texte quelconque, vérifier que le rendu est propre (pas de caractères d'échappement, pas de ligne coupée).
- [ ] **Step 5:** Relancer sur un dossier sans aucune adresse en échec, vérifier que la ligne `Aucune adresse non géocodée.` apparaît bien.
