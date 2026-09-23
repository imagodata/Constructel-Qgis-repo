# Constructel Bridge — mTLS nominatif + scopes MRO/POP — Design

**Statut :** brouillon de cadrage, aucune migration ni changement de code dans ce document.
**Origine :** prompt transmis par Simon Ducournau (session Claude Code) le 2026-09-22, qui citait en référence `docs/plans/PLAN_CONSTRUCTEL_BRIDGE_SCOPES_MTLS_2026-09-22.md`. Ce fichier référence **est introuvable** dans `Farois` ni dans `qgis_repo` (recherche exhaustive faite le 2026-09-22) — le contenu ci-dessous, reproduit tel quel, est donc devenu la seule spec écrite disponible pour ce chantier.
**Décision Simon (2026-09-22) :** le contenu ci-dessous fait foi comme spec. Le *séquencement* proposé par ce prompt (mTLS en premier) est en revanche mis en pause au profit de la séquence recommandée par `docs/cadrage/CADRAGE_SEC04_ROLES_PARTAGES_GIS_2026-09-21.md` (Marco) — voir section « État réel du terrain » en fin de document. PR Bridge 0 (ce document + son plan associé) ne préjuge pas de quand Bridge 1-3 seront repris.

---

## Prompt d'exécution — Constructel Bridge mTLS et accès MRO/POP

Tu es l'ingénieur principal chargé de faire évoluer le plugin QGIS Constructel Bridge pour supporter une identité humaine forte avec un login PostgreSQL partagé.

### Objectif

Le plugin doit continuer à connecter QGIS à Farois avec le rôle PostgreSQL partagé `ftth_editor`, mais chaque connexion PostgreSQL doit présenter un certificat client mTLS nominatif. PostgreSQL utilisera l'identité cryptographique du certificat pour résoudre l'utilisateur Farois et appliquer ses scopes READ/WRITE MRO/POP.

Le plugin ne décide pas des droits géographiques. Il fournit une connexion authentifiée ; PostgreSQL reste l'autorité finale via RLS.

### Décisions déjà prises

- Le compte Windows/profil QGIS peut préremplir l'utilisateur affiché.
- Azure AD/LDAP doit valider l'identité ; aucun fallback local ne donne de droits.
- Le login et le mot de passe PostgreSQL restent partagés.
- Chaque personne utilise un certificat client mTLS nominatif.
- Lecture et écriture sont limitées aux scopes Farois.
- Les droits d'écriture sont distincts de la lecture.
- Les scopes actuels seront lecture seule jusqu'à attribution explicite de `can_write`.
- MRO couvre tout le sous-arbre ; POP couvre ce POP et ses enfants uniquement.
- Un objet multi-POP exige tous les POP en écriture.
- ADMIN/MANAGER peuvent bypasser les scopes seulement après identité forte ; le bypass est audité côté Farois.
- Le premier lot couvre QGIS Desktop/Constructel Bridge, pas QField.

> **Note ajoutée le 2026-09-22 (découverte, pas une décision) :** rien de tout ceci n'existe aujourd'hui côté backend Farois. `ref.user_data_scopes` ne gère que `MRO` (tout ou rien) et `OPERATEUR` ; aucune colonne `can_write`, aucune fonction de résolution de sous-arbre hiérarchique, aucune fonction `current_user_pop_ids()`. Voir « État réel du terrain ».

### Interdictions de sécurité

Tu ne dois jamais :

- utiliser l'email, le nom Windows, le profil QGIS, QSettings, `application_name` ou `app.current_user` comme preuve d'identité ;
- considérer `SELECT set_config(...)` comme une authentification ;
- ajouter un fallback silencieux sans certificat ;
- générer ou accepter un certificat autosigné non approuvé ;
- embarquer une CA privée, une clé privée, un mot de passe ou un token dans le dépôt ;
- écrire une clé privée ou son mot de passe en clair dans QSettings, un fichier de projet, une URI ou les logs ;
- réduire TLS à `sslmode=require` : la cible est `verify-full` ;
- désactiver la validation du certificat serveur ou du hostname ;
- auto-inscrire librement un utilisateur en écrivant directement dans `ref.users` avec `ftth_editor` ;
- modifier ou rejouer la migration Farois 400 ;
- supposer les chemins/fichiers du plugin avant d'avoir inspecté la version réelle ;
- étendre le scope à QField dans cette livraison.

### Phase 0 obligatoire : découverte du dépôt

Avant toute modification :

1. Lis intégralement les instructions du dépôt (`AGENTS.md`, `CLAUDE.md`, README et règles de contribution).
2. Identifie la version courante et celle réellement distribuée.
3. Localise :
   - création et migration des connexions PostgreSQL ;
   - gestion QGIS Auth Manager / `authcfg` ;
   - acquisition username/email ;
   - authentification Azure AD/LDAP éventuelle ;
   - auto-inscription dans `ref.users` ;
   - injection `app.current_user` / `application_name` ;
   - hooks `beforeCommitChanges` ;
   - connexions Python internes distinctes des connexions provider ;
   - templates de projet, couches et vues éditables ;
   - stockage/logging des secrets ;
   - tests existants et mécanisme de packaging du zip.
4. Vérifie, sur la version QGIS minimale supportée, comment le provider PostgreSQL combine réellement SCRAM et identité PKI. Une configuration QGIS représente une méthode d'authentification : ne suppose pas qu'un unique `authcfg` stocke à la fois mot de passe et certificat.
5. Compare le code actuel au comportement documenté. Ne suppose pas que l'ancienne v1.0.0 ou la documentation Farois reflète la version déployée.
6. Produis un court rapport d'impact avant le premier changement : fichiers, flux, risques, dépendances manquantes.

Si le dépôt ne contient aucun contrat utilisable pour Azure AD/LDAP, la PKI ou l'API Farois, n'invente pas un endpoint. Définis précisément l'interface requise, implémente uniquement les parties testables derrière une abstraction, puis signale le blocage.

> **Phase 0 : FAITE le 2026-09-22.** Voir « État réel du terrain » en fin de document pour le rapport d'impact complet.

### Contrat de connexion cible

Chaque connexion PostgreSQL créée par le plugin doit utiliser :

- un hostname DNS validable par le certificat serveur ;
- `sslmode=verify-full` ;
- la CA serveur approuvée ;
- le certificat client nominatif ;
- la clé privée associée, protégée par QGIS Auth Manager ;
- le rôle partagé `ftth_editor` et son secret via un stockage approuvé QGIS/OS, jamais dans le code, les URI, les projets ou QSettings en clair ;
- la combinaison PKI + SCRAM réellement supportée par la version QGIS cible, réutilisée de façon cohérente par toutes les couches et connexions provider concernées.

Ne force pas artificiellement un `authcfg` unique si l'API QGIS ne sait pas composer ces deux méthodes. Le spike de découverte doit prouver une solution supportée, sans secret en clair ; à défaut, documente précisément le gap et arrête l'activation plutôt que de dégrader la sécurité.

L'objectif critique est que **chaque backend PostgreSQL ouvert par QGIS** présente le certificat. Il ne suffit pas que la connexion Python interne du plugin soit mTLS si les couches utilisent d'autres sessions.

Privilégie le type de configuration QGIS Auth Manager prévu pour l'identité PKI. Respecte les API de la version minimale de QGIS supportée par le plugin.

### Identité applicative

- Le nom Windows/QGIS sert uniquement à préremplir l'écran.
- L'identité affichée doit être confirmée par le flux Azure AD/LDAP officiel disponible.
- La clé canonique côté serveur sera `ref.users.id`, résolue depuis le certificat.
- L'email est une information d'affichage/audit et peut changer.
- Le plugin ne doit pas pouvoir choisir arbitrairement le `user_id` autorisé.
- Si une fonction de diagnostic Farois expose l'identité certifiée de la session, utilise-la pour afficher « connecté comme … » après la connexion ; n'en déduis jamais des droits côté client.

### Provisionnement et sélection du certificat

Implémente le flux compatible avec l'infrastructure réellement disponible :

1. détecter les certificats admissibles sans exposer les clés privées ;
2. sélectionner celui correspondant à l'identité validée ;
3. vérifier présence, chaîne, usage clientAuth et dates ;
4. créer/mettre à jour l'`authcfg` ;
5. tester la connexion ;
6. afficher une erreur actionnable si certificat absent, expiré, révoqué ou refusé ;
7. ne jamais retomber sur l'ancienne connexion non attestée.

Ne crée pas une mini-PKI dans le plugin. La délivrance, la révocation et le renouvellement appartiennent au runbook Constructel/Farois. Le plugin consomme les certificats provisionnés.

### Migration des connexions existantes

Le plugin doit reconnaître les anciennes connexions `constructel_bridge` / `wyre` réellement présentes et les migrer sans laisser un chemin utilisable en `sslmode=require`.

Exigences :

- sauvegarder uniquement les paramètres non secrets nécessaires au diagnostic ;
- mettre à jour l'`authcfg` et/ou les paramètres provider retenus de façon idempotente ;
- ne pas dupliquer les connexions à chaque démarrage ;
- retirer ou désactiver proprement les paramètres legacy non sécurisés ;
- ne jamais écraser une configuration valide sans possibilité de récupération ;
- prévoir une restauration de configuration, sans restaurer le fallback non attesté ;
- recharger le Browser QGIS après migration ;
- garantir que les projets existants et les nouvelles couches utilisent l'authcfg sécurisé.

### Audit legacy

Inspecte les usages de :

- `app.current_user` ;
- `application_name` ;
- écriture `ref.users` / `last_login` ;
- username configuré dans QSettings ;
- hooks avant commit.

Ils peuvent rester temporairement pour compatibilité d'audit, mais :

- documente-les explicitement comme non fiables pour l'autorisation ;
- ne les utilise dans aucune décision d'accès ;
- évite qu'une valeur déclarée contredise silencieusement l'identité certifiée ;
- prépare la suppression de l'auto-inscription directe dans `ref.users` ;
- si un provisioning reste requis, passe par le contrat API/DB borné fourni par Farois.

### UX attendue

Le plugin doit distinguer clairement :

- authentification Azure AD/LDAP échouée ;
- aucun certificat nominatif disponible ;
- certificat expiré ou chaîne invalide ;
- certificat accepté par TLS mais non mappé dans Farois ;
- utilisateur Farois inactif ;
- connexion DB indisponible ;
- édition refusée par scope.

Ne masque pas un refus de sécurité derrière une reconnexion infinie ou un warning silencieux. Un utilisateur non attesté peut éventuellement ouvrir les services publics non sensibles, mais ne doit pas charger les données métier via `ftth_editor`.

### Tests obligatoires

Ajoute des tests adaptés à la pile du dépôt.

#### Tests unitaires

- construction de la connexion avec `verify-full` ;
- sélection/validation des paramètres d'`authcfg` ;
- absence de secrets dans QSettings et logs ;
- migration idempotente d'une connexion legacy ;
- aucun fallback sans certificat ;
- erreurs distinctes et traduisibles ;
- compte Windows utilisé uniquement comme préremplissage ;
- aucune autorisation dérivée de `app.current_user`.

#### Tests d'intégration

- certificat valide + mot de passe partagé : connexion réussie ;
- mot de passe seul : échec ;
- certificat inconnu/expiré/révoqué : échec ;
- certificat valide mais mapping Farois absent : données métier refusées ;
- plusieurs couches et plusieurs connexions provider : même identité certifiée ;
- reconnexion et redémarrage QGIS ;
- projet legacy migré ;
- falsification de l'email/GUC : aucun élargissement ;
- édition dans scope WRITE réussie ;
- édition READ-only ou hors scope refusée avec message visible ;
- aucune écriture partielle après refus.

Si la CI ne peut pas démarrer PostgreSQL avec mTLS, fournis :

- tests unitaires complets ;
- fixture/config d'intégration reproductible ;
- script ou procédure de recette manuelle sans secret versionné ;
- preuve locale documentée avant de déclarer la tâche terminée.

### Livrables attendus

1. Code plugin mTLS et migration des connexions.
2. Tests unitaires et d'intégration disponibles.
3. Documentation administrateur : prérequis certificat, installation, renouvellement, révocation, diagnostic.
4. Documentation utilisateur : première connexion et erreurs courantes.
5. Changelog et version du plugin mis à jour selon les conventions du dépôt.
6. Inventaire des couches/vues éditables transmis au chantier Farois RLS.
7. Liste des dépendances Farois/PKI encore nécessaires.
8. Procédure de rollback qui ne réactive pas une connexion non attestée.

### Découpage de PR recommandé

- **PR Bridge 0 — discovery/tests :** inventaire, abstractions, tests de configuration legacy, aucun changement utilisateur.
- **PR Bridge 1 — mTLS/Auth Manager :** certificat, `verify-full`, migration idempotente, diagnostics.
- **PR Bridge 2 — identité corporate et provisioning :** Azure AD/LDAP, affichage identité certifiée, retrait auto-inscription directe.
- **PR Bridge 3 — rollout :** documentation, packaging, version, recette canari.

Chaque PR doit être autonome, testée et réversible sans réintroduire le fallback email/GUC.

### Critères d'acceptation finaux

- Toutes les connexions métier QGIS présentent un certificat nominatif valide.
- Le mot de passe `ftth_editor` seul ne donne aucun accès métier.
- Modifier l'email/QSettings/GUC ne change jamais les droits.
- Les clés privées et secrets ne sont ni versionnés, ni journalisés, ni stockés en clair.
- `sslmode=verify-full` est effectif sur les connexions et couches réelles.
- Une connexion legacy est migrée une seule fois et ne reste pas exploitable sans certificat.
- Les erreurs de certificat, mapping et scope sont distinctes et actionnables.
- Le plugin ne crée plus librement des comptes dans `ref.users`.
- Les tests couvrent connexions multiples, reconnexion et édition autorisée/refusée.
- La documentation permet à un administrateur de provisionner puis révoquer un utilisateur.

### Format de restitution

À la fin, fournis :

1. résumé du comportement livré ;
2. liste des fichiers modifiés ;
3. architecture réellement trouvée dans le dépôt ;
4. tests exécutés et résultats ;
5. preuves mTLS/QGIS obtenues ;
6. risques ou dépendances non levés ;
7. étapes précises à réaliser côté Farois/PKI ;
8. plan de déploiement et de rollback.

Ne déclare pas la tâche terminée si seule la connexion Python interne est sécurisée ou si les couches QGIS peuvent encore ouvrir une session `ftth_editor` sans certificat.

---

## État réel du terrain (ajouté le 2026-09-22, hors du prompt d'origine)

Découverte faite en lecture seule sur `sdadmin@192.168.160.31`, dépôts `~/projects/Farois` (HEAD `e2512a82`) et `~/projects/qgis_repo` (HEAD `main`@`954100a` avant création de ce worktree). Rien n'a été modifié pendant cette phase.

### 1. Le document référencé par le prompt n'existe pas
`docs/plans/PLAN_CONSTRUCTEL_BRIDGE_SCOPES_MTLS_2026-09-22.md` est introuvable dans `Farois` ni dans `qgis_repo`. La référence de cadrage réelle et la plus proche est `Farois/docs/cadrage/CADRAGE_SEC04_ROLES_PARTAGES_GIS_2026-09-21.md` (Marco, 2026-09-21).

### 2. Le socle RLS/identité (migration 400) n'est PAS actif en prod
La migration `400_sec04_gis_identity_rls` a été appliquée le 2026-09-21 à 13:44:02, puis **rollback le jour même** : elle rendait QGIS aveugle (0 ligne visible pour `ftth_editor` partout), faute de tout login PostgreSQL nominatif sur le serveur (9 rôles génériques seulement). Vérifié en base le 2026-09-22 : `ref.db_login_identity` n'existe pas, RLS désactivée sur `wyre.zone_pop`/`zone_mro`, `current_user_mro_ids()` est la version pré-400 vulnérable. Les migrations `402_sec04_lot1_fermeture_secdef_perimetres` et `403_sec05_view_security_invoker_guard` (appliquées le 2026-09-22 à 10:44) ne couvrent que le « Lot 1 » (fermetures sans impact sur la visibilité) — le « Lot 2 » (identité + RLS) n'a jamais été écrit.

### 3. Le modèle de scope MRO/POP décrit dans ce prompt n'existe nulle part
`ref.user_data_scopes` (`Farois/sql/10_tables/017_auth_tables.sql:325-339`) n'a qu'un `scope_type` texte libre (`MRO`/`OPERATEUR` en convention, `POP` jamais lu par aucun code), pas de colonne `can_write`/READ-WRITE, pas de fonction de résolution de sous-arbre hiérarchique, pas de `current_user_pop_ids()`. Ce modèle est à concevoir intégralement.

### 4. La PKI est un brouillon de février 2026, jamais activé
`Farois/scripts/deploy/pki_manager.sh` et `Farois/docker/postgres/pg_hba_mtls.conf` existent mais n'ont jamais été exécutés (`/var/lib/farois/pki` inexistant). `pg_hba.conf` actif n'a aucune règle `clientcert`, et est baked dans l'image Docker (pas de volume live) — toute activation mTLS impliquerait un rebuild/redeploy de `ftth-postgres`.

### 5. Un précédent direct existe : la v1.6.0 LDAP a causé une panne totale
Une version antérieure du plugin (`feat/wyre-ldap-auth`, commit `48a9aeb`/`619cc2f`) a implémenté une identité nominative individuelle (LDAP, pas mTLS, mais même principe de rôle PostgreSQL par personne), a été publiée en v1.6.0, puis **rollback immédiat vers 1.5.3** — message de revert : *« Publication de la 1.6.0 faite sans les prerequis serveur du plan wyre-ldap-auth (migration 375, pg_hba.conf LDAP, sync roles AD) -- tous les utilisateurs perdaient l'acces BDD »*. Le design complet existe encore dans une worktree Farois séparée : `~/projects/Farois-wyre-ldap` (branche `feat/wyre-ldap-auth`, non appliquée en prod), avec un rôle intermédiaire `wyre_ldap_users` potentiellement réutilisable.

### 6. Le cadrage de Marco classe le mTLS en Lot 4, pas en premier
`CADRAGE_SEC04_ROLES_PARTAGES_GIS_2026-09-21.md` recommande l'ordre **C → B → vues → A** (A = identité nominative/mTLS), précisément parce qu'aucune identité nominative n'existe aujourd'hui. Sur le mTLS spécifiquement : *« Variante mTLS, déjà à moitié outillée : pg_hba_mtls.conf prévoit un groupe +mtls_users en auth cert [...] Le fichier n'est référencé par aucun compose ni script — donc jamais activé [...] au prix d'une PKI client à distribuer. À évaluer contre LDAP au lot 4, pas avant. »* Le plugin `constructel_bridge` y est cité comme « dépendance externe bloquante, non estimable depuis ce dépôt ».

### 7. Décision Simon (2026-09-22)
Le chantier mTLS (Bridge 1-3) est mis en pause. La priorité immédiate est de coordonner avec Marco sur l'option B (périmètre par opérateur, rôles partagés) et le Lot 2 (identité/RLS) avant de reprendre ce prompt. **PR Bridge 0 reste utile indépendamment de ce séquencement** : c'est un refactor de testabilité + inventaire, sans changement de comportement utilisateur, qui ne dépend d'aucun des points 2-4 ci-dessus.

### 8. Trouvailles annexes, hors scope de ce document mais à traiter séparément
- `credentials.json` (mots de passe partagés `wyre`/`be`, encodés en base64 — pas chiffrés) est embarqué dans `constructel_bridge.zip`, servi en clair sur le réseau interne et committé dans l'historique git du zip. Documenté comme connu et non résolu depuis le 2026-07-30 (`.superpowers/sdd/2026-08-17-wyre-ldap-auth/progress.md:90-92`).
- `_on_before_commit()` résout la couche via `iface.activeLayer()` plutôt que via l'émetteur du signal — fragile si plusieurs couches sont éditées en parallèle (`bridge_plugin.py:1556`).
- Incohérence de métadonnées : `metadata.txt:38` référence `github.com/wyre-ftth/wyre`, le remote git réel est `github.com/imagodata/Constructel-Qgis-repo.git`.

### Suite du 2026-09-23 — Bridge 1 : dépendances Farois/PKI restantes

Bridge 1 (cette PR) livre : validation de certificat client, config PKI-Paths,
construction de ligne `.pgpass`, détection de migration — tout testé, sans
dépendance à une PKI Farois réelle (preuve empirique contre une CA/Postgres
jetables, voir `docs/superpowers/specs/2026-09-23-bridge1-spike-results.md`).

**Ce qui reste bloquant avant un déploiement réel (hors scope de cette PR,
côté Farois/ops) :**

1. **Convention de livraison du certificat.** Aucun endroit du dépôt ne
   définit où un certificat client réel atterrit sur le poste d'un
   utilisateur après émission. `pki_manager.sh create-client <name>` n'a
   jamais été exécuté — pas d'exemple d'artefact à inspecter. Le code de
   `bridge_mtls.py` ne suppose aucune convention : `validate_client_certificate`
   prend des chemins de fichiers explicites (certificat, clé, CA) ; la
   convention de répertoire pour une découverte automatique reste à décider
   avec les ops.
2. **PKI réelle jamais activée.** `docker/postgres/pg_hba_mtls.conf` et
   `ssl_ca_file` restent inactifs en prod — cette PR ne les active pas et
   ne le pourrait pas de toute façon (aucune CA Farois n'existe).
3. **`pg_hba.conf` de prod est baked dans l'image Docker**, pas monté en
   volume live — toute activation future nécessitera un rebuild/redeploy
   de `ftth-postgres`, en plus de la CA elle-même.
4. **Pas d'identité Azure AD/LDAP encore branchée** (Bridge 2) — le
   « connecté comme … » de la spec reste, pour cette PR, dérivé du CN du
   certificat uniquement, jamais validé contre un annuaire.
