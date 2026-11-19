<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering" hasScaleBasedVisibilityFlag="1" minScale="100000" maxScale="1" labelsEnabled="0">
  <!--
    osiris_phases_in_progress.qml - Phases de chantier en cours OSIRIS
    Couche source: osiris.phases_in_progress

    Categorise par status_fr, sur les valeurs reellement importees (prod
    18/11/2026) : Autorisée, En exécution, et trois etapes d'instruction
    (Passage chez l'administrateur, Passage en CCC, Passage en sCCC),
    meme rendu orange mais un symbole par categorie (2, 4, 5).
    Retirees : « Vergund » (libelle NL, jamais dans status_fr), « En cours »
    et « Avis flash » (aucune occurrence). Toute autre valeur -> « Autre ».
  -->
  <renderer-v2 type="categorizedSymbol" attr="status_fr" symbollevels="0">
    <categories>
      <category value="Autorisée" symbol="0" label="Autorisée" render="true"/>
      <category value="En exécution" symbol="1" label="En exécution" render="true"/>
      <category value="Passage chez l'administrateur" symbol="2" label="Passage chez l'administrateur" render="true"/>
      <category value="Passage en CCC" symbol="4" label="Passage en CCC" render="true"/>
      <category value="Passage en sCCC" symbol="5" label="Passage en sCCC" render="true"/>
      <category value="" symbol="3" label="Autre" render="true"/>
    </categories>
    <symbols>
      <!-- Autorisée: jaune -->
      <symbol type="fill" name="0" alpha="0.6">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="255,200,50,70"/>
            <Option type="QString" name="outline_color" value="200,160,30,200"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.5"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- En exécution: bleu -->
      <symbol type="fill" name="1" alpha="0.6">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="50,120,220,70"/>
            <Option type="QString" name="outline_color" value="30,80,200,200"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- Instruction en cours (administrateur, CCC, sCCC): orange, contour tirete -->
      <symbol type="fill" name="2" alpha="0.6">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="255,120,30,80"/>
            <Option type="QString" name="outline_color" value="230,90,10,200"/>
            <Option type="QString" name="outline_style" value="dash"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- Autre: gris -->
      <symbol type="fill" name="3" alpha="0.4">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="160,160,160,50"/>
            <Option type="QString" name="outline_color" value="120,120,120,150"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- Passage en CCC : meme rendu que le symbole 2. QGIS attribue un symbole
           par categorie (symbolMap.take) : un nom de symbole partage n'est servi
           qu'a la premiere categorie, les suivantes sont retirees au chargement. -->
      <symbol type="fill" name="4" alpha="0.6">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="255,120,30,80"/>
            <Option type="QString" name="outline_color" value="230,90,10,200"/>
            <Option type="QString" name="outline_style" value="dash"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- Passage en sCCC : meme rendu que le symbole 2 -->
      <symbol type="fill" name="5" alpha="0.6">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="255,120,30,80"/>
            <Option type="QString" name="outline_color" value="230,90,10,200"/>
            <Option type="QString" name="outline_style" value="dash"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>

  <!-- Visibilite par echelle : attributs de <qgis> (hasScaleBasedVisibilityFlag /
       minScale / maxScale)  seule forme lue par QGIS. L'ancien bloc
       <rendering><minScale>100000</minScale></rendering> etait ignore (couche
       visible a toutes les echelles). Seuil inchange : 1:100 000. -->
</qgis>
