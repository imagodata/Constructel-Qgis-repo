# Projet QGIS « Gofiber » : mode de travail depuis la migration Farois 538

Décision de Simon du 03/11/2026 : **le projet est publié en base par un administrateur**.

## Ce qui a changé

- Le projet « Gofiber » est le seul projet stocké en base (`public.qgis_projects`). Il a été enregistré par `bureau_etudes` le 05/10.
- Depuis la migration Farois 538 (03/11/2026), `bureau_etudes` est en **lecture seule** sur `public.qgis_projects`, `public.layer_styles` et `public.map_themes`. Il peut toujours ouvrir le projet, mais ne peut plus l'enregistrer en base.
- Raison : quand un compte de bureau d'études écrit un projet que tout le monde ouvre, ce projet peut porter des macros Python, qui s'exécutent sur les postes qui l'ouvrent.

## Qui fait quoi

| Rôle | Action |
|---|---|
| Utilisateurs | Rien ne change : **Constructel Bridge › Charger un projet** liste les projets de `public` et `wyre` (lecture seule) et ouvre « Gofiber ». |
| Bureau d'études | Travaille sur une copie locale `.qgz` du projet, puis envoie le `.qgz` modifié à un administrateur Farois quand il faut diffuser une nouvelle version. |
| Administrateur Farois | Contrôle le `.qgz` (macros, sources de données), sauvegarde la version en base, puis publie la nouvelle version sous le nom `Gofiber`. |

## Bureau d'études : partir de la version actuelle

1. Récupérer auprès d'un administrateur la dernière sauvegarde de la version en base : `/home/sdadmin/qgis_projects_Gofiber_backup_<horodatage>.qgz` sur le serveur Farois.
2. L'ouvrir dans QGIS avec Constructel Bridge connecté. Les couches `be` et `wyre` se rattachent aux configurations d'authentification du Bridge (`07254s7`, `9i19s56`) : aucun mot de passe n'est écrit dans le fichier.
3. Enregistrer les modifications **dans le fichier** `.qgz` (Projet › Enregistrer), jamais « dans PostgreSQL » : c'est refusé depuis la 538.

## Administrateur : publier une nouvelle version

Une commande Farois dédiée est demandée (côté dépôt Farois, à venir). Elle doit :

1. refuser un projet qui contient des macros Python (Projet › Propriétés › Macros) ou des actions Python ;
2. sauvegarder la version en base avant de la remplacer ;
3. écrire le `.qgz` dans `public.qgis_projects` sous le nom `Gofiber`.

D'ici là, un administrateur Farois fait ces trois étapes à la main :

1. sauvegarder la version en base (export en lecture seule de `public.qgis_projects`, comme le 03/11) ;
2. ouvrir le `.qgz` reçu dans QGIS et vérifier qu'il n'a **aucune macro** ;
3. l'enregistrer en base (Projet › Enregistrer sous › PostgreSQL, schéma `public`, nom `Gofiber`) **sous un compte d'administration**, jamais `bureau_etudes`.

## Sauvegardes

| Date | Fichier (serveur Farois) |
|---|---|
| 05/10/2026 | `/home/sdadmin/qgis_projects_Gofiber_backup_20261005_133718.qgz`, `…_133802.qgz` |
| 03/11/2026 | export en lecture seule avant la mise en place de ce mode de travail (voir le rapport du chantier) |
