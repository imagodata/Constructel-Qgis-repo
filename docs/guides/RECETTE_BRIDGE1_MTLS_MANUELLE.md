# Recette manuelle Bridge 1 — mTLS Constructel Bridge

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
