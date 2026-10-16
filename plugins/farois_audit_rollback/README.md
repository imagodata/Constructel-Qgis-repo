# Farois — Historique et rollback

Version 0.2.5 : une modification liée à d'autres changements (cascade, transaction à plusieurs
lignes) indique désormais clairement d'utiliser « Annuler la transaction ».

0.2.4 : plus de saisie de motif (motif automatique dans l'audit), confirmation courte sans valeurs, succès dans la barre de messages

0.2.3 : la raison d'une annulation impossible s'affiche dans le menu ; seules les modifications non enregistrées de la couche concernée bloquent l'annulation.

Version 0.2.2 : colonne Avant → après, détail Champ | Avant | Après, « création »/« suppression » dans Colonnes.

Connexion automatique à l'API Farois (0.2.2). La boîte « Se connecter à Farois »
propose « Se souvenir de moi (30 jours) », cochée par défaut ; l'adresse est
préremplie avec la dernière saisie, à défaut celle de Constructel Bridge
(`constructel_bridge/audit_email`). Case cochée : seul le jeton de rafraîchissement
de la session (30 jours depuis la connexion) est conservé, chiffré dans le
gestionnaire d'authentification QGIS (configuration « Farois — session historique »,
identifiant dans `farois_audit_rollback/session_authcfg`). Le mot de passe AD n'est
jamais stocké, le jeton d'accès reste en mémoire. Case décochée : rien n'est conservé
et une session mémorisée auparavant est oubliée. Si l'enregistrement échoue, la
session mémorisée auparavant est effacée (jamais d'ancienne identité reprise).

Mot de passe maître QGIS : la case étant cochée par défaut, la première connexion
peut faire demander par QGIS son mot de passe maître, ou en faire créer un s'il
n'en existe pas encore. Le jeton est relu à l'ouverture du panneau : QGIS peut
alors aussi demander ce mot de passe, s'il n'est pas déjà déverrouillé dans la
session ni enregistré dans le gestionnaire de mots de passe du système. Refuser
laisse simplement la session non reprise (jeton gardé).

À la première ouverture du panneau dans une session QGIS (jamais au démarrage de
QGIS), le plugin reprend la session mémorisée sans aucune boîte de dialogue du
plugin, avec un délai court (5 s) : session expirée ou révoquée → jeton effacé,
bandeau « session expirée — reconnectez-vous (clic droit) » ; API injoignable →
jeton gardé, bandeau « API injoignable », nouvel essai à la prochaine ouverture du
panneau ; compte non ADMIN/MANAGER → session fermée et jeton effacé.
« Se connecter à Farois… » essaie d'abord ce jeton gardé, sans mot de passe, et
n'ouvre le dialogue que s'il échoue.
En cours d'utilisation, un jeton d'accès expiré est renouvelé une seule fois en
silence et la requête refusée (donc non exécutée) est rejouée une seule fois ;
sinon le panneau demande de se reconnecter, sans jamais repasser par PostgreSQL.
« Se déconnecter » révoque la session côté API et efface le jeton mémorisé ;
fermer QGIS ou désactiver le plugin ne la révoque pas.

Version 0.2.1 : les administrateurs (ADMIN, MANAGER) se connectent à l'API Farois
(clic droit du panneau ou menu Farois → Se connecter à Farois…, compte AD) et peuvent
annuler toute modification connue du moteur 442 : RESTORE pour une suppression,
annulation de transaction pour une création, FORCE proposé après confirmation en cas
de conflit, depuis toutes les portées de l'historique. Le mot de passe AD est demandé
à la connexion et jamais stocké ; le jeton d'accès reste en mémoire (8 h), et depuis
0.2.2 seul le jeton de rafraîchissement peut être mémorisé (voir ci-dessus). L'URL de l'API est
réglable dans les paramètres QGIS (`farois_audit_rollback/api_url`, défaut
`http://192.168.160.31:8080`).
Zip : `farois_audit_rollback.0.2.4.zip` (le point est requis pour que QGIS propose la mise à jour).

Version 0.1.8 : informations d'audit complètes avec le moteur existant,
contrat d'annulation détecté, conflit sans restitution partielle, détail avant/après
et modification des attributs actuels dans le formulaire QGIS. Le logo et les
menus de navigation sont conservés.

Barre d'outils (non publié) : une seule entrée, Historique Farois, avec le logo
retour/avance (icon.svg, farois-logo.png 128 px), qui ouvre le panneau. Les
annulations restent dans le clic droit de l'historique et le menu Extensions → Farois.

Plugin QGIS autonome farois_audit_rollback, indépendant de Constructel Bridge.
Sans session admin, PostgreSQL est l’autorité pour identité, droits, périmètre, fenêtre,
conflits et journalisation. En session admin, l’API Farois (compte AD, rôle ADMIN/MANAGER)
et le moteur 442 sont l’autorité : identité, droits, conflits et journal (avec le motif).
Python n’exécute jamais de SQL fourni par l’utilisateur et ne construit pas d’UPDATE.

## Installation et utilisation

Dans QGIS : Extensions → Installer depuis un ZIP, puis activer le plugin.
La couche active doit être une couche PostgreSQL issue d’une connexion QGIS standard.
Sans session admin, aucun mot de passe n’est demandé. En mode admin, le mot de passe AD
est demandé par « Se connecter à Farois… » et n’est jamais stocké ; avec « Se souvenir
de moi », seul le jeton de rafraîchissement (30 jours) est conservé, chiffré par QGIS.
Ouvrir le panneau Farois et choisir la couche source : son historique récent se charge
même sans objet sélectionné. Sans session admin, une annulation exige le mode Objet
sélectionné et exactement un objet. En session admin, elle est possible depuis toutes
les portées (un objet supprimé n’apparaît qu’en portée couche ou « Tous les changements
visibles »). Un motif est obligatoire (500 caractères au maximum en mode admin).

Le mode utilisateur est FIELD. FORCE et RESTORE restent réservés à l’administrateur :
ils passent par l’API Farois, qui les soumet au moteur 442 ; aucun contournement Python.
Imports et cascades sont visibles mais non annulables par défaut. Après succès,
la couche est rechargée et l’identifiant d’annulation est affiché.

## Contrat base et développement

Le plugin détecte le contrat réel via le catalogue PostgreSQL : moteur historique
442 (argument `FIELD`, retour JSONB) ou moteur 451 (motif, UUID du journal).
L'historique 442 enrichit les candidats avec `audit.v_operator_changes_scoped`
pour récupérer utilisateur/compte, libellé, provenance et valeurs avant/après.
Les contrôles de présentation utilisent `audit.fn_undo_caller()` et
`audit.undo_window()` ; aucune identité n'est fournie comme autorisation par Python.
Le plugin appelle audit.revert_change et audit.revert_transaction avec des paramètres SQL. Les schémas sont contrôlés par
allowlist (wyre, orange, proximus, audit). Un moteur absent ou un contrat inconnu laisse l'historique en consultation seule.
Le plugin n'installe aucune migration et ne provisionne aucune identité.

Sur le VPS, sans QGIS Desktop :
    python -m compileall plugins/farois_audit_rollback
    pytest plugins/farois_audit_rollback/tests
    ruff check plugins/farois_audit_rollback
    python scripts/package_farois_audit_rollback.py

Version QGIS : 3.28–3.99. Cible : PostgreSQL 17 avec PostGIS.
La recette graphique doit être faite sur un poste QGIS Desktop avec une base de test :
couche PostgreSQL, sélection simple/multiple, historique vide, INSERT/DELETE/cascade,
filtres, prévisualisation, succès, refus et conflit.

## Désinstallation et limites

Désactiver puis supprimer le plugin dans le gestionnaire QGIS. La désinstallation
ne modifie ni les tables d’audit ni les migrations. Le MVP gère une sélection à la
fois et dépend des colonnes retournées par v_undo_candidates. La recette Desktop
reste obligatoire pour valider les métadonnées, le fournisseur PostgreSQL,
le rafraîchissement et les dialogues Qt.


## Interface améliorée et cascades

Le panneau permet de choisir soit la couche active, soit une couche PostgreSQL
du projet QGIS. La sélection de l’objet source est réévaluée lorsque la couche
ou sa sélection change. L’historique peut être actualisé automatiquement toutes
les cinq secondes, ou manuellement via le menu contextuel de la table.

Le fichier mockup.svg documente l’ergonomie cible. Le menu Farois et le clic
droit du panneau présentent deux actions distinctes : Annuler la modification et
Annuler la transaction. Sélectionner une ligne de l'historique les active selon
les informations reçues de PostgreSQL. Un UUID transaction_id valide est requis
pour la transaction. Un identifiant numérique PostgreSQL txid n'est pas accepté
à sa place. Une modification avec cascades ne bascule jamais automatiquement
vers une annulation plus large. Les cascades ne sont pas annulées individuellement.

La transaction est explicitement confirmée avant la saisie du motif : elle peut
concerner plusieurs tables et objets au-delà de l'objet source. Le panneau ne
dispose pas encore d'une prévisualisation exhaustive de tous ses effets. Le
moteur PostgreSQL décide de l'autorisation et des conflits. Les actions restent
visibles et grisées avec un motif explicite lorsque le moteur n'est pas installé.

La connexion PostgreSQL provient de la couche source créée/configurée via QGIS,
y compris lorsqu'elle est fournie par Constructel Bridge. Le plugin utilise
QgsDataSourceUri.connectionInfo(True) pour résoudre authcfg/service en mémoire,
puis psycopg2 du Python de QGIS. Il n'importe aucun code de Bridge. Sans psycopg2,
le panneau affiche la dépendance manquante et n'installe rien automatiquement.
Les modes authcfg, service PostgreSQL et certificats sont à vérifier sur Desktop.
Une nouvelle session est ouverte avec ces paramètres : elle ne copie pas les
variables de session d'un autre plugin. PostgreSQL reste l'autorité sur l'identité.

En absence du moteur d'undo, l'historique est lu via la vue filtrée
audit.v_operator_changes_scoped, jamais via audit.changes. Les valeurs avant/après,
l'acteur et le libellé utilisent les noms réels de cette vue. La vue actuelle ne
fournit pas transaction_id : les actions transactionnelles restent donc grisées.
Le modèle exploite l'UUID de l'attribut source, jamais le feature.id() numérique
de QGIS. Les filtres utilisateur/provenance/colonne portent sur l'historique de
l'objet déjà filtré par PostgreSQL. Un historique vide ne distingue pas l'absence
de changement d'un objet invisible dans le périmètre autorisé.

Recette 0.1.1 : désinstaller l'ancienne version, installer le nouveau ZIP puis
redémarrer QGIS. Vérifier la barre via Affichage → Barres d'outils → Farois.
Choisir une couche PostgreSQL configurée par Bridge et un objet avec audit ;
vérifier le message de connexion et l'historique. Sans moteur, aucune annulation
ne doit être possible. Avec le moteur sur une base de test, sélectionner une
entrée à transaction UUID, vérifier les deux boutons et leurs confirmations,
la conservation de sélection et les changements de contexte pendant le dialogue.

## Correctif 0.1.2 : cycle de vie Qt et panneau compact

Les connexions aux signaux QGIS et au timer sont suivies et détachées avant
suppression du panneau, ainsi que lors de sa destruction Qt. Les événements
déjà en attente ne touchent pas les widgets supprimés. Les couches raster
ne sont jamais connectées à selectionChanged. Les émetteurs Qt supprimés ne
sont pas déréférencés pendant le nettoyage. Un panneau détruit est recréé
à sa prochaine ouverture.

La largeur minimale demandée passe de 920 à 320 px et la largeur préférée
à 460 px. Les filtres se répartissent sur deux lignes ; les actions se placent
verticalement. La table garde un défilement horizontal. Un test natif Qt en
mode offscreen vérifie la réduction effective du dock à 360 px sur Linux.
La taille exacte dépend du thème, des polices et du facteur d'échelle Windows.

Après mise à jour depuis un ZIP, **fermer complètement puis redémarrer QGIS**.
Des callbacks de l'ancienne version peuvent rester en mémoire jusqu'au redémarrage,
avec des numéros de lignes qui ne correspondent plus aux fichiers installés.
Vérifier ensuite la version installée dans le gestionnaire d'extensions. Recette :
ouvrir/fermer le panneau, retirer une couche source, passer à une couche raster,
fermer le projet, réouvrir le panneau, puis désactiver/réactiver le plugin.
Ces actions ne doivent produire aucune erreur de widget ou couche supprimé.

## Version actuelle 0.1.5 : menu contextuel et panneau sans boutons

Les boutons du dock sont supprimés. Cliquer droit sur une ligne d'historique
propose Identifier les objets, Zoomer sur les objets et Sélectionner les objets.
Ctrl+clic et Maj+clic permettent de sélectionner plusieurs lignes. Le clic droit
sur une ligne déjà sélectionnée conserve l'ensemble de la sélection ; sur une
autre ligne, il cible seulement cette ligne. Une actualisation automatique conserve
les lignes sélectionnées tant qu'elles sont encore présentes dans le même contexte.

Chaque objet UUID est traité une seule fois, même si plusieurs changements le
concernent. Toutes les cibles sont recherchées avant de modifier la sélection :
un objet introuvable refuse l'action sans sélectionner seulement les autres.
Sélectionner remplace la sélection dans chaque couche concernée, sans toucher
aux autres couches. Zoomer effectue cette sélection puis cadre l'étendue commune
des objets, en utilisant la gestion des projections du canevas QGIS. Un objet
sans géométrie utilisable provoque un refus explicite avant la sélection.
Identifier sélectionne les objets puis ouvre leurs formulaires de lecture seule
successivement. Le double-clic reste un raccourci d'identification.

Le menu propose aussi les annulations selon les droits/moteur et le mode objet,
Actualiser l'historique et Réinitialiser les filtres. Ces deux dernières commandes
sont accessibles par clic droit dans la table même vide. Les annulations restent
dans le menu Farois ; plusieurs lignes sélectionnées ne déclenchent jamais une
annulation groupée. L'actualisation est suspendue pendant le menu ou les dialogues.
Les sections des versions 0.1.2 à 0.1.4 ci-dessous décrivent l'évolution passée ;
leurs mentions de boutons du panneau sont remplacées par ce menu en 0.1.5.

Recette Desktop : installer le ZIP 0.1.5, redémarrer QGIS, vérifier l'absence de
boutons dans le dock, puis tester clic droit simple et Ctrl/Maj multi-sélection,
zoom sur points/lignes/polygones et sur plusieurs couches de CRS différents,
identification en lecture seule (y compris couche en édition), déduplication,
objet supprimé, objet masqué, géométrie vide, et menu d'une table sans entrées.
Vérifier enfin Actualiser/Réinitialiser et la conservation de sélection au timer.
Aucun changement BDD n'est nécessaire pour ces actions de navigation.

## Correctif 0.1.3 : historique sans sélection et diagnostic du tableau vide

Trois modes sont disponibles sous le choix de couche :

- **Couche source — récent** (par défaut) : les 200 derniers changements visibles
  de la table source, sans sélection obligatoire.
- **Objet sélectionné** : tout l'historique visible de l'UUID sélectionné ; seul
  ce mode permet une annulation, si le moteur et les droits l'autorisent.
- **Tous les changements visibles** : les 200 derniers changements de la vue
  d'audit filtrée, en utilisant la connexion de la couche choisie. Ce mode ne
  contourne ni les droits PostgreSQL ni le périmètre géographique.

Le pied du panneau indique séparément le nombre d'entrées chargées et affichées.
Si des filtres masquent les lignes, utiliser Réinitialiser les filtres. Le filtre
Annulables uniquement est désactivé en l'absence du moteur afin de ne pas cacher
tout l'historique consultable. Les paramètres TLS explicites de la source QGIS
sont conservés lors de l'ouverture de la connexion psycopg2.

Un tableau vide en mode couche peut être normal : la vue filtrée n'expose pas
toutes les entrées d'audit.changes. La table doit correspondre au schema_name et
table_name enregistrés dans l'audit ; une couche basée sur une vue métier n'est
pas automatiquement associée à sa table sous-jacente. Le mode Tous les
changements visibles aide à distinguer ce cas d'un problème de connexion. Les
filtres s'appliquent aux entrées déjà chargées, pas à l'ensemble de la base.
Un résultat vide ne prouve donc pas l'absence d'audit dans la base.

Recette Desktop 0.1.3 : installer le ZIP puis redémarrer complètement QGIS.
Vérifier la version 0.1.3. Choisir une couche PostgreSQL configurée dans QGIS,
sans sélection, et vérifier le compteur du mode couche. Essayer ensuite Tous
les changements visibles, réinitialiser les filtres, puis passer en mode objet
avec une sélection simple. En cas de tableau vide, relever le message exact du
pied de panneau : erreur de lecture, zéro entrée chargée ou lignes filtrées.
Vérifier également authcfg/service/certificats avec la connexion réelle du poste.
Les tests offscreen ne remplacent pas cette recette sur QGIS Desktop.

## Version 0.1.4 : sélectionner et identifier depuis une ligne d'historique

Une ligne active avec schema_name, table_name et record_id UUID valide active
Sélectionner l'objet et Identifier l'objet, même sans moteur de rollback.
Sélectionner remplace la sélection de la couche cible par cet objet et rend la
couche active dans QGIS. Identifier effectue la même sélection puis ouvre le
formulaire d'attributs QGIS en mode IdentifyMode, en lecture seule. Un double-clic
sur la ligne déclenche également Identifier. Les attributs montrés sont les
valeurs actuelles de l'objet ; les valeurs avant/après restent celles de l'audit.

La recherche utilise les couches PostgreSQL déjà chargées et leurs filtres et
droits existants. Aucun SQL libre, chargement de couche automatique, changement
BDD ou passage en édition n'est exécuté. L'UUID d'audit est recherché dans un
attribut UUID/texte, jamais confondu avec l'identifiant numérique QGIS.
La couche source est prioritaire ; sinon la table et la connexion doivent
correspondre exactement. Les alias de connexion différents ne sont pas fusionnés
automatiquement. Plusieurs couches correspondantes exigent un choix explicite
de couche source pour éviter une sélection ambiguë.

Un objet supprimé, masqué par un filtre ou hors périmètre ne peut pas être
sélectionné. Un message explique le refus et l'historique reste affiché.
L'actualisation est suspendue pendant l'identification pour conserver la ligne
active. La sélection dans les autres couches n'est pas modifiée.

Recette Desktop 0.1.4 : installer puis redémarrer QGIS. En mode couche ou Tous les
changements visibles, cliquer une ligne et tester les deux boutons et le
double-clic. Vérifier la sélection de l'objet et le formulaire non éditable,
y compris si la couche était déjà en édition. Tester également une entrée DELETE,
une couche non chargée, un filtre de couche excluant l'objet et deux connexions
vers des bases différentes. Aucun cas ne doit déclencher d'écriture en base.


## Correctif 0.1.7 : historique, édition et contrat réel

Utilisateur, libellé, provenance et colonnes proviennent de l'audit filtré. Les
aliases vides ne masquent plus les champs renseignés ; le libellé peut être extrait
des valeurs auditées. Une information absente est explicitement signalée.
Un compte partagé `ftth_editor` dans l'audit identifie un compte PostgreSQL,
pas la personne qui l'utilisait ; le plugin ne reconstruit pas un auteur historique.
Clic droit → **Voir les valeurs avant/après** ouvre le détail du changement.

Clic droit → **Modifier l'objet** retrouve l'objet courant dans une couche chargée
et ouvre son formulaire QGIS en édition. Cette action concerne les attributs
actuels ; les valeurs de l'historique restent immuables. Enregistrer ou abandonner
ensuite le mode édition dans QGIS. Une couche non éditable, un objet absent ou
hors droits est refusé. L'annulation reste bloquée pendant toute édition PostgreSQL.

Avec 442, les UPDATE peuvent être proposés en FIELD selon auteur, délai et
identité réellement reconnus par PostgreSQL. Les autres opérations restent
refusées dans ce correctif. Les origines CASCADE/PIPELINE/BULK et les groupes visibles à plusieurs entrées
imposent une demande transactionnelle ; jamais une annulation isolée d'un effet.
Le motif est transmis au contexte transactionnel
`app.undo_reason` ; **442 ne le conserve pas dans son journal**. Le journal reste
celui du serveur. L'argument de la fonction est `FIELD`, jamais ce motif.
Une transaction explicite couvre l'appel, l'examen du retour et le COMMIT : un
conflit, y compris après une restitution partielle de champs par 442, annule toute
l'opération. Un résultat vide ne produit aucun message de succès.

Sur le VPS au diagnostic du 09/10/2026, les changements du moteur historique
n'ont pas d'identifiant d'auteur et aucun certificat utilisateur actif ne relie
la connexion automatique Bridge à un utilisateur vérifié. L'audit fournit le
compte PostgreSQL et les données métier, mais les droits du moteur refusent
l'annulation ordinaire. Le plugin montre le motif de refus et ne contourne pas
cette protection. Un login/certificat vérifiable doit être provisionné selon le
choix d'identité du projet ; cela ne réattribue pas les changements anciens.

Recette : installer l'archive 0.1.7, fermer complètement puis redémarrer QGIS.
Vérifier données et détail, menus navigation/modification, enregistrement QGIS,
refus auteur inconnu et identité inconnue, puis succès et refus atomique sur une
base de test avec auteur et identité configurés. Les tests offscreen ne remplacent
pas la recette du vrai fournisseur PostgreSQL et des dialogues QGIS Desktop.


## Correctif 0.1.8 : consultation lorsque les droits du moteur manquent

La détection du moteur vérifie les droits de lecture des candidats et les droits
EXECUTE des helpers/endpoint du contrat détecté. Un compte sans ces droits
conserve la consultation via `audit.v_operator_changes_scoped`, si cette vue
lui est autorisée. Les boutons d'annulation sont alors désactivés avec le motif
installation, contrat ou droits PostgreSQL. Aucun droit n'est accordé par le plugin.
Les archives 0.1.7 et 0.1.8 sont distinctes et immuables dans le dépôt QGIS.
Installer 0.1.8 puis fermer complètement et redémarrer QGIS.
