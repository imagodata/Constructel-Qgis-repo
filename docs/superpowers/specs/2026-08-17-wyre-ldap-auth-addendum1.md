# Addendum 1 — décisions post-revue finale

**Date** : 2026-08-17
**Contexte** : la revue finale de branche (Farois + qgis_repo) a trouvé 2 défauts critiques
bloquants pour Task 10 et plusieurs points nécessitant un arbitrage de Simon. Cet addendum
documente les décisions prises et le design retenu pour chacune ; il complète
`2026-08-17-wyre-ldap-auth-design.md` sans le réécrire.

## 1. Migration 375 — rôle intermédiaire `wyre_ldap_users`

**Problème** : `ftth_editor` a été créé par `postgres` (via `deploy_roles.sh`) ; `ftth_admin`
n'a pas l'ADMIN OPTION requise (PostgreSQL 16+) pour lui retirer `LOGIN` ni pour lui `GRANT`
son appartenance à quiconque. De plus, si `pg_role_sync` gère directement l'appartenance à
`ftth_editor`, tout rôle qui s'y retrouve membre pour une autre raison (ex. `ftth_admin`
lui-même, une fois l'ADMIN OPTION posée) serait candidat à un `NOLOGIN` accidentel au
prochain passage du script.

**Décision (Simon)** : rôle intermédiaire dédié, `wyre_ldap_users` — NOLOGIN, créé par
`ftth_admin` (aucun problème d'ownership, c'est un rôle neuf). `pg_hba.conf` cible
`+wyre_ldap_users` (pas `+ftth_editor`). `pg_role_sync` gère exclusivement l'appartenance à
`wyre_ldap_users` (création/désactivation, `current` scope sur ce rôle) — il ne touche plus
jamais directement à l'appartenance `ftth_editor`.

**Le problème d'ADMIN OPTION persiste malgré tout** pour deux opérations qui doivent quand
même toucher `ftth_editor` lui-même :
- `ALTER ROLE ftth_editor NOLOGIN` (migration 375/376)
- `GRANT ftth_editor TO "<personne>"` (héritage des privilèges infra/osiris — sans ce GRANT,
  le rôle individuel n'aurait accès à rien malgré son appartenance à `wyre_ldap_users`)

**Résolution** : une étape manuelle, unique, hors migration versionnée, exécutée sous
`postgres` (seul un superuser ou un rôle ayant déjà l'ADMIN OPTION peut la poser) —
documentée dans Task 10, pas dans le SQL :
```sql
GRANT ftth_editor TO ftth_admin WITH ADMIN OPTION, INHERIT FALSE;
```
`INHERIT FALSE` : `ftth_admin` obtient le droit d'administrer `ftth_editor` (altérer,
accorder son appartenance) sans hériter de ses privilèges effectifs — pas d'élargissement
non désiré du périmètre de `ftth_admin`. Une fois cette ligne posée (une seule fois, avant
la première exécution de la migration 375 révisée), `ftth_admin` peut exécuter la migration
ET `pg_role_sync` peut faire `GRANT ftth_editor TO "<personne>"` normalement, indéfiniment.

Cette étape est un précédent déjà accepté dans ce dépôt : `deploy_roles.sh` lui-même
s'exécute sous `postgres` pour du bootstrap administratif hors migration versionnée
(pose des mots de passe des rôles). Le geste ci-dessus est de la même famille.

## 2. Séquencement du rollout — coupure nette conservée

**Décision (Simon)** : garder l'ordre du plan original (pg_hba + migration 375 avant
publication du plugin 1.6.0). Pas de fenêtre de cohabitation entre versions. Conséquence
assumée : tout poste encore en 1.5.3 après la coupure perd l'accès `wyre` jusqu'à sa mise à
jour manuelle — à communiquer clairement au moment de l'exécution de Task 10.

## 3. `pg_role_sync` — planification cron ajoutée

**Décision (Simon)** : ajouter une planification, sur le modèle exact de `ldap_sync`
(migration 289). Nouvelle migration, seed dans `esb.farois_cron_jobs` :
```sql
INSERT INTO esb.farois_cron_jobs (name, description, command, cron_expression, enabled)
VALUES (
    'pg_role_sync',
    'Synchronisation des roles Postgres individuels wyre (wyre_ldap_users) depuis un groupe AD',
    'python3 -m farois.cron.pg_role_sync',
    '25 4 * * *',
    FALSE
)
ON CONFLICT (name) DO NOTHING;
```
`enabled = FALSE` par défaut (convention du dépôt) — activé manuellement par un admin après
un dry-run validé, via `farois cron enable pg_role_sync` ou l'UI Cron. Aucun changement de
signature nécessaire côté `pg_role_sync.py` : `main()`/`run()` correspondent déjà exactement
à la convention `python3 -m <module>` + exit code (confirmé par lecture de
`farois/commands/cron_cmd.py` et du seed de `ldap_sync`).

## 4. Cache en mémoire après connexion réussie (qgis_repo)

**Problème** : après le passage à l'auth LDAP, `_auto_connect()` ne connecte plus jamais
silencieusement — la personne doit saisir son mot de passe dans le dialogue **natif** de
QGIS (déclenché par le chargement d'une couche). Mais le plugin lui-même reste alors
« déconnecté » (pas de hooks de commit, pas d'enregistrement `ref.users`, pas de
`app.current_user`), et si l'utilisateur clique ensuite sur le dialogue du plugin, il retape
son mot de passe une seconde fois.

**Décision (Simon)** : ajouter un cache en mémoire (jamais persisté) après une connexion
réussie, quel que soit le chemin (natif QGIS ou dialogue du plugin) :
```python
QgsCredentials.instance().put(realm, DEFAULT_USER, password)
```
posé sur les mêmes variantes de realm que `_precache_pg_credentials` énumérait avant sa
suppression (host/port/dbname avec et sans sslmode). Ce cache vit en RAM, meurt avec le
process QGIS, n'est jamais écrit sur disque — ne réintroduit pas de stockage persistant, ne
viole pas l'invariant « aucun mot de passe wyre stocké ». Objectif : si la personne s'est
déjà authentifiée une fois dans la session (par n'importe quel chemin), elle ne doit plus
être re-sollicitée, ET le plugin doit passer en état connecté (hooks, `ref.users`) dans ce
cas — donc en plus du cache credentials, il faut détecter la connexion réussie via le
dialogue natif et déclencher le même chemin que `_connect()` (enregistrement utilisateur,
hooks) plutôt que de se contenter de mettre en cache le mot de passe.

## 5. `be` perd l'accès aux couches `wyre` dans les projets partagés — accepté

**Décision (Simon)** : accepter ce changement de comportement. Documenté comme amélioration
de sécurité assumée, pas une régression — `be` n'était de toute façon pas censé accéder à
`infra`/`osiris`. Aucune action de code supplémentaire.

## 6. `credentials.json` embarqué dans le zip — mot de passe `be` retiré du build

**Problème** : `release.py` embarque `credentials.json` tel quel dans le zip, y compris le
mot de passe `be` en clair-base64 — commité sur un dépôt GitHub public à chaque release,
déjà flaggé le 2026-07-30, jamais traité.

**Décision (Simon)** : traiter maintenant. Design retenu (le plus simple, cohérent avec le
traitement déjà appliqué à `wyre`) : `release.py` retire `be.password` (et `be.user`, non
secret mais autant rester cohérent) du `credentials.json` qu'il embarque dans le zip — la
source sur disque dans le dépôt worktree garde le bloc `be` complet (nécessaire pour les
tests/vérifications locales), seul le zip distribué est amputé. Après installation depuis le
zip, `be` est présent mais désactivé (`BE_ENABLED` retombe à `False`, dégradation déjà
gérée par le code existant) jusqu'à ce qu'un admin complète `user`/`password` dans le
`credentials.json` installé — distribution hors-git de ce complément, canal à définir par
Simon (hors périmètre du code : remise en main propre, partage réseau interne, etc.), à
documenter dans Task 10.

## 7. Références `ftth_editor` restantes — auditées

- `sql/bridge_grants.sql` (qgis_repo) : **aucune action nécessaire**. Le fichier fait
  `GRANT ... TO ftth_editor` — ce GRANT reste valide et continue de bénéficier aux rôles
  individuels via l'héritage de `ftth_editor` (`GRANT ftth_editor TO "<personne>"`,
  conservé par le design du point 1 ci-dessus). Vérifié par lecture directe du fichier.
- `plugin-repo/packages/constructel_bridge/styles/*.qml` (9 fichiers) : **action requise**.
  Chaque fichier embarque une `LayerSource` figée pointant sur `ref.v_form_lists` avec
  `user='ftth_editor'` (pas de mot de passe dans la chaîne — vérifié, pas de fuite de
  secret, mais la chaîne de connexion elle-même devient inopérante après la migration 375).
  Utilisé par les widgets ValueRelation des formulaires. Ce chantier ajoute une tâche pour
  auditer si cette valeur figée dans le style est réellement consommée au chargement (elle
  pourrait être supplantée par la couche vivante que `_ensure_ref_layers()` crée à
  l'exécution) et, si oui, la corriger — probablement en retirant `user='...'` de la chaîne
  pour laisser QGIS retomber sur la résolution de connexion standard, à valider par lecture
  du code de chargement de style.
