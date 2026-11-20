GeoFiber As-Built — schéma projet (migration Farois 574)
Version de collection : 1.4.0.

La migration Farois 574 déplace les tables et fonctions As-Built du
schéma public vers le schéma projet (projet GoFiber). Cette version
fonctionne des deux côtés de la bascule : au début de chaque exécution,
elle regarde si la table projet.geofiber_asbuilt_depth_points existe.

- Elle existe : schéma projet. Les points et les non géocodées sont
  écrits directement ; les segments et les connecteurs sont en lecture
  seule et sont écrits par les fonctions de la base
  (fn_asbuilt_segments_upsert / _delete, fn_asbuilt_connectors_upsert /
  _delete).
- Elle n'existe pas : schéma public, comportement identique à la 1.3.0.

Le journal du traitement indique le schéma retenu (ligne « Schéma
As-Built : … »). Une exécution ne mélange jamais les deux schémas.

Droits, schéma projet : il faut se connecter avec son login nominatif
(pas un compte technique partagé) et avoir le scope PROJET GOFIBER coché
en écriture dans Farois (fiche utilisateur, onglet Périmètre), avec un
rôle Farois qui permet l'écriture réseau (ADMIN, MANAGER,
PROJECT_MANAGER ou DESIGNER). Sinon le script s'arrête avant tout
géocodage et affiche quoi demander à l'administrateur Farois.

Base à moitié migrée (table dans projet mais une fonction d'écriture
absente) : arrêt explicite avant tout géocodage, le script n'écrit
jamais directement les segments ni les connecteurs.

Pendant la fenêtre de migration : ne pas lancer le script. Une version
1.3.0 lancée après la migration s'arrête dès le début (table
public.geofiber_asbuilt_depth_points introuvable) sans rien écrire.

Projets QGIS existants : les couches As-Built qui pointent vers
public.geofiber_asbuilt_* deviennent invalides après la migration. Les
retirer (le script ajoute les couches projet.* au prochain lancement)
ou changer leur source vers le schéma projet. Les styles par défaut
de la base suivent les tables (lignes layer_styles passées à projet
par la migration).

GeoFiber As-Built — styles gérés par Farois
Version de collection : 1.3.0.

Depuis la migration Farois 538 (03/11/2026), le bureau d'études est en
lecture seule sur public.layer_styles : le script n'écrit plus de style
par défaut en base (l'ancienne étape « styles par défaut en base » est
supprimée) et la collection ne livre plus de fichiers .qml.

Source de vérité unique : le dépôt Farois, styles/asbuilt_depth_points.qml,
styles/asbuilt_depth_segments.qml et styles/asbuilt_depth_connectors.qml,
publiés en base par « farois styles init ». Les couches que le script
ajoute au projet prennent ce style par défaut de la base.

Pour changer un style : livrer le QML modifié dans styles/ du dépôt
Farois (puis « farois styles init »), pas dans cette collection.

Projets existants : une couche As-Built déjà présente dans un projet
garde le style enregistré dans ce projet (le script ne la modifie pas).
Pour reprendre le style de Farois : clic droit sur la couche › Styles ›
« Par défaut » (ou retirer la couche et relancer le script).

Le reste du script est inchangé : il n'écrit que dans les tables
public.geofiber_asbuilt_* et n'appelle que les fonctions
public.fn_asbuilt_* ; aucune table temporaire.

GeoFiber As-Built — largeur des segments selon l'échelle
Version de collection : 1.0.1.

(Historique, avant 1.3.0 : le style vit désormais dans Farois.)
Le style depth_segments.qml conserve les catégories de profondeur et
les traits pleins/pointillés. La largeur est calculée avec @map_scale,
donc avec l'échelle de chaque carte et de chaque page de l'atlas :
clamp(0.15, 0.6 * sqrt(greatest(@map_scale, 1) / 1000), 3).

La largeur augmente lorsqu'on dézoome, avec un plafond de 3 mm :
1:500 = 0,42 mm ; 1:1 000 = 0,60 mm ; 1:5 000 = 1,34 mm ;
1:10 000 = 1,90 mm ; 1:25 000 et au-delà = 3 mm.
Le minimum est 0,15 mm pour les très grandes échelles.
(Le rendu Python de repli de l'époque a été supprimé en 1.3.0.)

Après mise à jour de la collection, recharger le style de la couche
segments déjà ouverte. Relancer Layers to Atlas pour exporter le PDF :
la carte générale et les plans détaillés évaluent leur propre échelle.
Les projets avec des styles de carte verrouillés doivent actualiser ces
styles avant l'export. Vérifier un détail au 1:1 000 et une carte générale.

GeoFiber As-Built — mode seul de re-géocodage des non géocodées
Version de collection : 1.0.2.

Nouvelle case « Mode seul : re-géocoder uniquement les adresses de la
table « non géocodées » (dossier ignoré) », décochée par défaut.
Cochée, aucun fichier n'est lu (le dossier devient facultatif) : seules
les adresses de public.geofiber_asbuilt_ungeocoded sont re-soumises à
Nominatim. Celles trouvées deviennent des points (retirées de la table,
segments recalculés), les autres restent dans la table.
Décochée, un dossier vide arrête le script avec un message explicite.
