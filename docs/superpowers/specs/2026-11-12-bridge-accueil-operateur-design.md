# Constructel Bridge — écran d'accueil, choix d'opérateur et outils hors connexion

- **Date** : 2026-11-12
- **Statut** : proposé, à valider par Simon
- **Plugin** : `plugin-repo/packages/constructel_bridge` (base 1.8.4, cible **1.9.0**)
- **Maquette de référence** : `2026-11-12-bridge-accueil-operateur-maquette.html` (fragment HTML, version 3 validée en séance)

## 1. Intention

Aujourd'hui, le clic principal sur le bouton Constructel Bridge lance directement « Initialiser le projet ». Comme l'assistant d'accueil (onboarding) et le statut, il est refusé tant que QGIS n'est pas connecté à la base Farois (`conn.connect_first`). Un poste qui n'arrive pas à se connecter ne peut donc ni vérifier ses extensions, ni comprendre pourquoi la connexion échoue.

Côté données, Farois est passé au modèle **un schéma par opérateur** (`wyre`, `orange`, …, registre `ref.operateurs`), avec des **scopes OPÉRATEUR** par utilisateur (mig 530/537/541). Le plugin, lui, code en dur le schéma `wyre` dans `LAYER_CATALOG` : un utilisateur qui a Orange dans ses scopes ne peut pas charger l'infra Orange.

On veut un **écran d'accueil** derrière le clic principal, qui :

1. fonctionne **sans connexion** pour les outils du poste : check-in, diagnostic, langue ;
2. une fois connecté, permet de **charger les couches d'un opérateur de ses scopes**, un seul à la fois, puis d'en ajouter un deuxième ;
3. **conserve tel quel** le système de sélection actuel : modèles, arbre des couches de travail, fonds de plan raster, styles.

## 2. Objectifs

- **O1** : le clic principal ouvre l'écran d'accueil, connecté ou non.
- **O2** : sans connexion, le check-in, le diagnostic et la langue sont utilisables.
- **O3** : connecté, on choisit **un** opérateur parmi ceux de ses scopes, puis on charge ses couches avec la sélection actuelle.
- **O4** : on peut ensuite ajouter un deuxième opérateur (puis un troisième…) au même projet, sans dupliquer les couches communes.
- **O5** : dans le panneau Couches, chaque opérateur a son groupe racine à son nom. Le reste est dans un groupe **Commun**.
- **O6** : les garde-fous existants (lecture seule selon le périmètre, refus d'écriture traduits) s'appliquent à **tous** les schémas opérateurs chargés, pas seulement à `wyre`.

## 3. Non-objectifs

- Aucune modification côté serveur Farois (SQL, API). Le plugin s'appuie sur les fonctions existantes. Si un manque apparaît, on le signale, on ne le corrige pas dans ce chantier.
- Pas d'ouverture automatique de l'écran au démarrage de QGIS : **au clic seulement**.
- Pas de chargement de plusieurs opérateurs en une seule action.
- Pas de refonte du flux de connexion (login nominatif, mTLS, repli BE), ni de la fonction « Charger un projet depuis la base » au-delà de sa place dans l'écran.

## 4. Anti-objectifs (échec même si « ça marche »)

- **Perdre une capacité du dialogue d'initialisation actuel** : modèles et « Sélection manuelle », description du modèle, arbre par groupe, couches « déjà chargées » grisées, Tout sélectionner / désélectionner, arbre des fonds de plan, « Appliquer les styles de la base », mode « Ajouter des couches ».
- **Montrer un opérateur hors des scopes**, même grisé ou barré.
- **Dupliquer** une couche commune ou un fond de plan à l'ajout d'un deuxième opérateur.
- **Bloquer l'interface** : une vérification hors connexion qui tente la base, ou un test réseau sans délai court, qui fige QGIS.

## 5. Contraintes

- QGIS **3.28 minimum** (Python 3.9), jusqu'à 4.99 (Qt5/Qt6). Garder le style d'enums déjà utilisé (`Qgis.MessageLevel.Warning`, `QDialog.DialogCode.Accepted`…).
- Tous les textes en **FR / EN / PT** (`i18n/translations.py`), et la liste de clés testée (`test_bridge18_i18n.py`).
- Tests sur stubs (`constructel_bridge_tests/`, pytest) : la suite actuelle (538 verts) doit rester verte.
- Sécurité côté serveur, déjà en place :
  - `public.current_gis_operator_codes(false)` renvoie les **codes** des opérateurs des scopes OPÉRATEUR de l'identité vérifiée : `NULL` = tous (ADMIN/MANAGER), `{}` = aucune identité.
  - Correspondance code ↔ schéma ↔ libellé : `ref.operateurs (code, label, schema_name)`. Seuls les schémas réellement instanciés comptent (`ref.fn_operator_schemas()`, triés par code).
  - L'accès aux schémas opérateurs passe par les rôles `ftth_op_<schema>` accordés selon le scope OPÉRATEUR (mig 537) : sans le scope, le schéma n'est même pas lisible.
- Publication : `release.py 1.9.0 --cloture` (zip sans identifiant partagé).

## 6. Ce qui a été décidé avec Simon

### 6.1 Écran d'accueil (solution « B », tuiles avec la tuile principale dépliée)

```
┌ Constructel Bridge ───────────── ● christopherroland · Wyre : 10 MRO · écriture sur tout le périmètre ┐
│ ┌ Charger les couches ─────────────────────────────────────────────────────────────────────────────┐ │
│ │ Opérateur : [ Wyre | Orange ]     Modèle : [ Infrastructure ▾ ]  (description du modèle)         │ │
│ │ ┌ Couches de travail ───────────────────────┐  ┌ Fonds de plan ──────────┐                       │ │
│ │ │ ▾ ☑ Points de demande  [Wyre]             │  │ ▾ UrbIS Brussels        │                       │ │
│ │ │ ▾ ☑ Infrastructure     [Wyre]             │  │ ▾ OpenStreetMap         │                       │ │
│ │ │ ▾ ☑ Zones              [Wyre]             │  │ ▾ Google                │                       │ │
│ │ │ ▸ ☐ Chantier · OSIRIS · Cadastre · Urba.  │  └─────────────────────────┘                       │ │
│ │ │       (commun)                            │  ☑ Appliquer les styles de la base                 │ │
│ │ └───────────────────────────────────────────┘                                                    │ │
│ │ [Tout sélectionner] [Tout désélectionner]                               [ Initialiser · Wyre ]   │ │
│ └──────────────────────────────────────────────────────────────────────────────────────────────────┘ │
│ [ Projet enregistré ]   [ Check-in ]   [ Diagnostic ]   [ Langue ]                                    │
└───────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **En-tête** : état de connexion.
  - Connecté : login et texte de périmètre (`_scope_text()`, corrigé en 1.8.4).
  - Non connecté : « non connecté · Se connecter », qui lance la connexion existante (`_on_connect`).
- **Grande tuile « Charger les couches »** : le contenu **actuel** de `InitProjectDialog` (modèle, arbre, fonds de plan, styles, Tout/Rien, bouton), avec un **sélecteur d'opérateur** au-dessus.
- **Tuiles secondaires** : Projet enregistré (connexion requise), Check-in, Diagnostic, Langue.

### 6.2 Choix de l'opérateur

- **Un seul opérateur à la fois** (choix exclusif).
- **Liste** : uniquement les opérateurs **réellement utilisables** par la session (décision Simon : « ceux autorisés à l'utilisateur »). Concrètement :
  - opérateurs **actifs** de `ref.operateurs` dont le schéma est instancié **et lisible** par la session (`has_schema_privilege(schema_name, 'USAGE')`) ;
  - quand `public.current_gis_operator_codes(false)` renvoie un tableau **non vide**, on garde seulement l'intersection avec ces codes ;
  - quand il renvoie `NULL` (ADMIN/MANAGER) ou `{}` (compte de secours `ftth_secours`, exclu de l'identité vérifiée), ou si la fonction n'est pas exécutable (login BE), seul le filtre « schéma lisible » s'applique.

  Pourquoi : côté serveur, `ref.gis_login_sync_operator_roles` (`sql/80_security/084`) n'accorde `ftth_op_<schema>` qu'aux opérateurs actifs du scope OPÉRATEUR, ADMIN/MANAGER compris. Afficher « tous les schémas instanciés » proposerait des opérateurs illisibles, et le chargement échouerait avec « permission denied for schema ».
- **Aucun opérateur utilisable** : sélecteur et chargement désactivés, avec « Aucun opérateur accessible : demande un scope opérateur à un administrateur Farois ». Côté serveur, un login nominatif sans scope OPÉRATEUR actif ne peut normalement pas être activé (FG005, mig 537).
- **Un seul opérateur utilisable** : affiché en texte, sans sélecteur.
- **Présélection** : le dernier opérateur chargé sur ce poste (QgsSettings), s'il est toujours dans les scopes ; sinon le premier des scopes (ordre `ref.operateurs.code`).
- **Deuxième opérateur** : une fois un opérateur chargé, la tuile passe en mode « Ajouter des couches » (comme `init.title_add` / `init.btn_add` aujourd'hui). Elle rappelle ce qui est déjà chargé (« ✓ Wyre · Infrastructure · 14 couches ») et propose les autres opérateurs. Les couches communes et les fonds de plan déjà chargés sont grisés (mécanisme « déjà chargée » existant).

### 6.3 Couches qui suivent l'opérateur

- **Couches opérateur** : groupes du catalogue *Points de demande*, *Infrastructure* et *Zones*. Ce sont les entrées de `LAYER_CATALOG` aujourd'hui en schéma `wyre` ; elles sont lues dans le schéma de l'opérateur choisi.
- **Couches communes** : Chantier, OSIRIS, Cadastre UrbIS (WFS) et Urbanisme (WFS). Elles sont chargées **une seule fois**, quel que soit le nombre d'opérateurs.

### 6.4 Organisation du panneau Couches

```
▾ Wyre                  ← groupe racine au libellé de l'opérateur (ref.operateurs.label)
    ▸ Points de demande
    ▸ Infrastructure
    ▸ Zones
▾ Orange                ← ajouté par « Ajouter les couches · Orange »
    ▸ …
▾ Commun                ← « Common » (EN), « Comum » (PT)
    ▸ Chantier
    ▸ OSIRIS
    ▸ Cadastre UrbIS
    ▸ Urbanisme
▸ Basemaps
▸ Référence
```

- **Toutes** les couches d'un opérateur sont dans le groupe à son nom (décision Simon).
- Le reste des couches de travail est dans le groupe **Commun** (décision Simon).
- **Noms des couches opérateur : suffixe de l'opérateur** (décisions Simon) : « Câbles · Wyre », « Zones POP · Orange ».
  - **Un seul opérateur dans le projet** : le suffixe est **optionnel**. Une case « Ajouter le nom de l'opérateur aux couches » est proposée dans la tuile de chargement. Mon interprétation de « en option » : la case est **décochée par défaut**, et le dernier choix est mémorisé sur le poste.
  - **Dès qu'un deuxième opérateur est chargé ou ajouté** : le suffixe devient **obligatoire** pour toutes les couches opérateur. La case est alors cochée et grisée. Au clic « Ajouter », les couches du premier opérateur encore sans suffixe le reçoivent aussi.
  - Le suffixe s'ajoute **après** la traduction du nom (`apply_layer_name`), dans la langue courante, et suit un changement de langue.
  - Les couches communes n'ont jamais de suffixe.

### 6.5 Projets existants (structure 1.8.x)

- **Ouvrir** un ancien projet ne le modifie jamais : `_on_project_read` reste sans effet sur l'arbre.
- La réorganisation n'a lieu **qu'au clic « Ajouter des couches »** dans le nouvel écran (décision Simon) :
  - les groupes racine *Demand Points*, *Infrastructure* et *Zones* passent dans le groupe de l'opérateur dont ils viennent (schéma de la source des couches, `wyre` pour les projets 1.8.x) ;
  - les groupes communs (*Chantier*, *OSIRIS*, *Cadastre UrbIS*, *Urbanisme*) passent dans **Commun** ;
  - les couches opérateur existantes suivent la règle du suffixe du § 6.4 : suffixe optionnel si le projet n'a toujours qu'un opérateur, obligatoire si on ajoute un autre opérateur.
- Un projet partagé en base est en lecture seule hors administrateurs (mig 539). Après réorganisation, l'utilisateur l'enregistre en local, comme pour toute autre modification.

### 6.6 Hors connexion

- L'écran s'ouvre quand même.
  - Le sélecteur d'opérateur et le bouton de chargement sont désactivés, avec « Connecte-toi pour voir les opérateurs auxquels tu as accès ».
  - « Projet enregistré » est désactivé.
- **Check-in** : l'assistant d'accueil existant (`bridge_onboarding.py`), rendu lançable sans connexion.
  - Les pages *Plugins recommandés*, *Resource Sharing* et *Résumé* fonctionnent hors ligne.
  - La page *Profil* (qui passe par `db_conn`) est sautée, ou indiquée « disponible une fois connecté ».
- **Diagnostic** (nouveau). Quatre vérifications, chacune avec un état OK / avertissement / erreur et, quand c'est possible, une action :
  1. **Version du plugin** comparée au dépôt Constructel (mise à jour disponible ?).
  2. **Extensions recommandées** (`RECOMMENDED_PLUGINS`) installées, activées et à jour, avec un bouton pour installer ou mettre à jour.
  3. **Accès au serveur Farois** : serveur joignable (hôte et port de `credentials.json`, délai court) et certificat du serveur valide (CA de `certs/`, verify-full).
  4. **Identifiant nominatif** configuré sur ce poste (login AD mémorisé, entrée du gestionnaire d'authentification QGIS).
- **Langue** : l'action existante (`_on_change_language`).
- **Ouverture** : au clic seulement.

### 6.7 Navigateur QGIS et projets enregistrés

Ajout du 12/11, décision Simon :
- la connexion `wyre` du navigateur QGIS, aujourd'hui restreinte aux schémas `wyre,osiris`, expose les schémas des **opérateurs utilisables** (§ 6.2), plus `osiris` ;
- « Projet enregistré » liste les tables `qgis_projects` des schémas des opérateurs utilisables, plus `public`, au lieu de `wyre` et `public` seulement ;
- sans liste d'opérateurs (échec de lecture), on garde le comportement 1.8 (`wyre,osiris` ; `wyre` et `public`).

## 7. Points techniques à traiter (pistes, pas une solution imposée)

- **Catalogue paramétré par schéma.** `LAYER_CATALOG` code `wyre` en dur. Les entrées opérateur doivent prendre le schéma de l'opérateur au chargement. Les **clés** de couches doivent devenir propres à l'opérateur partout où elles indexent des couches chargées (deux opérateurs = deux `cables`) :
  - `init_project`, `ensure_relations(loaded)` ;
  - la détection « déjà chargée » (`schema.table`) ;
  - l'application des styles ;
  - `_rewrite_value_relation_sources` ;
  - les traductions de couches (`bridge_sketcher`, indexées par table).
- **Identité du projet.** `@bridge_operator` et `writeEntry("bridge", "operator")` valent aujourd'hui `wyre` (une valeur). Il faut passer à la liste des opérateurs chargés, en gardant la lecture des projets existants.
- **Lecture seule.** `should_lock_layer(schema, scope)` (`bridge_nominatif.py`) ne vise que `schema == "wyre"`. Il faut l'étendre à tous les schémas opérateurs.
- **Périmètre affiché.** `_read_session_scope` ne résout les noms de MRO/POP que dans `wyre.zone_mro` / `wyre.zone_pop`. Il faut les résoudre dans les schémas opérateurs autorisés.
- **Styles.** Recherche dans `public.layer_styles` par `(f_table_schema, f_table_name)`. Si un opérateur n'a pas de style propre pour une table, on utilise le style `wyre` de la même table (voir § 9).
- **Résolution par nom de couche (obligatoire avec plusieurs opérateurs).** Plusieurs mécanismes trouvent une couche par son nom ou sa table. Avec deux opérateurs, un formulaire Orange pourrait viser une couche Wyre et proposer des POP que les FK propres à chaque opérateur refusent (mig 543). Chaque couche opérateur doit viser les couches **de son propre opérateur** :
  - les expressions des styles embarqués, par exemple `get_feature('zone_pop', 'id', zone_pop_id)` dans cables, subducts, zone_distribution et zone_drop ;
  - les ValueRelation, qui ciblent par `LayerName` ;
  - `_sync_value_relation_layer_names`, dont la table table → nom s'écrase dès que deux opérateurs ont la même table.

  La technique (identifiant de couche, ou noms suffixés uniques plus réécriture) est laissée au builder.
- **Constats du relecteur côté serveur :**
  - toutes les tables du catalogue existent dans chaque schéma opérateur, `trench_segments` et `v_duct_progress` compris (mig 342/475/480) ;
  - `ref.operateurs` et les fonctions `current_gis_*` sont lisibles par les logins via `ftth_editor` ;
  - `@bridge_operator` n'a aucun consommateur côté Farois.
- **Diagnostic non bloquant** : les vérifications réseau tournent avec un délai court, hors du fil de l'interface (QgsTask ou équivalent).
- **Menu déroulant** du bouton (flèche) : conservé. L'entrée « Statut » ouvre le Diagnostic, qui reprend aussi les informations de connexion de l'actuel `_on_status`.

## 8. Laissé au builder

- La structure des widgets : extraire le contenu de `InitProjectDialog` en widget réutilisable ou réutiliser la classe, mise en page exacte, tailles, icônes.
- La façon d'obtenir la dernière version publiée (URL de `plugins.xml` du dépôt Constructel).
- La stratégie de tests sur stubs.
- La formulation exacte des messages (FR/EN/PT), dans le sens décrit ici.

## 9. Choix faits par Claude (à vérifier par Simon)

1. **Basemaps et Référence** restent des groupes techniques **à la racine**, sous Commun, et non dedans. Référence porte la couche cachée `v_form_lists` des formulaires.
2. **Un opérateur déjà chargé reste sélectionnable** en mode ajout, pour compléter ses couches manquantes.
3. **Style de repli** : le style `wyre` de la même table si l'opérateur n'a pas le sien.
4. **Liste d'opérateurs** : filtre « schéma lisible » (USAGE), croisé avec les scopes quand le serveur en renvoie. Ce filtre remplace la règle « ADMIN/MANAGER voient tout » et le repli « Wyre seul ».
5. **Suffixe optionnel avec un seul opérateur** : la case est décochée par défaut et le choix est mémorisé sur le poste. C'est mon interprétation de « en option ».
6. **Version cible** : 1.9.0 (nouvelle fonctionnalité).
