# Adresse mail de l'auteur sur chaque modification QGIS — design

Date : 2026-10-15 · Statut : validé en brainstorm (Simon + Claude), à planifier
Sous-projet 1 sur 5 du chantier « historique et annulation Farois ».
Dépôts touchés : `qgis_repo` (Constructel Bridge) et `Farois` (une migration).

## 1. Problème

Aucune modification faite depuis QGIS n'enregistre son auteur. Constat en prod
(`farois_ftth`, lecture seule, 15/10/2026) : 100 % des transactions d'audit
QGIS sur `wyre.*` ont `app_user`, `app_user_id`, `gis_user_id` et
`constructel_email` à NULL, et aucune ne porte `application_name =
constructel_bridge:<user>`.

Cause :

1. Bridge pose `app.current_user` sur **sa propre** connexion psycopg2
   (`bridge_plugin.py:1327` au login, `:2010` avant chaque commit). Les
   éditions passent par la connexion du **fournisseur PostgreSQL de QGIS**,
   une autre session. Les GUC `app.*` sont propres à chaque session : le
   trigger d'audit (`Farois sql/20_esb/025_audit_transactional_tables.sql:796`)
   lit une valeur vide.
2. La valeur posée est le nom de session Windows, pas une adresse mail. La
   migration 443 résout `constructel_user_id`/`constructel_email` en
   cherchant `app_user` **par email** dans `ref.users`.

Conséquence : historique sans acteur, plugin « Historique et rollback »
incapable d'attribuer quoi que ce soit, annulation par l'auteur impossible
par construction.

## 2. Décisions (brainstorm du 15/10/2026)

| Sujet | Décision |
|---|---|
| Nature de l'adresse | **Déclarée** par le poste (Bridge), donc falsifiable : le mot de passe `ftth_editor` est public. Elle sert à la **traçabilité seulement**. `identity_verified` reste `false`. |
| Annulation | Inchangée : réservée à l'admin tant que mTLS (sous-projet 5) n'est pas en place. L'adresse déclarée n'alimente jamais `app_user_id` ni `author_id`. |
| Mécanisme | Variable d'environnement libpq `PGOPTIONS="-c app.current_user=<email>"` posée par Bridge dans le processus QGIS, avant le chargement des couches. |
| Diffusion | Directe à tous via le dépôt `:9080`, après spike validé (pas de pilote sur un seul poste). |
| Version | Bridge **1.5.10** (1.6.x évité : numéro de l'échec LDAP du 17/08). |
| Passé | Déjà traité le 15/10 : les 20 transactions sans auteur (28/09→09/10) sont attribuées à `simonducourneau@constructel.be` comme responsable par défaut (`context.attribution='defaut_backfill'`, `identity_verified=false`). Sauvegarde : `~/ops/backups/2026-10-15_audit_attribution/`. Le même rattrapage sera rejoué juste avant la publication de 1.5.10 pour combler l'intervalle. |

Hors périmètre : moteur d'annulation, mTLS, priorité adresse vérifiée >
adresse déclarée dans `025:796` (à corriger avec mTLS), lignes
`ftth_admin`/`AUTO` de `audit.status_history`, plugin d'historique.

## 3. Vérifications préalables déjà faites (prod, lecture seule)

- **Visibilité RLS inchangée.** Les policies `wyre.*` de `ftth_editor` passent
  par `gis_row_allowed()`, qui ne lit pas `app.current_user` (vérifié sur
  3 niveaux d'appels). Sur `chantier.*` et `docs.documents`, `mro_filter`
  lit l'adresse mais est PERMISSIVE, en OU avec `gis_editor_pre_cutover` qui
  donne tout l'accès tant que l'enforcement GIS est inactif : elle ne peut
  qu'élargir. La RESTRICTIVE `gis_editor_activation_guard` ne lit pas l'adresse.
- **Lecteurs live de `app.current_user`** : `universal_trigger_before`,
  `record_esb_change`, `current_user_mro_ids`, `current_user_operator_codes`,
  `set_app_user`, `get_app_user`, `set_app_context` (aucun appelant des trois
  derniers). Aucune colonne n'a de DEFAULT basé dessus.
- **Bloquant trouvé** : `universal_trigger_before` insère
  `COALESCE(app.current_user, current_user)` dans `audit.status_history.source`,
  de type **VARCHAR(30)**, et relance l'exception hors BEON. **5 utilisateurs
  actifs ont une adresse de plus de 30 caractères** (33 au maximum) : leurs
  changements de statut seraient **refusés**. `audit.transactions.app_user`
  (VARCHAR(100), écrit via `LEFT(…,100)`) n'est pas concerné.
- 3 vues dépendent de `audit.status_history.source` :
  `v_beon_status_changes`, `v_status_history_scoped`,
  `v_dp_retenus_recul_manuel`.

## 4. Composants

### ① Migration Farois 453 (+ `453r`), déployée en premier

- `ALTER TABLE audit.status_history ALTER COLUMN source TYPE VARCHAR(255)`.
- PostgreSQL refuse ce changement tant qu'une vue utilise la colonne : dans
  **une seule transaction**, capturer puis supprimer les 3 vues, élargir,
  recréer les vues **à l'identique**, restaurer leurs ACL, leurs
  `security_barrier`/options et leurs commentaires.
- `SET LOCAL lock_timeout` court : l'élargissement varchar ne réécrit pas la
  table, mais prend un verrou ACCESS EXCLUSIVE bref.
- `453r` : remet VARCHAR(30) uniquement si `max(length(source)) <= 30` ;
  sinon `RAISE EXCEPTION` explicite, jamais de troncature.
- Numéro à reconfirmer au moment de l'implémentation (dernier sur
  `origin/main` le 15/10 : 452).
- **Point à vérifier avant tout déploiement** : 451 est présente dans le dépôt
  mais non appliquée en prod (elle refuse de s'installer si 442 est là).
  S'assurer que l'auto-migration du worker ne tente pas 451 avant 453
  (filtre d'installation, cf. `tests/unit/scripts/test_install_migration_filter.py`)
  ou appliquer 453 manuellement.

### ② Constructel Bridge 1.5.10

- **`bridge_identity.py`**, fonctions pures testables :
  - `is_valid_audit_email(email) -> bool` : liste blanche stricte
    (`^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$`, longueur ≤ 255).
  - `build_pgoptions(existing: str | None, email: str | None) -> str | None` :
    conserve les options existantes, retire toute occurrence antérieure de
    `-c app.current_user=…`, ajoute `-c app.current_user=<email>`. Renvoie
    `existing` inchangé si l'adresse est invalide ou absente.
- **`bridge_plugin.py`** :
  - Au début de `initGui` (avant tout chargement de couche, y compris un
    projet ouvert au démarrage) : si l'interrupteur est actif et qu'une
    adresse est en cache dans `QgsSettings`
    (`constructel_bridge/audit_email`), poser `PGOPTIONS`.
  - Dans `_register_bridge_user`, après résolution de l'utilisateur
    (`ref.users` par `username`) : lire son `email`, la mettre en cache,
    poser `PGOPTIONS` avant `_apply_project_hooks`/le chargement du projet.
  - `_set_app_user` et `_on_before_commit` posent l'adresse et non plus le
    nom d'utilisateur, pour la cohérence de la connexion propre de Bridge.
  - **Interrupteur** `constructel_bridge/audit_email_pgoptions` (bool, vrai
    par défaut) : à faux, Bridge ne touche pas à `PGOPTIONS`.
  - Adresse absente/invalide : avertissement dans le journal Bridge, aucune
    modification bloquée.
- `metadata.txt` : 1.5.10 + changelog. Zip et `plugins.xml` mis à jour de
  façon **ciblée** (ne pas régénérer `plugins.xml` en masse : il référence
  d'autres paquets).

### ③ Spike préalable (jetable, aucun code conservé)

Question : un `PGOPTIONS` posé via `os.environ` depuis Python, après le
démarrage de QGIS Windows, est-il transmis par le fournisseur PostgreSQL de
QGIS ?

Protocole :
- PostgreSQL 17 jetable sur le serveur (port 5433, comme le spike Bridge 1),
  table de test avec un trigger qui enregistre
  `current_setting('app.current_user', true)` et `application_name`.
- Le QGIS 3.44.6 Windows du poste de Simon, piloté par script depuis WSL
  (`python-qgis`), pose `PGOPTIONS`, ouvre une couche postgres, modifie,
  enregistre.
- Cas couverts : connexion ouverte **après** la pose (doit porter l'adresse) ;
  connexion déjà ouverte **avant** (documenter : pool QGIS) ; connexion
  `authcfg` + `sslmode=require`.

Réussite : l'adresse est lue côté serveur dans les deux premiers cas
attendus. Échec : repli à étudier (fichier de service `pg_service.conf`
avec `options=`), retour en brainstorm avant toute implémentation.

## 5. Tests

1. Unitaires `bridge_identity` : PGOPTIONS vide ; existant avec autre
   `-c` ; remplacement d'un ancien `app.current_user` ; adresses refusées
   (espace, guillemet, `\`, virgule, > 255 car., `None`) ; majuscules.
2. Ordre d'exécution dans Bridge (stubs QGIS/psycopg2) : adresse résolue
   depuis `ref.users`, `PGOPTIONS` posé avant le chargement du projet,
   interrupteur à faux respecté, utilisateur sans adresse non bloquant.
3. Suite Bridge existante dans `~/.venvs/bridge0-tests` ; résultat relu
   directement, jamais sur la seule foi d'un compte rendu de sous-agent.
4. Migration sur conteneur jetable (image existante + `sql/` monté) :
   application OK ; `pg_get_viewdef` des 3 vues identique avant/après ; ACL
   identiques ; un changement de statut avec une adresse de 33 caractères
   passe ; `453r` s'applique (et refuse s'il existe une valeur > 30).
5. Spike ③.

## 6. Déploiement

**GATE** : aucune publication de Bridge 1.5.10 sur `:9080` tant que les
trois conditions ne sont pas remplies : (a) 453 appliquée en prod et
vérifiée, (b) spike ③ réussi, (c) tests 1–4 verts et relus. Le dépôt
`qgis_repo` est servi en direct depuis son working tree.

Ordre :
1. Farois : 453 dans un worktree isolé, PR, merge ; sauvegarde
   `pg_dump -s -t audit.status_history` + définitions des 3 vues ;
   application en prod ; contrôle.
2. Spike ③.
3. Bridge 1.5.10 sur `feat/bridge-audit-email`, revue, merge sur `main`.
4. Rejouer le rattrapage d'auteur (§2) sur les transactions apparues depuis
   le 15/10, puis publier 1.5.10 (zip + entrée `plugins.xml`).
5. Vérification post-déploiement.

## 7. Vérification après publication (prod, lecture seule)

- Nouvelles transactions QGIS : `identity_source = 'QGIS'`,
  `constructel_email` non NULL, `identity_verified = false`.
- `audit.status_history.source` contient des adresses ; journaux
  PostgreSQL sans `value too long for type character varying`.
- Sur le poste de Simon : mise à jour 1.5.10, redémarrage, une
  modification, adresse retrouvée en base.

## 8. Retour arrière

- Par poste : interrupteur `constructel_bridge/audit_email_pgoptions = false`
  puis redémarrage de QGIS (`PGOPTIONS` ne vit que dans le processus QGIS).
- Pour tous : publier **1.5.11 = code 1.5.9** (QGIS ne propose jamais une
  version inférieure) ; mise à jour + redémarrage.
- Symptôme à surveiller : connexion refusée « unsupported startup
  parameter » (pgbouncer ou autre serveur atteint depuis QGIS).
- Migration : conservée en cas de retour arrière de Bridge (colonne plus
  large sans risque) ; `453r` ne tronque jamais.

## 9. Risques ouverts

- `PGOPTIONS` s'applique à **toutes** les connexions libpq du processus QGIS,
  y compris vers d'autres serveurs : sans effet sur PostgreSQL (GUC
  personnalisée), refus possible derrière pgbouncer.
- Projet ouvert au démarrage de QGIS avant le premier login Bridge : couvert
  par le cache `QgsSettings` dès le deuxième démarrage seulement.
- `ftth_editor` peut écrire dans `ref.users` : n'importe qui peut créer un
  compte avec une adresse arbitraire. Assumé (traçabilité seulement).
- Conflits probables avec les branches mTLS `feat/bridge1-*` (même zone de
  `bridge_plugin.py`) : rebase à prévoir côté mTLS.
