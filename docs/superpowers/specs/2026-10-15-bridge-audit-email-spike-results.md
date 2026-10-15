# Spike PGOPTIONS — résultats (Task 1, plan 2026-10-15-bridge-audit-email)

Date : 2026-10-15 · Verdict : **RÉUSSI**

## Question

Un `PGOPTIONS` posé via `os.environ` depuis le Python de QGIS Windows, après
`initQgis()`, est-il transmis par le fournisseur PostgreSQL de QGIS ?

## Montage

- QGIS 3.44.6 Windows (`python-qgis.bat`), profil QGIS **temporaire**
  (`QgsApplication([], False, <tmp>)`) : réglages et base d'authentification
  réels non touchés. Lancé depuis WSL via un `.bat` d'appel.
- PostgreSQL 17.5 jetable sur le PC (`ftth-postgres:17.3.5-farois`, port
  `127.0.0.1:5433`, installation Farois désactivée). Authentification
  `scram-sha-256` (connexions venant du pont Docker). SSL activé avec les
  certificats générés par l'image.
- Table `spike_edit` + trigger BEFORE UPDATE qui enregistre
  `current_setting('app.current_user', true)`, `application_name`,
  `pg_stat_ssl.ssl` et `pg_backend_pid()`.

## Sortie brute

Script :
```
cas1_avant: commit=True
cas2_meme_conninfo: commit=True
cas3_ssl_require: commit=True
cas4_authcfg_require: commit=True
SPIKE_DONE
```

Serveur :
```
 label |         app_user          |    app_name     | ssl | pid
-------+---------------------------+-----------------+-----+-----
 cas1  |                           | python external | f   | 145
 cas2  |                           | python external | f   | 145
 cas3  | spike.user@constructel.be | python external | t   | 148
 cas4  | spike.user@constructel.be | python external | t   | 151
```

## Verdict par cas

| Cas | Situation | Attendu | Observé |
|---|---|---|---|
| 1 | Connexion ouverte avant la pose | NULL | NULL ✔ |
| 2 | Même conninfo après la pose | à documenter | NULL, **même pid 145** : le pool QGIS réutilise la connexion existante |
| 3 | Nouvelle conninfo (`sslmode=require`) après la pose | adresse | adresse ✔ |
| 4 | `authcfg` Basic + `sslmode=require` | adresse | adresse ✔ |

## Conséquences pour la conception

- Le mécanisme fonctionne sous Windows, mots de passe en clair comme `authcfg`.
- Une connexion déjà ouverte n'est jamais modifiée : les couches chargées
  avant la pose de `PGOPTIONS` gardent une session sans adresse jusqu'au
  redémarrage de QGIS. C'est exactement ce que couvre le cache
  `constructel_bridge/audit_email` appliqué en tête d'`initGui` : dès le
  deuxième démarrage, l'adresse est posée avant toute connexion.
- `application_name` vaut `python external` en mode autonome ; en QGIS
  Desktop il vaut `QGIS <version> desktop` (cf. prod), ce qui donne
  `identity_source = 'QGIS'` via la migration 443.

## Écarts de procédure (consignés au ledger)

- L'image exige `FAROIS_OPERATOR_SCHEMA` même installation désactivée :
  ajouté (`wyre`).
- Certificats SSL de l'image réutilisés au lieu d'en générer de nouveaux.
- Appel `cmd.exe` via un `.bat` (les guillemets directs échouent depuis WSL).
