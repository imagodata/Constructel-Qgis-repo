<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering" hasScaleBasedVisibilityFlag="1" minScale="100000" maxScale="1" labelsEnabled="0">
  <!--
    osiris_deviations.qml - Lignes de deviation routiere OSIRIS
    Couche source: osiris.deviations
    Style: lignes jaune-orange epaisses pointillees
  -->
  <renderer-v2 type="singleSymbol" symbollevels="0">
    <symbols>
      <symbol type="line" name="0" alpha="0.8">
        <layer class="SimpleLine" enabled="1">
          <Option type="Map">
            <Option type="QString" name="line_color" value="255,180,30,200"/>
            <Option type="QString" name="line_style" value="dash"/>
            <Option type="QString" name="line_width" value="1.2"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
        <!-- Fleches directionnelles -->
        <layer class="MarkerLine" enabled="1">
          <Option type="Map">
            <Option type="QString" name="interval" value="15"/>
            <Option type="QString" name="interval_unit" value="MM"/>
            <Option type="QString" name="placement" value="interval"/>
          </Option>
          <symbol type="marker" name="@0@1" alpha="0.7">
            <layer class="SimpleMarker" enabled="1">
              <Option type="Map">
                <Option type="QString" name="name" value="arrowhead"/>
                <Option type="QString" name="color" value="255,160,20,180"/>
                <Option type="QString" name="size" value="3"/>
                <Option type="QString" name="size_unit" value="MM"/>
                <Option type="QString" name="angle" value="0"/>
              </Option>
            </layer>
          </symbol>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <!-- Visibilite par echelle : attributs de <qgis> (hasScaleBasedVisibilityFlag /
       minScale / maxScale)  seule forme lue par QGIS. L'ancien bloc
       <rendering><minScale>100000</minScale></rendering> etait ignore (couche
       visible a toutes les echelles). Seuil inchange : 1:100 000. -->
</qgis>
