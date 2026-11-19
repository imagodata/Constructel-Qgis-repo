<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering" hasScaleBasedVisibilityFlag="1" minScale="100000" maxScale="1" labelsEnabled="0">
  <!--
    osiris_chantiers_autorises.qml - Style QGIS pour les chantiers autorises OSIRIS
    Couche source: osiris.v_chantiers_proches ou osiris.chantiers_autorises

    Categorise par procedure, sur les codes reellement importes d'OSIRIS
    (A, E, PCA, CA ; constat prod du 18/11/2026). Libelles : docs/integrations/OSIRIS_BRUSSELS.md §4.1-4.2.
    Les anciennes categories OSIRIS / OSIRIS_LIGHT / URGENCE etaient le
    vocabulaire des dossiers Farois (chantier.*), jamais present ici.
  -->
  <renderer-v2 type="categorizedSymbol" attr="procedure" symbollevels="0" enableorderby="0">
    <categories>
      <category value="A" symbol="0" label="A — Autorisation" render="true"/>
      <category value="E" symbol="2" label="E — Exemption (OSIRIS Light)" render="true"/>
      <category value="PCA" symbol="1" label="PCA — Programmation + CA" render="true"/>
      <category value="CA" symbol="3" label="CA — Coordination + Autorisation" render="true"/>
      <category value="" symbol="4" label="Autre / non renseigné" render="true"/>
    </categories>
    <symbols>
      <!-- A (autorisation): vert -->
      <symbol type="fill" name="0" alpha="0.5">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="50,180,50,80"/>
            <Option type="QString" name="outline_color" value="30,140,30,200"/>
            <Option type="QString" name="outline_width" value="0.5"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- PCA: bleu -->
      <symbol type="fill" name="1" alpha="0.5">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="50,100,200,80"/>
            <Option type="QString" name="outline_color" value="30,70,180,200"/>
            <Option type="QString" name="outline_width" value="0.5"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- E (exemption, OSIRIS Light): jaune-vert -->
      <symbol type="fill" name="2" alpha="0.5">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="180,200,50,80"/>
            <Option type="QString" name="outline_color" value="140,160,30,200"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- CA (coordination + autorisation): violet -->
      <symbol type="fill" name="3" alpha="0.5">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="150,80,190,70"/>
            <Option type="QString" name="outline_color" value="110,50,150,200"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- Autre: gris -->
      <symbol type="fill" name="4" alpha="0.4">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="160,160,160,60"/>
            <Option type="QString" name="outline_color" value="120,120,120,150"/>
            <Option type="QString" name="outline_width" value="0.3"/>
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
