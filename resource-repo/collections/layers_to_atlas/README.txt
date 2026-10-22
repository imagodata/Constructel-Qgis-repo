Layers to Atlas — Atlas PDF
Collection QGIS Resource Sharing, version 1.2.0, cible QGIS 3.44 à 4.x.

Installer/mettre à jour cette collection dans QGIS Resource Sharing, puis ouvrir
la boîte à outils Processing : Scripts > Constructel > Layers to Atlas.
Après mise à jour, redémarrer QGIS si Processing conserve l'ancien script.
Le journal doit afficher « Layers to Atlas — version 1.2.0 ».

Utilisation par défaut
- Préparer la carte dans le projet QGIS : visibilité des couches et groupes,
  ordre de rendu, styles, étiquettes, filtres et règles d'échelle.
- Le périmètre est le canevas courant. Une sélection, une couche entière
  (filtre fournisseur respecté) ou une emprise restent disponibles.
- Choisir le format A3/A4 paysage, l'échelle, le titre et le fichier PDF.
- L'index est créé à côté du PDF : <nom>_plans.gpkg. Si le nom ou sa copie
  de logo existent, le script utilise un nouveau nom numéroté.
- Le dossier contenant le PDF s'ouvre après réussite, sur le poste QGIS.

La liste des couches reste vide par défaut : les couches visibles sont reprises
par le mécanisme natif QGIS, dans l'ordre du projet, y compris l'ordre personnalisé
et les groupes de rendu. Les fonds suivent leur visibilité, sans ajout de fond
masqué. Le CRS du projet est utilisé par défaut et doit être projeté en mètres ;
sinon choisir un CRS métrique dans les options avancées (EPSG:31370 en Belgique).

Sans choix explicite de couches, la mise en page ajoutée au projet continue de
suivre les couches, leur ordre et leurs styles après sauvegarde/réouverture.
Sa légende est synchronisée avec le projet. L'index ajouté au panneau Couches
fournit la grille ; sa visibilité dans la mise en page suit ce panneau.
Le PDF exporté reste un document fixe. Après modification du projet, vérifier
la place de la légende avant de réexporter la mise en page manuellement, ou
relancer le script pour refaire la validation complète de toutes les pages.

Options avancées
Les couches explicites, l'ajout facultatif des fonds visibles à ce choix, le
chemin de l'index, le CRS, la résolution, les pages, la légende, la grille,
le nord, la barre d'échelle, le cartouche, le logo et l'ouverture du dossier
se trouvent dans les options avancées. Un choix explicite fixe la liste des
couches dans l'ordre du projet au lancement, avec leurs styles courants.
Un chemin d'index explicite déjà utilisé est refusé. Sans interface QGIS,
choisir le mode Emprise ; aucun gestionnaire de fichiers n'est lancé.

Le script n'altère pas les données sources. L'export initial adapte les noms
longs de légende sur plusieurs lignes et essaie 8/7 pt sur 1/2 colonnes.
Une configuration doit tenir sur toutes les pages ; sinon l'export est refusé
avant écriture finale. Aucun PDF existant n'est remplacé en cas d'échec.
Enregistrer le projet et conserver les sources, l'index et la copie du logo.
Les fonds distants nécessitent leur accès réseau habituel.

Le logo SVG Constructel est fourni. Si Resource Sharing copie le script sans
le voisinage processing/../svg, choisir le SVG installé dans l'option Logo.
Le logo reste facultatif.

Recette Desktop : A3/A4, couches/groupes masqués, ordre personnalisé, styles
et étiquettes, légende avec noms longs/classes nombreuses, ouverture du dossier
activée/désactivée, réexécution avec index existant et réouverture du projet.
Vérifier aussi un échec d'export : PDF existant préservé, dossier non ouvert.
Les tests automatisés sans QGIS ne remplacent pas cette recette visuelle.
