<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering" hasScaleBasedVisibilityFlag="1" minScale="500000" maxScale="1" labelsEnabled="0">
  <!--
    osiris_hypercoordination.qml - Style QGIS pour les zones d'hypercoordination
    Couche source: osiris.hypercoordination_zones

    10 zones strategiques a Bruxelles ou la coordination est renforcee.
    Style: violet semi-transparent, bordure epaisse pointillee.
  -->
  <renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0" forceraster="0">
    <symbols>
      <symbol type="fill" name="0" alpha="1" clip_to_extent="1" force_rhr="0">
        <!-- Remplissage violet transparent -->
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="128,0,128,35"/>
            <Option type="QString" name="outline_color" value="100,0,140,220"/>
            <Option type="QString" name="outline_style" value="dash"/>
            <Option type="QString" name="outline_width" value="1.0"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
        <!-- Hachures violettes croisees -->
        <layer class="LinePatternFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="angle" value="45"/>
            <Option type="QString" name="color" value="100,0,140,60"/>
            <Option type="QString" name="distance" value="6"/>
            <Option type="QString" name="distance_unit" value="MM"/>
            <Option type="QString" name="line_width" value="0.3"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
          </Option>
        </layer>
        <layer class="LinePatternFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="angle" value="135"/>
            <Option type="QString" name="color" value="100,0,140,60"/>
            <Option type="QString" name="distance" value="6"/>
            <Option type="QString" name="distance_unit" value="MM"/>
            <Option type="QString" name="line_width" value="0.3"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>

  <!-- Rendering: always visible (only 10 features) -->
  <!-- Visibilite par echelle : attributs de <qgis> (hasScaleBasedVisibilityFlag /
       minScale / maxScale)  seule forme lue par QGIS. L'ancien bloc
       <rendering><minScale>500000</minScale></rendering> etait ignore (couche
       visible a toutes les echelles). Seuil inchange : 1:500 000. -->

</qgis>
