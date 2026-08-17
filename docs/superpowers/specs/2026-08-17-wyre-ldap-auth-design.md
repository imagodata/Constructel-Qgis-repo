# Authentification LDAP pour la connexion QGIS `wyre`

**Date** : 2026-08-17
**Statut** : proposé
**Périmètre** : connexion `wyre` du plugin `constructel_bridge`
(`plugin-repo/packages/constructel_bridge/`) + rôles/`pg_hba.conf` de la base
`farois_ftth` (`~/projects/Farois`). La connexion `be` (`bureau_etudes`) n'est
**pas** concernée par ce chantier.

## Contexte

Le chantier « Connexions QGIS `wyre`/`be` » du 2026-07-30
(`docs/superpowers/specs/2026-07-30-connexions-wyre-be-design.md`) a séparé la
connexion historique en deux : `wyre` (identifiant Postgres partagé
`ftth_editor`, schémas `infra`/`osiris`) et `be` (identifiant partagé
`bureau_etudes`, schéma `public` seul — compte unique voulu, pas de compte par
personne). La revue finale de ce chantier avait flaggé, sans le traiter, un
pattern de sécurité faible : `credentials.json` embarque le mot de passe de
`wyre` en clair-base64, committé dans git et bundlé dans le zip publié du
plugin.

Par ailleurs, Farois authentifie déjà ses utilisateurs via un bind LDAPS
applicatif contre l'Active Directory `constructelbe.corp`
(`farois/ui/auth/ldap_ad.py`, actif en prod depuis le 2026-07-27) : serveur
`dc01be.constructelbe.corp:636`, compte de service `farois ldaps`
(`LDAP_BIND_DN=CN=farois ldaps,OU=Utilisateurs SI,OU=SI,DC=constructelbe,DC=corp`),
base utilisateurs `OU=Utilisateurs,OU=SI,DC=constructelbe,DC=corp`. Ce
mécanisme est un bind applicatif Python (`ldap3`), pas une authentification
LDAP native PostgreSQL — `pg_hba.conf` de `ftth-postgres` n'a aujourd'hui que
`scram-sha-256`.

Le mapping rôle Farois ⇄ groupe AD (`AZURE_GROUP_ADMIN`, `AZURE_GROUP_VIEWER`,
etc., `docker/docker-compose.yml`) existe dans le code mais n'est câblé sur
aucun groupe réel (`.env` : toutes les variables `AZURE_GROUP_*` vides) —
c'est noté comme bloqué côté infra depuis la décision du 2026-07-13
(`memory/decision_sso_ldaps_provisioning_jit_2026_07_13.md`).

## Objectif

1. Remplacer l'identifiant Postgres partagé `ftth_editor` de la connexion
   `wyre` par une identité individuelle par personne, adossée au même
   annuaire AD que Farois — plus aucun mot de passe stocké ni côté plugin
   (`credentials.json`), ni côté Postgres pour ces comptes.
2. Laisser QGIS demander le mot de passe AD de la personne à chaque session
   (pas de mot de passe mémorisé), au lieu du mode `authcfg` silencieux
   actuel.
3. Créer/gérer les rôles PostgreSQL individuels correspondants, synchronisés
   sur un groupe AD partagé avec le futur mapping de rôles Farois.
4. Couper l'accès par mot de passe partagé `ftth_editor` (retrait de
   `LOGIN`) — le mot de passe base64 actuellement exposé dans
   `credentials.json` devient sans valeur, inutile de le faire tourner.

## Design

### Authentification PostgreSQL (`docker/postgres/pg_hba.conf`, dépôt Farois)

PostgreSQL ne crée jamais de rôle à la volée : la méthode `ldap` ne fait que
déléguer la vérification du mot de passe, le rôle Postgres doit préexister.
Mode retenu : **search+bind**, en réutilisant le compte de service `farois
ldaps` déjà provisionné pour Farois (même Bind DN, même mot de passe — pas de
nouveau compte de service à demander à l'IT) :

```
hostssl farois_ftth  +ftth_editor  192.168.0.0/16  ldap
    ldapserver=dc01be.constructelbe.corp
    ldapport=636
    ldapscheme=ldaps
    ldapbasedn="OU=Utilisateurs,OU=SI,DC=constructelbe,DC=corp"
    ldapsearchattribute=sAMAccountName
    ldapbinddn="CN=farois ldaps,OU=Utilisateurs SI,OU=SI,DC=constructelbe,DC=corp"
    ldapbindpasswd=<templated depuis .env.secrets, jamais commité>
```

Cette ligne est insérée **avant** les lignes génériques `hostssl ... all ...
scram-sha-256` existantes. La syntaxe `+ftth_editor` restreint l'auth LDAP aux
rôles membres du groupe `ftth_editor` — `postgres`/`ftth_admin` et les autres
comptes de service restent en `scram-sha-256`, inchangés.

`ldapbindpasswd` ne peut pas rester en clair dans le fichier versionné :
`pg_hba.conf` versionné garde un placeholder, substitué à partir de
`docker/.env.secrets` (valeur déjà présente, réutilisée depuis `LDAP_BIND_PASSWORD`)
au moment où le fichier est posé dans `PGDATA` — même famille de mécanisme que
`deploy_roles.sh` pour le mot de passe `bureau_etudes` du chantier précédent.
Point d'attention : contrairement au SQL (rejoué uniquement au boot si non
tracé), `pg_hba.conf` est copié depuis l'image vers `PGDATA` **seulement à
l'installation initiale** (`10_install_farois.sh`) — une mise à jour sur un
serveur déjà installé demande un geste explicite (recopie + `pg_ctl reload`
ou `SELECT pg_reload_conf();`), à documenter dans le plan.

### Rôles PostgreSQL (`farois_ftth`)

- `ftth_editor` perd `LOGIN` (`ALTER ROLE ftth_editor NOLOGIN`) et devient un
  rôle groupe pur — ses grants actuels sur `infra`/`osiris` ne changent pas.
- Un rôle individuel par personne, nommé sur son `sAMAccountName` :
  ```sql
  CREATE ROLE "<samaccountname>" LOGIN;
  GRANT ftth_editor TO "<samaccountname>";
  ```
  Aucun mot de passe posé sur ces rôles — la vérification est entièrement
  déléguée à l'AD via `pg_hba.conf`. L'appartenance à `ftth_editor` donne
  l'héritage des grants existants sans dupliquer aucun `GRANT` par personne.
- **Synchronisation** : un script analogue à `farois/cron/ldap_sync.py`
  (create/disable uniquement, jamais de `DROP ROLE`, cohérent avec la
  décision du 2026-07-13 sur `ref.users`) énumère les membres du groupe AD
  choisi et fait converger l'ensemble des rôles individuels membres de
  `ftth_editor` vers cette liste.
- **Dépendance externe non résolue** : ce groupe AD doit être le même que
  celui qui alimentera un jour `AZURE_GROUP_*` côté Farois — mais aucun de
  ces groupes n'est pour l'instant renseigné (`.env` vide, cf. Contexte). Le
  nom réel du groupe reste à obtenir de l'IT avant que le script de
  synchronisation puisse tourner. Ne bloque pas ce spec, bloque son
  implémentation.

### Plugin `constructel_bridge`

- `credentials.json`, bloc `wyre` : les clés `user` et `password` sont
  retirées (plus rien à y stocker — `be` reste inchangé, avec son
  `user`/`password` partagés).
- Nom d'utilisateur de connexion PG pour `wyre` : dérivé de
  `_get_qgis_username()` (`bridge_plugin.py:938`, déjà utilisé pour
  l'enregistrement dans `ref.users`), au lieu du `DEFAULT_USER` fixe. Suppose
  que l'identifiant retourné (profil QGIS, ou `getpass.getuser()` en repli)
  correspond au `sAMAccountName` AD sur un poste joint au domaine — **à
  valider empiriquement**, pas garanti par la seule lecture du code.
- `_setup_qgis_pg_connection(conn="wyre", ...)` : passe de `use_authcfg=True`
  à un mode sans mot de passe mémorisé, pour que QGIS affiche son dialogue de
  saisie natif à chaque session. `_BridgeCredentials._credentials_for` ne
  doit plus répondre pour le realm `wyre` (retour à la case `return None`,
  fallback vers le comportement QGIS standard) — seul `be` garde une réponse
  automatique.
- Toute la mécanique de nettoyage d'authcfg déjà en place pour éviter la fuite
  du mot de passe `wyre` dans les projets `.qgz` sauvegardés
  (`_strip_authcfg_from_dom`, `_fix_layer_credentials`, `_fix_datasource` —
  hotfix 1.5.1 du chantier précédent) devient sans objet pour `wyre` une fois
  qu'il n'y a plus de mot de passe à stocker dans un authcfg : à vérifier que
  ce code ne casse pas silencieusement en l'absence d'authcfg `wyre` (il doit
  rester actif pour `be`).

### Gouvernance / déploiement

Même discipline que le chantier du 2026-07-30 :
- Travail côté Farois (rôles, `pg_hba.conf`, script de synchro) dans une
  worktree isolée — jamais de commit direct sur le working tree partagé
  `~/projects/Farois`.
- Travail côté `qgis_repo` (plugin) sur une branche dédiée — le merge dans
  `main` de `qgis_repo` EST l'acte de publication (dépôt servi en direct sur
  `:9080`).
- Rien appliqué en prod (rôles, `pg_hba.conf` rechargé, merge/push) sans GO
  explicite de Simon.
- Aucun mot de passe dans du SQL ou du `pg_hba.conf` versionné.

## Compatibilité / risques

- **Coupure nette** : une fois `LOGIN` retiré de `ftth_editor`, plus aucune
  connexion par mot de passe partagé n'est possible sur `wyre` — pas de filet
  de secours si l'AD est indisponible. Décision assumée (cf. échanges de
  cadrage) : pas de fallback conservé.
- **Dépendance IT bloquante** : le nom du groupe AD à synchroniser n'est pas
  encore fourni ; l'implémentation du script de synchro des rôles est
  bloquée tant qu'il n'est pas obtenu.
- **`pg_hba.conf` sur serveur déjà installé** : contrairement à une migration
  SQL, la mise à jour ne s'applique pas automatiquement au prochain boot — un
  geste explicite est nécessaire (cf. Design). À documenter précisément dans
  le plan d'implémentation pour éviter une divergence entre le fichier
  versionné et l'état réel de `PGDATA`, comme cela s'est déjà produit une
  fois par le passé sur ce même mécanisme d'installation initiale.
- **Hypothèse `_get_qgis_username()` == `sAMAccountName`** : non vérifiée
  empiriquement. Si les postes ne sont pas joints au domaine ou si le profil
  QGIS diverge du login Windows, la connexion échouera systématiquement pour
  les utilisateurs concernés — à tester avant diffusion large.
- **Réutilisation du compte de service `farois ldaps`** : une fuite du bind
  Postgres (ex. `pg_hba.conf` mal protégé sur le serveur) expose le même
  compte que celui utilisé par l'application Farois — accepté comme
  compromis (cf. cadrage), isolation plus stricte explicitement écartée.

## Testing

- SQL : `SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname =
  'ftth_editor';` → `rolcanlogin = f`. Un rôle individuel créé a bien
  `rolcanlogin = t` et hérite des grants (`pg_has_role('<personne>',
  'ftth_editor', 'USAGE')` → `t`).
- Connexion réelle : `psql "host=... user=<samaccountname> dbname=farois_ftth
  sslmode=require"` avec le mot de passe AD de la personne → succès ; avec un
  mauvais mot de passe → échec (délégué à l'AD, pas de verrouillage
  Postgres). Un rôle non membre du groupe AD synchronisé (ou absent de l'AD)
  → refus de connexion.
- QGIS : ouverture d'un projet, connexion `wyre` demande explicitement le mot
  de passe (plus de connexion silencieuse) ; après saisie, les schémas
  `infra`/`osiris` sont accessibles comme avant. Un projet `.qgz` existant
  s'ouvre sans erreur (couches PG stockent leur propre URI, pas une
  référence au nom de connexion — non-régression déjà vérifiée au chantier
  précédent).
- Non-régression `be` : la connexion `bureau_etudes` continue de fonctionner
  sans changement (mot de passe partagé, `authcfg` silencieux, schéma
  `public` seul).

## Hors périmètre

- Création du groupe AD côté IT (dépendance externe, pas une tâche de ce
  chantier).
- Toute modification de la connexion `be` (`bureau_etudes` reste un compte
  partagé, conformément à la décision du 2026-07-30).
- MFA / accès conditionnel AD sur les connexions Postgres directes.
- Recalcul automatique des grants individuels si les schémas accessibles à
  `ftth_editor` changent dans le futur (hérité automatiquement via
  l'appartenance au rôle groupe — rien à faire de spécifique).
