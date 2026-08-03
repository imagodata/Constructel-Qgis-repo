# Message copiable des adresses non géocodées

**Date** : 2026-08-03
**Statut** : proposé
**Périmètre** : `resource-repo/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`
(collection QGIS Resource Sharing, dépôt bare `resource-repo.git`)

## Contexte

Le script produit déjà, en sortie optionnelle (`UNGEOCODED`), un CSV listant les
adresses non géocodées (`build_ungeocoded_rows`, 7 colonnes : `intervention_id`,
`work_order`, `address_raw`, `postal_code`, `place`, `geocode_query`,
`source_message`). Ce CSV vise la traçabilité complète et la retouche manuelle
avant un nouveau passage — il faut renseigner un chemin de fichier avant le run,
puis l'ouvrir après.

Besoin distinct exprimé : à la fin de chaque run, pouvoir copier-coller directement
depuis le journal Processing (sans configurer ni ouvrir de fichier) un message
prêt à envoyer listant les adresses en échec — que ce soit pour relance interne ou
pour demander une correction au sous-traitant Go Fiber. Le message doit rester
factuel et neutre pour convenir aux deux usages.

## Objectif

Après la boucle de géocodage, afficher dans le journal Processing (`feedback.pushInfo`)
un bloc de texte listant chaque adresse non géocodée, sous une forme compacte et
directement copiable-collable. N'affecte aucune sortie existante (`OUTPUT`,
`SUMMARY`, `UNGEOCODED` restent inchangés).

## Design

### Nouvelle fonction pure `build_ungeocoded_message`

À côté de `build_ungeocoded_rows` (même fichier, même section), sans dépendance
PyQGIS, testable via pytest :

```python
def build_ungeocoded_message(entries) -> str:
    """Message compact, pret a copier-coller, listant les adresses non geocodees.

    ``entries`` : meme forme que build_ungeocoded_rows -- iterable de
    (InterventionRecord, query). Fonction pure, testable hors QGIS.
    """
```

- `entries` vide → retourne `"Aucune adresse non géocodée."`
- `entries` non vide → une ligne d'en-tête avec le compte, puis une ligne par
  intervention :

```
6 adresse(s) non géocodée(s) à vérifier :
- WO-1234 (Intervention 45277503) : Aachener Straße 14 Bte:2/1, 4780 Saint-Vith
- WO-5678 (Intervention 49103453) : Am Sonnenhang 3, 4780 Sankt V
```

- Contenu par ligne : `work_order`, `intervention`, puis l'adresse reconstituée à
  partir de `rec.address` + `rec.postal_code` + `rec.place` (champs bruts du
  rapport source — **pas** la requête Nominatim qui a échoué, réservée au CSV pour
  qui veut creuser la cause de l'échec).
- Un champ vide (`postal_code` ou `place` absent) est omis proprement de la ligne
  reconstituée plutôt que de laisser un espace/virgule orpheline.

### Point d'accroche dans `processAlgorithm`

Un seul appel, juste avant `return outputs` (après le bloc CSV `UNGEOCODED`
existant, pour ne rien changer à son comportement) :

```python
feedback.pushInfo(build_ungeocoded_message(ungeocoded))
```

`ungeocoded` est la liste déjà accumulée pendant la boucle de géocodage (même
source que celle utilisée pour le CSV) — aucune nouvelle collecte de données.
Toujours affiché, y compris quand la liste est vide (ligne "Aucune adresse non
géocodée.") : confirmation explicite que rien n'est à signaler, cohérent avec les
autres lignes de synthèse déjà affichées en fin de run (`pushInfo` du compte
géocodées/échecs/ignorées).

## Compatibilité / risques

- Aucun changement de comportement sur `OUTPUT`, `SUMMARY`, `UNGEOCODED` (CSV) ou
  l'upsert vers `be` — purement additif, une ligne de log supplémentaire.
- Pas de paramètre ni de sortie Processing supplémentaire à déclarer : rien à
  configurer avant un run, aucune migration pour les utilisateurs existants de la
  collection.

## Testing

- Pur (pytest, hors QGIS) : `build_ungeocoded_message()` sur liste vide, une
  entrée, plusieurs entrées, et une entrée avec `postal_code`/`place` vide(s).
- Manuel (QGIS, après implémentation) : lancer sur un rapport avec au moins une
  adresse non géocodable, vérifier que le bloc apparaît dans le journal Processing
  avec le bon format et se sélectionne/copie proprement.

## Hors périmètre

- Toute modification du CSV `UNGEOCODED` existant ou de son format.
- Envoi automatique du message (email, etc.) — reste un copier-coller manuel.

## Extension (demandée après la première publication, 2026.08.03.4)

Simon a demandé que le message apparaisse aussi à deux autres endroits, en plus de sa position en fin de run :

1. **Journal Processing, juste après la ligne de résumé existante** (`"{n_ok} interventions géocodées, {n_nf} échecs, {n_skip} déjà présentes ignorées."`) — le bloc `build_ungeocoded_message` y est affiché une seconde fois, en plus de sa position actuelle en fin de run (pas un déplacement — les deux occurrences coexistent).
2. **Table de synthèse xlsx (SUMMARY)** — nouvelle feuille "Adresses non géocodées" dans le même classeur, réutilisant `build_ungeocoded_rows(ungeocoded)` (déjà existant, sert aussi au CSV optionnel `UNGEOCODED`) pour son contenu. Ne remplace ni ne modifie les deux feuilles existantes ("Synthèse par ville", "Pourcentages"), ni le chargement en couche (qui ne cible que la feuille pivot).
