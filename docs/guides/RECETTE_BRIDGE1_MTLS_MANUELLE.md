# Recette manuelle mTLS — Bridge 1 + Bridge 1b (Constructel Bridge)

> **STATUT GATE 2 : EN ATTENTE — exécution humaine sur vrai QGIS requise.**
> Cette recette (partie Bridge 1 + partie Bridge 1b ci-dessous) est la
> preuve d'intégration manuelle du chantier mTLS. Aucune activation mTLS
> sur un poste opérateur réel tant qu'un humain n'a pas exécuté les deux
> parties avec succès. Consigner : date : ____, QGIS exact : ____,
> poste : ____, exécutant : ____.

À exécuter par une personne disposant d'un vrai poste QGIS (>= 3.28).
Objectif : vérifier, avec de vrais objets QGIS (`QgsAuthManager`,
`QgsDataSourceUri`), ce que la Console Python de QGIS peut prouver et que
cette session SSH headless ne peut pas.

## Prérequis
- Rejouer `plugin-repo/packages/constructel_bridge_tests/spike/run_spike.sh`
  sur un serveur accessible depuis votre poste QGIS (le spike Bridge 1-0 est
  jetable et destructeur en sortie — ne PAS le pointer sur `ftth-postgres` de
  prod). Notez l'IP/port exposés et gardez les fichiers `pki/client.crt` et
  `pki/client.key` générés (normalement supprimés par `run_spike.sh` — pour
  cette recette, commentez temporairement l'étape de nettoyage, le temps du
  test, puis nettoyez manuellement ensuite).

## Étape 1 — Config PKI-Paths dans le Console Python QGIS

```python
from qgis.core import QgsApplication, QgsAuthMethodConfig
auth_mgr = QgsApplication.authManager()
config = QgsAuthMethodConfig("PKI-Paths")
config.setName("bridge1_recette_test")
config.setConfig("certpath", "/chemin/vers/pki/client.crt")
config.setConfig("keypath", "/chemin/vers/pki/client.key")
auth_mgr.storeAuthenticationConfig(config)
print(config.id())  # notez cet id
```
Attendu : pas d'exception, un id non vide imprimé.

## Étape 2 — Connexion combinant authcfg PKI + user/password directs

```python
from qgis.core import QgsDataSourceUri
uri = QgsDataSourceUri()
uri.setConnection(
    "<IP du spike>", "5433", "spike_db",
    "spike_test_user", "spike_test_password",
    QgsDataSourceUri.SslMode.SslVerifyFull,
    "<id noté à l'étape 1>",
)
from qgis.core import QgsVectorLayer
layer = QgsVectorLayer(uri.uri(False), "recette_test", "postgres")
print(layer.isValid())
```
Attendu : `True`. Si `False`, inspecter `layer.dataProvider().error()` et
comparer au résultat du spike (Task 1) — toute divergence est un écart
réel entre le comportement QGIS et libpq nu, à documenter ici.

## Étape 3 — Confirmer que le bug #58179 est bien contourné

Répéter l'étape 2 mais avec un authcfg "Basic" portant le mot de passe
au lieu du couple user/password direct de l'étape 2 — la couche doit
échouer à charger le certificat (c'est le bug documenté). Ceci confirme
que la conception retenue (user/password directs + authcfg PKI-Paths
séparé) est bien nécessaire, pas une précaution superflue.

## Étape 4 — Nettoyage

- `auth_mgr.removeAuthenticationConfig("<id de l'étape 1>")`
- Supprimer `pki/client.crt`/`pki/client.key` du poste de test.
- Sur le serveur : relancer `run_spike.sh` jusqu'au bout (nettoyage inclus)
  ou `docker compose -f spike_compose.yml down -v` manuellement.

## Résultat à consigner

Date, version QGIS exacte utilisée, résultat de chaque étape (succès/échec
avec message exact), toute divergence avec le comportement prouvé côté
serveur (Task 1). Coller ce résultat dans le ledger d'exécution de ce plan
ou dans un commentaire de PR — c'est la preuve d'intégration qui manque à
la CI.

---

# Partie Bridge 1b — câblage mTLS (wiring)

Vérifie le câblage du plugin lui-même (`_connect`,
`_setup_qgis_pg_connection`, `_fix_layer_credentials`) sur vrai QGIS :
plus de Console Python directe sur le spike, on passe par le menu
Constructel Bridge > Connexion base de données.

## Prérequis 1b

- Poste QGIS (>= 3.28) **de TEST** avec le plugin installé depuis la
  branche `feat/bridge1b-mtls-wiring` (jamais un poste opérateur de
  prod — GATE 1 : l'activation prod attend la convention de livraison
  des certificats, piste Farois).
- Un bundle cert client de TEST + sa CA (ex. ceux du spike Bridge 1,
  partie ci-dessus) : `client.crt`, `client.key`, `ca.crt`.
- Un Postgres de LAB joignable depuis le poste, avec :
  1. un rôle `wyre` + une base `wyre` (mot de passe connu),
  2. `ssl = on` et un certificat **serveur** signé par la CA de test
     (le client vérifie le serveur en `verify-full`),
  3. la ligne `pg_hba.conf` prouvée par le spike
     (`docs/superpowers/specs/2026-09-23-bridge1-spike-results.md`) :
     `hostssl all all 0.0.0.0/0 scram-sha-256 clientcert=verify-full`.
- Rediriger le plugin vers le lab (QGIS lancé avec ces variables,
  pas touche à la prod) :
  `WYRE_DB_HOST=<ip lab> WYRE_DB_PORT=<port lab> WYRE_DB_NAME=wyre`.

## Étape 1b-1 — Poser les chemins cert (settings explicites)

Dans la Console Python QGIS (pas d'UI de sélection dans ce plan :
chemins explicites uniquement) :

```python
from qgis.core import QgsSettings
s = QgsSettings()
s.setValue("constructel_bridge/mtls_cert_path", "/chemin/vers/client.crt")
s.setValue("constructel_bridge/mtls_key_path", "/chemin/vers/client.key")
s.setValue("constructel_bridge/mtls_ca_path", "/chemin/vers/ca.crt")
print(s.value("constructel_bridge/mtls_enabled", True))  # attendu: True (défaut ON)
```

Attendu : pas d'exception, le flag vaut `True` sans qu'on l'ait posé.

## Étape 1b-2 — Connecter wyre, vérifier l'entrée navigateur

Menu Constructel Bridge > Connexion base de données, mot de passe `wyre`.
Puis, en console :

```python
from qgis.core import QgsSettings
s = QgsSettings()
base = "PostgreSQL/connections/wyre"
print("sslmode:", s.value(f"{base}/sslmode"))            # attendu: 5 ou '5' (= verify-full)
print("authcfg:", s.value(f"{base}/authcfg"))            # attendu: == mtls_authcfg_id, non vide
print("pki id :", s.value("constructel_bridge/mtls_authcfg_id"))
print("savePassword:", s.value(f"{base}/savePassword"))  # attendu: False
print("password:", s.value(f"{base}/password", None))    # attendu: None (jamais en clair)
```

Attendu : connexion réussie, `sslmode` vaut 5, `authcfg` non vide et
égal à l'id PKI géré par le plugin, aucune valeur `password` stockée.

## Étape 1b-3 — Auth Manager + pgpass

- Gestionnaire d'authentification QGIS : exactement UNE config nommée
  `constructel_bridge_mtls`, méthode `PKI-Paths`, avec `certpath` et
  `keypath` renseignés et **aucun mot de passe** (contournement #58179).
- Fichier pgpass (`~/.pgpass` Linux,
  `%APPDATA%\postgresql\pgpass.conf` Windows) : contient une ligne
  `host:port:wyre:wyre:<mot de passe saisi>`. Sous Linux :
  `ls -l ~/.pgpass` doit afficher `-rw-------` (0600, sinon libpq
  l'ignore silencieusement).

## Étape 1b-4 — Charger une couche wyre

Ouvrir une couche via l'entrée navigateur `wyre` (ou recharger le
projet lab).

Attendu : la couche s'ouvre **sans** demande de mot de passe ; sa
source référence l'authcfg PKI (pas de `password='...'` en clair dans
l'URI). Vérifiable en console :
`QgsProject.instance().mapLayers().values()` puis `.source()` d'une
couche wyre — `authcfg='<id PKI>'` présent, `password=` absent.

## Étape 1b-5 — Révocation pgpass (pas de downgrade silencieux)

1. Supprimer **notre** ligne du pgpass (laisser les autres lignes
   intactes), sans toucher au reste.
2. Recharger le projet / rouvrir la couche wyre.

Attendu : ÉCHEC **visible** (couche invalide / erreur
d'authentification affichée), jamais un succès silencieux ; surtout,
l'URI ne doit PAS avoir été réécrite avec un mot de passe en clair
(`password=` toujours absent, authcfg PKI toujours en place).
3. Reconnecter via le plugin : la ligne pgpass est régénérée, la
   couche se recharge normalement.

## Étape 1b-6 — Kill-switch (flag OFF = retour legacy)

```python
from qgis.core import QgsSettings
QgsSettings().setValue("constructel_bridge/mtls_enabled", False)
```

Reconnecter, puis revérifier l'entrée navigateur : `sslmode` vaut de
nouveau 3 (= `require`, legacy), comportement mot de passe 1.5.5
restauré (y compris réécriture plaintext de `_fix` au rechargement
projet). Puis réactiver :

```python
from qgis.core import QgsSettings
QgsSettings().setValue("constructel_bridge/mtls_enabled", True)
```

Reconnecter : `sslmode` vaut 5 à nouveau (retour mTLS).

## Étape 1b-7 (bonus) — Cert configuré mais invalide = refus bruyant

```python
from qgis.core import QgsSettings
QgsSettings().setValue("constructel_bridge/mtls_cert_path", "/chemin/bidon.crt")
```

Cliquer Connexion : une boîte d'erreur **traduite** doit apparaître
immédiatement (ex. en français : « Fichier du certificat client
introuvable. »), pas une erreur de connexion/mot de passe trompeuse.
Remettre le vrai chemin et reconnecter (vert à nouveau).

## Étape 1b-8 — Nettoyage

```python
from qgis.core import QgsApplication, QgsSettings
s = QgsSettings()
s.remove("constructel_bridge/mtls_cert_path")
s.remove("constructel_bridge/mtls_key_path")
s.remove("constructel_bridge/mtls_ca_path")
s.remove("constructel_bridge/mtls_enabled")  # retour au défaut ON (inerte sans certs)
pki_id = s.value("constructel_bridge/mtls_authcfg_id", "")
if pki_id:
    QgsApplication.authManager().removeAuthenticationConfig(pki_id)
s.remove("constructel_bridge/mtls_authcfg_id")
s.remove("PostgreSQL/connections/wyre")  # entrée lab uniquement
```

Retirer aussi notre ligne du pgpass, puis supprimer les fichiers
`client.crt`/`client.key` du poste de test.

## Résultat 1b à consigner

Date, QGIS exact, poste, serveur lab (IP/port), résultat de chaque
étape 1b-1 à 1b-8 (succès/échec avec message exact), contenu relevé
de l'entrée `PostgreSQL/connections/wyre` (sslmode/authcfg), et toute
divergence avec les attendus ci-dessus. Coller avec le résultat
Bridge 1 — ensemble, c'est la preuve GATE 2.
