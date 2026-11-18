# Constructel Bridge — écran d'accueil v2 : barre latérale, presets cumulables, multi-opérateur, couches communes seules

Date : 2026-11-18 · Base : Constructel Bridge 1.9.0 (`origin/main` 98a2984) · Branche : `feat/bridge-accueil-v2`
Précédent : `2026-11-12-bridge-accueil-operateur-design.md` (écran d'accueil 1.9.0, dont celui-ci reprend les contraintes et les règles d'opérateur).

## 1. Intention

L'écran d'accueil 1.9.0 (`bridge_home.py`) impose de choisir un opérateur avant de voir la moindre couche, et ses modèles de sélection incluent tous l'infrastructure de l'opérateur. Charger « seulement OSIRIS » (ou seulement le cadastre, le chantier…) oblige à passer en sélection manuelle et à tout décocher à la main. Simon juge aussi l'écran confus (ordre des étapes), l'arbre des couches illisible (libellés `Structures (wyre.structures)`, tout déplié) et l'aspect brut (boutons et tuiles Qt par défaut).

La v2 rationalise l'écran : on peut charger des couches communes sans opérateur, les presets se combinent, l'arbre est allégé, et l'écran devient une fenêtre à barre latérale qui intègre Projet enregistré, Check-in et Diagnostic au lieu d'ouvrir des fenêtres séparées. Le setup (assistant de check-in) ne se rejoue plus tout seul après chaque mise à jour du plugin.

Ce document est le **chantier 1** d'un découpage validé par Simon le 18/11 :

1. **Écran v2 du plugin** (ce document).
2. **Partage et ressources Constructel** : FilterMate (favoris partagés via le dépôt git du VPS), Resource Sharing (collections de scripts, styles, SVG), éventuel partage des « Mes presets » — cadrage séparé. Le chantier 1 n'en fait que **l'affichage d'état** dans la page Check-in.
3. **Projets QGIS partageables en base** : migration Farois (table dédiée, droits utilisateur / équipe), neutralisation des macros à l'ouverture (raison d'être de la mig 539), login nominatif, enregistrement par le plugin — cadrage séparé. Le chantier 1 réserve seulement la place dans la page Projets.

## 2. Objectifs

- Charger un ou plusieurs blocs de couches communes **sans opérateur** (ex. OSIRIS seul).
- Charger les couches de **plusieurs opérateurs en un seul geste** (ex. zones MRO/POP de Wyre et d'Orange).
- Presets **cumulables** : toutes les combinaisons de blocs sans sélection manuelle.
- Un ordre de lecture évident : Périmètre → Presets → Couches → Charger.
- Un arbre lisible (libellés courts, compteurs, groupes repliés).
- Une seule fenêtre : barre latérale + pages intégrées.
- L'assistant de check-in ne s'ouvre automatiquement qu'au premier setup.

## 3. Non-objectifs

- Pas de changement du catalogue de couches (`LAYER_CATALOG`), des styles QML, des relations ni du SQL côté Farois.
- Pas de refonte du contenu de l'assistant de check-in (ses 6 pages restent ce qu'elles sont) ni des contrôles du Diagnostic.
- Pas de partage des « Mes presets » entre postes ou utilisateurs (chantier 2).
- Pas de configuration nouvelle de FilterMate ni de Resource Sharing au-delà de ce que fait déjà l'assistant (chantier 2).
- Pas d'enregistrement de projet en base par l'utilisateur (chantier 3).
- Pas de changement des règles d'opérateurs utilisables, du suffixe ni de la réorganisation des projets 1.8 (spec du 12/11 § 6.2 à 6.5) : on les reprend telles quelles.

## 4. Anti-objectifs (échec même si « ça marche »)

- L'assistant de check-in réapparaît après une mise à jour chez quelqu'un qui l'a déjà fait.
- Un chargement « commun seul » écrit un opérateur dans l'identité du projet (`bridge/operator`), ou en casse la relecture / la recréation des relations.
- L'écran devient illisible en thème sombre de QGIS (couleurs codées en dur).
- La fenêtre déborde de l'écran d'un portable (1366×768) dans l'état par défaut.
- Une couche déjà chargée redevient cochable ou rechargée en double (règle T9-c2b perdue).

## 5. Contraintes

Reprises de la spec du 12/11 § 5 :

- QGIS **3.28 minimum** (Python 3.9) à 4.99 (Qt5/Qt6) ; style d'enums existant (`Qt.CheckState.Checked`, `QDialog.DialogCode.Accepted`…).
- Tous les textes en **FR / EN / PT** (`i18n/translations.py`), un appel `tr` littéral par clé (K11, relevé par `test_bridge18_i18n.py` / `test_bridge19_i18n.py`).
- Tests pytest sur stubs (`plugin-repo/packages/constructel_bridge_tests/`) : la suite existante reste verte ; la logique sans Qt reste dans un module testable sans QGIS (patron `bridge_home_model.py`).
- Sécurité serveur inchangée : opérateurs utilisables = scopes OPÉRATEUR (`public.current_gis_operator_codes`, rôles `ftth_op_<schema>`).
- Publication par `release.py <version> --cloture`. **Le working tree `main` de `~/projects/qgis_repo` sur le VPS sert le dépôt de plugins aux utilisateurs** : tout le développement se fait dans `.worktrees/feat-bridge-accueil-v2`, la publication est un geste séparé, sur GO de Simon.

## 6. Ce qui a été décidé avec Simon

### 6.1 Fenêtre : barre latérale + pages intégrées

```
┌──────────────────┬──────────────────────────────────────────────┐
│ ⬇ Charger        │ Déjà dans le projet : ✓ Wyre · 11 couches    │
│ 📂 Projets       │ ┌ 1 PÉRIMÈTRE ─────────────────────────────┐ │
│ ✔ Check-in ⚠ 1   │ │ [☑Wyre] [☑Orange] [Aucun]                │ │
│ 🩺 Diagnostic    │ └──────────────────────────────────────────┘ │
│                  │ ┌ 2 PRESETS ──────── Enregistrer ma sélection┐│
│                  │ │ Mes presets : [Coordo Ixelles] [Permis]  │ │
│                  │ │ [☑ Zones][☐ Réseau][☐ Chantier][☑OSIRIS] │ │
│                  │ │ [☐ Cadastre UrbIS][☐ Urbanisme]          │ │
│                  │ └──────────────────────────────────────────┘ │
│                  │ ┌ 3 COUCHES ───── Afficher toutes les couches┐│
│ ● s.ducournau    │ │ ▸ ☑ Zones [Wyre] [Orange]  4/4           │ │
│   Bruxelles      │ │ ▸ ☑ OSIRIS  7/7  …                       │ │
│ FR · EN · PT     │ └──────────────────────────────────────────┘ │
│ [Se connecter]   │ ▸ Options             20 couches  [ Charger ]│
└──────────────────┴──────────────────────────────────────────────┘
```

- Barre latérale (choix A+B+C des maquettes) : **Charger les couches**, **Projet enregistré**, **Check-in**, **Diagnostic**. Chaque entrée affiche sa page dans la zone principale (**pages intégrées**, pas de fenêtre séparée).
- Les 4 tuiles du bas et l'en-tête de connexion de la 1.9.0 disparaissent.

### 6.2 Page « Charger les couches » : étapes numérotées en une colonne

1. **Périmètre** : un bouton par opérateur utilisable, **plusieurs cochables à la fois**, plus **« Aucun — couches communes »**, exclusif. Simon a choisi de **garder cette étape** au-dessus des cartes (variante A) plutôt que de mettre l'opérateur dans une carte.
2. **Presets** : **cartes cumulables** (on coche / décoche chacune) avec titre et description courte de ce qu'elles chargent. Deux cartes **opérateur**, appliquées à chaque opérateur coché : **Zones** (MRO, POP, distribution, drop) et **Réseau** (structures, câbles, conduites, tranchées, points de demande) — découpage A choisi contre une carte Infra unique et contre un découpage en 4. Quatre cartes **communes** : **Chantier**, **OSIRIS**, **Cadastre UrbIS**, **Urbanisme**. « Urbanisme » ne contient plus implicitement le cadastre.
3. **Couches** : l'arbre, pour ajuster, avec un groupe par opérateur coché.
- **Multi-opérateur** : cas de référence « zones MRO/POP de Wyre et d'Orange » = cocher Wyre et Orange, carte Zones seule, Charger. Un seul clic enchaîne les opérateurs ; les couches communes ne sont chargées qu'une fois. Le suffixe opérateur est imposé dès deux opérateurs entre ceux du projet et ceux cochés (règle `suffix_state` existante).
- Bouton principal : **« Charger »**, libellé fixe (plus de « Initialiser · Wyre » / « Ajouter les couches · Wyre »).

### 6.3 Extras retenus

- **Mes presets** : « Enregistrer ma sélection… » nomme la sélection courante ; elle réapparaît en pastille au-dessus des cartes, sur ce poste.
- **Dernier choix retenu** : à l'ouverture, on recoche ce qui a été chargé la dernière fois sur ce poste (périmètre, cartes, ajustements).
- **Masquer « Référence »** : le groupe technique (`docs_elements`, `v_form_lists`) sort de l'arbre ; il reste chargé automatiquement comme aujourd'hui (`v_form_lists` toujours incluse).
- **Couches « expert »** : les couches rarement utiles sont masquées derrière « Afficher toutes les couches ».

### 6.4 Page « Check-in » : état + actions + assistant à la demande

- La page montre l'état : profil (login, e-mail), extensions recommandées (actives / à mettre à jour / absentes, avec boutons « Mettre à jour » / « Installer » par ligne), partages (Resource Sharing, FilterMate) configurés ou non.
- Un bouton **« Refaire le check-in complet »** lance l'assistant existant (`OnboardingWizard`) **dans la page**.
- **Ressources Constructel (affichage d'état seulement, le fond relève du chantier 2)** : dépôt Resource Sharing « Constructel » configuré ou non, collections du dépôt (`resource-repo/metadata.ini` : as-built, layers_to_atlas, fusion GPKG JMS, style cadastral, SVG, sketches) installées / à jour / absentes ; FilterMate : dépôt de favoris « Constructel » configuré ou non. Une action « Configurer » réutilise le code existant de l'assistant (`_configure_resource_sharing`, `_configure_filtermate_sharing`).

### 6.5 Le setup ne se rejoue pas s'il est déjà fait

- Aujourd'hui `bridge_plugin.py` (≈ l. 1097-1101) efface `constructel_bridge/onboarding_done` à chaque installation / mise à jour, d'où l'assistant qui revient à chaque version.
- v2 : une mise à jour **n'efface plus** cet indicateur. L'assistant ne s'ouvre automatiquement que pour un **nouvel utilisateur** ou si le setup n'a **jamais été terminé** sur ce poste.
- S'il y a quelque chose à faire après une mise à jour (extension recommandée absente ou en retard), c'est signalé par une **pastille sur « Check-in »** dans la barre latérale (« ⚠ 1 »), sans ouvrir de fenêtre.

## 7. Propositions de Claude reprises sans objection (à confirmer en relisant)

- **Lien périmètre ↔ cartes opérateur** : « Aucun » grise et décoche Zones et Réseau ; cocher un opérateur les réactive (état repris du dernier choix). Décocher les deux cartes avec un opérateur coché ne change pas le périmètre (on charge alors seulement des communes ; aucun opérateur n'est inscrit au projet, cf. § 8.2). Décocher le dernier opérateur coché bascule sur « Aucun ».
- **Cartes selon le contexte** : toutes les cartes restent visibles dans les deux modes ; seules les cartes opérateur sont grisées en « Aucun ». Coché/décoché d'une carte = coche/décoche ses couches dans l'arbre ; une carte dont l'arbre est partiellement coché s'affiche en état intermédiaire.
- **Arbre allégé** : libellé court seul (« Zones gelées »), `schema.table` en infobulle ; compteur par groupe (« OSIRIS 7/7 », « Zones [Wyre] 4/4 ») ou « déjà chargé » ; groupes entièrement chargés repliés ; badge opérateur / « commun » conservé.
- **Couches expert** proposées : `subducts` (déjà exclue de tous les modèles) et `planning_facades` (sans géométrie). Liste en constante, facile à ajuster.
- **Options** repliées sous la page : fonds de plan (arbre actuel), « Appliquer les styles de la base », suffixe opérateur. La case du suffixe est masquée en « Aucun ».
- **Résumé** à gauche du bouton : « 20 couches · 2 fonds de plan » (ce qui va être ajouté, hors couches déjà chargées).
- **Projet enregistré** : liste des projets en base groupés par opérateur, champ de recherche, bouton « Ouvrir » (remplace le `QInputDialog` de `_on_load_project`). La fenêtre se ferme avant l'ouverture, comme en 1.9.0 (D11). La page est construite pour accueillir plus tard une section « Mes projets / partagés » (chantier 3), sans rien en afficher en v2.
- **Diagnostic** : le contenu actuel de `DiagnosticDialog` (lignes de contrôle, actions, sonde réseau asynchrone) hébergé dans la page, avec « Relancer ».
- **Langue** : sélecteur FR · EN · PT en bas de la barre latérale, pas de page dédiée ; changer de langue redessine la fenêtre.
- **Hors connexion** : état et bouton « Se connecter » en bas de la barre ; les pages qui demandent la base l'indiquent (règles § 6.6 de la spec du 12/11 inchangées ; Diagnostic reste utilisable hors connexion).
- **Après un chargement réussi** la fenêtre se ferme ; sinon elle reste ouverte et se met à jour (règle T9-c1b inchangée).
- **Thème** : couleurs dérivées de la palette Qt de QGIS (`palette().highlight()`, etc.) ; aucune couleur de fond codée en dur.
- **Version** : 2.0.0 (changement visible de tout l'écran d'accueil).

## 8. Points techniques à traiter (pistes, pas une solution imposée)

### 8.1 Presets

- Remplacer `TEMPLATES` (6 modèles « Infra + X ») par des **blocs** : clé → ensemble de clés du catalogue. Proposition :
  - `zones` (opérateur) = zone_mro, zone_pop, zone_distribution, zone_drop ;
  - `reseau` (opérateur) = structures, ducts, cables, trench_segments, demand_points (+ `docs_elements` dont les relations visent ces couches) ;
  - `chantier` = groupe Chantier + `duct_progress` (l'actuel « Infra + Chantier » l'y ajoutait ; c'est une couche opérateur : à charger pour chaque opérateur coché) ;
  - `osiris`, `cadastre` (4 couches WFS UrbIS), `urbanisme` (`wfs_protection`, `wfs_heritage`).
  - ⚠ `topo_violations` est cité dans `_INFRA_BASE` mais absent de `LAYER_CATALOG` : vérifier et nettoyer.
- « Mes presets » et « Dernier choix » : stockés dans `QgsSettings` (clé sous `constructel_bridge/`), format sérialisé simple (JSON : nom, périmètre, clés de couches). Un preset qui cite un opérateur non utilisable sur la session se charge en « Aucun » ou est grisé (au builder de trancher, en le signalant).

### 8.2 Chargement sans opérateur

- `actions.load` / `_load_operator_layers` / `init_project` prennent aujourd'hui un `OperatorInfo` obligatoire. `stamp_project` n'est appelé que si une couche opérateur est ajoutée ou présente (T2-c3) et `_stamp_version` marque le projet : un chargement commun seul est donc déjà compatible avec l'identité du projet. Il faut permettre `operator=None` (ou un sentinelle) sur toute la chaîne : `catalog_for`, `_reorganize_legacy_project`, `LAST_OPERATOR_KEY` (ne pas l'écraser), `_detect_existing_layers`.
- Vérifier `ensure_relations` et `_on_project_read` sur un projet sans aucune couche opérateur.
- **Multi-opérateur** : appeler la chaîne de chargement une fois par opérateur coché (ordre des boutons), les communes avec le premier seulement ; un échec sur un opérateur n'annule pas les autres et est signalé. `LAST_OPERATOR_KEY` devient une liste (ou une clé nouvelle) ; « Dernier choix » restaure la liste. Les règles d'opérateurs utilisables, de suffixe et de réorganisation 1.8 (spec du 12/11 § 6.2-6.5) s'appliquent à chacun.

### 8.3 Fenêtre

- `HomeDialog` → `QListWidget` (ou boutons) + `QStackedWidget`. Un module par page (ex. `bridge_home_load.py`, `bridge_home_projects.py`, `bridge_home_checkin.py`, `bridge_home_diagnostic.py`), la logique d'état dans `bridge_home_model.py` (étendue : périmètre « Aucun », état des cartes, pastille Check-in).
- `LayerSelectionWidget` évolue (cartes, arbre allégé, masquage Référence / expert). Son contrat T9-c2b (déjà chargé = grisé, décoché, jamais rendu par `selected_layers()`) est conservé.
- `DiagnosticDialog` : extraire le contenu dans un `QWidget` réutilisable ; garder la fin de session propre de la sonde réseau à la fermeture de la fenêtre (cf. correctif 1.9.0 « écran d'accueil et Diagnostic détruits après fermeture »).
- `OnboardingWizard` (`QWizard`) : l'héberger dans la page (un `QWizard` est un `QDialog`, il peut s'insérer avec `Qt.WindowType.Widget`) ou le relancer en modal depuis la page si l'intégration pose problème — **le signaler** dans ce cas.
- État du Check-in : réutiliser `PluginSummary` (`bridge_diagnostic`) et `RECOMMENDED_PLUGINS` / `install_or_activate_plugin` (`bridge_onboarding`).

### 8.4 Setup

- Supprimer l'effacement de `onboarding_done` sur changement de version ; garder la mise à jour de `plugin_version`.
- Calculer la pastille à partir de `PluginSummary.updates` + extensions recommandées absentes.
- Les gardes existantes sur l'ouverture automatique (I-3 « jamais deux fois », I13 « pas sous l'écran de démarrage ») restent.

## 9. Laissé au builder

- Découpage exact des modules, noms de clés i18n, noms de clés `QgsSettings`.
- Rendu précis des cartes (QFrame cliquable, QToolButton checkable…) tant qu'il reste lisible en thème clair et sombre.
- Taille par défaut de la fenêtre (contrainte : 1366×768 sans débordement).
- Ordre des tâches et stratégie de tests, dans le respect du patron « logique sans Qt testée sans QGIS ».

## 10. Approches envisagées

- **Retenue — refonte de `HomeDialog` en Qt code** (barre latérale + pages empilées), en gardant le découpage modèle sans Qt / dessin. Cohérente avec le reste du plugin et ses tests sur stubs.
- Écartée — **fichiers Qt Designer (`.ui`)** : aucun dans le plugin, casserait le patron de tests.
- Écartée — **interface web embarquée (QWebEngine)** : moteur non fiable dans les QGIS Windows des utilisateurs.
- Pour les presets, Simon a choisi les **cartes cumulables** contre des presets par métier et contre la liste actuelle corrigée ; pour le périmètre, **l'étape conservée** (A) contre l'opérateur dans la carte Infrastructure (B) ; pour l'infra, **Zones / Réseau** contre une carte unique et contre 4 cartes.
