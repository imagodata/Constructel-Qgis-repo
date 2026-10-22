GeoFiber As-Built — largeur des segments selon l'échelle
Version de collection : 1.0.1.

Le style depth_segments.qml conserve les catégories de profondeur et
les traits pleins/pointillés. La largeur est calculée avec @map_scale,
donc avec l'échelle de chaque carte et de chaque page de l'atlas :
clamp(0.15, 0.6 * sqrt(greatest(@map_scale, 1) / 1000), 3).

La largeur augmente lorsqu'on dézoome, avec un plafond de 3 mm :
1:500 = 0,42 mm ; 1:1 000 = 0,60 mm ; 1:5 000 = 1,34 mm ;
1:10 000 = 1,90 mm ; 1:25 000 et au-delà = 3 mm.
Le minimum est 0,15 mm pour les très grandes échelles.
Le rendu Python de repli utilise la même règle.

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
