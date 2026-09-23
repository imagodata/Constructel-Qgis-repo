# Bridge 1-0 — Spike mTLS + mot de passe partagé : résultats réels

**Date** : 2026-09-23
**Statut** : preuve empirique faite ; instance jetable détruite après exécution (voir « Nettoyage »)
**Périmètre** : `plugin-repo/packages/constructel_bridge_tests/spike/` (scripts et config du spike, jetables — non applicables tels quels en prod). Ce document est la preuve écrite dont dépend Task 2 (`bridge_mtls.py`) et Task 4 (spec) du plan `docs/superpowers/plans/2026-09-23-bridge1-mtls-auth-manager.md`.

## Objectif

Prouver empiriquement, contre une vraie instance PostgreSQL jetable (conteneur `spike-postgres`, port **5433** — jamais `ftth-postgres`/5432), que le pattern suivant fonctionne réellement, avec de vrais certificats OpenSSL et un vrai serveur PostgreSQL (rien de simulé) :

- une connexion doit présenter un certificat client signé par une CA de confiance (`clientcert=verify-full`) ;
- **ET**, séparément, s'authentifier par mot de passe `scram-sha-256` (canal indépendant du certificat) ;
- le CN du certificat n'est **pas** utilisé comme rôle Postgres — le rôle reste partagé (ici `spike_test_user`, à l'image de `ftth_editor` en production) ; le certificat est une porte au niveau TLS, pas un substitut à l'authentification par mot de passe.

## Pattern prouvé

### Ligne `pg_hba.conf` (byte-for-byte, committée dans `spike_pg_hba.conf`)

```
hostssl all all 0.0.0.0/0 scram-sha-256 clientcert=verify-full
hostnossl all all 0.0.0.0/0 reject
```

### Paramètres de connexion libpq prouvés

- `sslmode=verify-full` — **pas** `require` : le cas (b) ci-dessous prouve que `require` seul (sans certificat client présenté) n'est pas rejeté au niveau TLS, mais **est bien rejeté par PostgreSQL** grâce à `clientcert=verify-full` dans `pg_hba.conf` (« defense actually lives in pg_hba, not just in sslmode »).
- `PGSSLCERT` / `PGSSLKEY` / `PGSSLROOTCERT` (ou l'équivalent QGIS Auth Manager « PKI-Paths ») pointant vers le certificat client, sa clé privée, et le certificat de la CA.
- Le mot de passe (`PGPASSWORD` / `.pgpass`) est un canal **complètement séparé**, vérifié indépendamment du certificat — le cas (c) ci-dessous prouve qu'un certificat client valide ne contourne pas le mot de passe.
- Le `host=` de la chaîne de connexion doit correspondre **textuellement** au CN du certificat serveur (`localhost` dans ce spike) : `sslmode=verify-full` compare la chaîne de connexion telle quelle, pas l'adresse IP résolue (`127.0.0.1` échoue contre un certificat `CN=localhost`, voir « Écarts d'environnement » ci-dessous).

## Écarts d'environnement par rapport au brief initial (aucun n'affecte le contrôle de sécurité testé)

Le serveur `sdadmin@192.168.160.31` a trois contraintes qui ont nécessité des adaptations d'implémentation — documentées ici et dans les commentaires de `spike_compose.yml` / `run_spike.sh` — mais qui ne modifient ni la ligne `pg_hba.conf`, ni le `sslmode` testés :

1. **Image `postgres:17` non disponible.** `docker pull` d'une image non déjà en cache reste bloqué indéfiniment sur cet hôte (le manifest se récupère, mais le téléchargement des blobs CDN de Docker Hub sur le port 443 sortant est filtré — restriction réseau préexistante, sans rapport avec cette tâche ; confirmé en direct par un `docker pull postgres:17` qui reste sur `Waiting` sans jamais progresser). `spike_compose.yml` utilise donc `ftth-postgres:17.3.5-farois` (déjà en cache localement), qui est un vrai PostgreSQL 17.5 construit sur la lignée `postgres:17` + PostGIS. Nos flags `-c ssl_cert_file=` / `-c ssl_key_file=` / `-c ssl_ca_file=` (passés en ligne de commande, priorité maximale dans l'ordre de préséance des GUC PostgreSQL) garantissent que ce sont bien nos certificats jetables qui sont actifs, pas les valeurs par défaut de l'image — confirmé ci-dessous via `SHOW ssl_cert_file` etc.
2. **`WYRE_AUTO_INSTALL=false` / `FAROIS_AUTO_INSTALL=false`.** Contrairement à `postgres:17` vanilla, cette image de production embarque `/docker-entrypoint-initdb.d/10_install_farois.sh`, qui installe par défaut le schéma complet FAROIS (~300 migrations) et suppose l'existence d'un rôle superuser `postgres` — incompatible avec `POSTGRES_USER=spike_test_user` et hors-sujet pour ce spike. Ce flag (lu par le script de l'image) désactive cet installeur.
3. **`spike_pg_hba.conf` appliqué après coup (`ALTER SYSTEM` + restart), pas via `-c hba_file=` dès le démarrage initial.** L'entrypoint officiel de l'image bootstrap la base (création de `POSTGRES_USER`/`POSTGRES_DB`) via une connexion **locale** (socket Unix), que notre `spike_pg_hba.conf` (uniquement `hostssl`/`hostnossl`, aucune ligne `local`) rejetterait — cassant le bootstrap à chaque démarrage (pas de volume nommé, donc bootstrap à froid systématique). `run_spike.sh` laisse donc le conteneur démarrer avec le `pg_hba.conf` par défaut de l'image (permissif en local), puis exécute `ALTER SYSTEM SET hba_file = '/etc/postgresql-certs/pg_hba.conf';` et redémarre le conteneur (`hba_file` est de contexte *postmaster* : un redémarrage est nécessaire, `SELECT pg_reload_conf()` seul ne suffit pas — vérifié empiriquement, voir sortie brute ci-dessous). Après ce redémarrage, c'est bien notre `spike_pg_hba.conf`, non modifié, qui gouverne toutes les connexions — prouvé par `SHOW hba_file`.
4. **Correction `host=localhost` (pas `host=127.0.0.1`).** Incohérence interne au brief original : `generate_spike_pki.sh` fixe `CN=localhost` sur le certificat serveur, mais le `run_spike.sh` original du brief se connectait via `host=127.0.0.1`. `sslmode=verify-full` compare la chaîne `host=` telle quelle au CN — `127.0.0.1` ne correspond pas textuellement à `localhost`, même s'il s'agit de la même adresse loopback. Reproduit en direct (`psql: error: ... server certificate for "localhost" does not match host name "127.0.0.1"`), corrigé en connectant via `host=localhost`.
5. **Client `psql` absent localement** (pas de `psql`, pas de sudo sans mot de passe pour l'installer) : tous les appels `psql` du spike passent par `docker run --rm --network host --entrypoint psql ftth-postgres:17.3.5-farois ...`, montant `pki/` en lecture seule — comportement identique à un `psql` installé localement pour ce qui nous intéresse ici.

Aucun de ces écarts ne touche la ligne `pg_hba.conf` sous test ni le `sslmode` des connexions clientes.

## Résultats réels (sortie terminal brute, capturée le 2026-09-23, `bash run_spike.sh`)

### Démarrage, ownership de `server.key`, bootstrap

```
=== fixing ownership of pki/server.key for the container's postgres user ===
postgres uid inside ftth-postgres:17.3.5-farois = 999
 Network spike_default Creating
 Network spike_default Created
 Container spike-spike-postgres-1 Creating
 Container spike-spike-postgres-1 Created
 Container spike-spike-postgres-1 Starting
 Container spike-spike-postgres-1 Started

Waiting for spike-postgres to be ready (booting with the image's default pg_hba.conf, so bootstrap can use its local trust rule)...
/var/run/postgresql:5432 - no response
/var/run/postgresql:5432 - accepting connections
```

### Bascule vers `spike_pg_hba.conf` : pourquoi un restart, pas seulement un reload

```
=== switching to spike_pg_hba.conf (ALTER SYSTEM + restart -- see spike_compose.yml note 3) ===
ALTER SYSTEM
 Container spike-spike-postgres-1 Restarting
 Container spike-spike-postgres-1 Started
```

`hba_file` est de contexte *postmaster* dans PostgreSQL : contrairement à la plupart des paramètres, un simple reload (`SELECT pg_reload_conf();` / SIGHUP) ne suffit pas à l'appliquer — un redémarrage du serveur est nécessaire. Ce n'est pas une supposition : reproduit isolément (même `ALTER SYSTEM SET hba_file = ...;` que `run_spike.sh`, mais suivi d'un `SELECT pg_reload_conf();` au lieu du restart, pour observer ce qui se passe), la ligne de log PostgreSQL réelle suivante a été capturée le 2026-09-23 :

```
$ docker compose -f spike_compose.yml exec -T spike-postgres psql -U spike_test_user -d spike_db -c "SELECT pg_reload_conf();"
 pg_reload_conf
----------------
 t
(1 row)

$ docker compose -f spike_compose.yml logs --no-log-prefix spike-postgres | tail -3
2026-09-23 09:02:07.418 UTC [1] LOG:  received SIGHUP, reloading configuration files
2026-09-23 09:02:07.419 UTC [1] LOG:  parameter "hba_file" cannot be changed without restarting the server
2026-09-23 09:02:07.419 UTC [1] LOG:  configuration file "/var/lib/postgresql/data/postgresql.auto.conf" contains errors; unaffected changes were applied
```

C'est cette évidence — pas une hypothèse — qui explique pourquoi `run_spike.sh` fait un `docker compose restart spike-postgres` après l'`ALTER SYSTEM`, plutôt qu'un simple reload : `pg_reload_conf()` retourne `t` (« succès ») mais le log montre que le changement de `hba_file` lui-même a été ignoré silencieusement (« unaffected changes were applied ») jusqu'au redémarrage réel qui suit dans le script.

### Configuration effective après redémarrage (preuve que nos fichiers montés sont bien actifs)

```
=== waiting for spike-postgres to accept cert+password connections under spike_pg_hba.conf, and showing its effective config (proves our mounted files -- not the image's own defaults -- are what's active) ===
             hba_file
-----------------------------------
 /etc/postgresql-certs/pg_hba.conf
(1 row)

          ssl_cert_file
----------------------------------
 /etc/postgresql-certs/server.crt
(1 row)

           ssl_key_file
----------------------------------
 /etc/postgresql-certs/server.key
(1 row)

         ssl_ca_file
------------------------------
 /etc/postgresql-certs/ca.crt
(1 row)

CREATE EXTENSION
```

### Cas (a) — certificat + mot de passe : **SUCCÈS attendu**

```
=== (a) cert + password: EXPECT SUCCESS ===
                     ?column?
--------------------------------------------------
 spike connection OK, cert CN=/CN=spike_test_user
(1 row)

RESULT: SUCCESS (as expected)
```

### Cas (b) — mot de passe seul, **sans** certificat client : **ÉCHEC attendu**

```
=== (b) password alone, NO client cert: EXPECT FAILURE ===
psql: error: connection to server at "localhost" (127.0.0.1), port 5433 failed: FATAL:  connection requires a valid client certificate
RESULT: FAILED (as expected -- no cert)
```

### Cas (c) — certificat valide, mot de passe **erroné** : **ÉCHEC attendu**

```
=== (c) valid cert, WRONG password: EXPECT FAILURE ===
psql: error: connection to server at "localhost" (127.0.0.1), port 5433 failed: FATAL:  password authentication failed for user "spike_test_user"
RESULT: FAILED (as expected -- cert alone does not bypass password)
```

**Les trois cas ont produit exactement le résultat attendu.** Aucune surprise, aucune propriété de sécurité qui ne tienne pas : le certificat client est une porte TLS nécessaire mais pas suffisante (cas b), et le mot de passe reste vérifié indépendamment même avec un certificat valide (cas c).

## Nettoyage

`run_spike.sh` détruit le conteneur automatiquement en fin de script (`trap 'docker compose -f spike_compose.yml down -v' EXIT`) — sortie réelle capturée en fin du run ci-dessus :

```
 Container spike-spike-postgres-1 Stopping
 Container spike-spike-postgres-1 Stopped
 Container spike-spike-postgres-1 Removing
 Container spike-spike-postgres-1 Removed
 Network spike_default Removing
 Network spike_default Removed
SCRIPT_EXIT=0
```

Nettoyage explicite du matériel PKI jetable (Step 6), exécuté séparément après capture des résultats ci-dessus :

```
$ docker compose -f spike_compose.yml ps
NAME      IMAGE     COMMAND   SERVICE   CREATED   STATUS    PORTS
$ rm -rf pki *.srl
$ ls -la
total 28
drwxrwxr-x 2 sdadmin sdadmin 4096 ...  .
drwxrwxr-x 4 sdadmin sdadmin 4096 ...  ..
-rwxrwxr-x 1 sdadmin sdadmin 1037 ...  generate_spike_pki.sh
-rwxr-xr-x 1 sdadmin sdadmin 5224 ...  run_spike.sh
-rw-rw-r-- 1 sdadmin sdadmin 3426 ...  spike_compose.yml
-rw-rw-r-- 1 sdadmin sdadmin  473 ...  spike_pg_hba.conf
$ docker ps -a --filter name=spike-postgres
CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES
$ docker ps -a | grep -i spike
(no spike containers)
$ ss -ltn | grep 5433
(port 5433 free)
```

Balayage final, exécuté depuis la racine du worktree, de tout `spike/` (récursif) pour un `.crt`/`.key`/`.csr`/`.srl` oublié — sortie réelle, capturée le 2026-09-23 après le nettoyage ci-dessus :

```
$ find plugin-repo/packages/constructel_bridge_tests/spike -iname '*.crt' -o -iname '*.key' -o -iname '*.csr' -o -iname '*.srl'
$
```

(aucune sortie — 0 correspondance.)

**Confirmé** : la CA et les certificats jetables (`pki/`, tout `*.srl`) ont été détruits, aucun conteneur `spike-postgres` (même arrêté) ne subsiste dans `docker ps -a`, le port 5433 est libre, et le balayage `find` récursif ci-dessus confirme qu'aucun `.crt`/`.key`/`.csr`/`.srl` ne subsiste où que ce soit sous `spike/`. Le répertoire ne contient plus que les 4 fichiers scripts/config committés.

## Implications pour Task 2 (`bridge_mtls.py`)

- `build_pki_paths_authcfg_config` doit produire une configuration QGIS Auth Manager de type **PKI-Paths** portant : chemin certificat client et chemin clé privée uniquement (jamais de mot de passe — contrainte #58179). La vérification du serveur (`sslmode=verify-full`, le rôle que jouait `PGSSLROOTCERT` dans ce spike) passe par le canal TLS standard de la connexion, pas par cet authcfg. Jamais un secret en clair dans le projet/QSettings/logs (déjà une contrainte du plan).
- Le mot de passe partagé (`ftth_editor` en prod) continue de passer par un canal séparé (`.pgpass` / config Postgres QGIS classique), **jamais** fusionné avec la logique certificat — cette séparation est ce que ce spike vient de prouver empiriquement, pas juste supposer.
- `sslmode` doit être `verify-full`, jamais `require` seul : le cas (b) montre que c'est bien `clientcert=verify-full` côté `pg_hba.conf` serveur qui fait respecter l'exigence de certificat — le rôle du plugin est de fournir un `sslmode=verify-full` + les bons chemins PKI, pas de réimplémenter cette logique côté client.
- La ligne `pg_hba.conf` de production reste du ressort de l'infra Farois (hors périmètre plugin), mais ce spike en fixe la forme exacte de référence : `hostssl all all <réseau> scram-sha-256 clientcert=verify-full`.

## Notes

- La section « File Structure » de haut niveau du plan (`docs/superpowers/plans/2026-09-23-bridge1-mtls-auth-manager.md`) mentionne un `spike/README.md`, mais aucune des étapes 1 à 7 du brief de Task 1 ne lui donne de contenu à écrire. C'est une incohérence du plan lui-même, pas un oubli d'implémentation : plutôt que d'inventer un contenu sans spec, ce fichier a été délibérément omis. Seuls les 4 scripts/config (`generate_spike_pki.sh`, `spike_compose.yml`, `spike_pg_hba.conf`, `run_spike.sh`) et ce document de résultats ont été committés pour Task 1.
