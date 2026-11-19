<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering" hasScaleBasedVisibilityFlag="1" minScale="100000" maxScale="1" labelsEnabled="0">
  <!--
    osiris_events.qml - Evenements temporaires OSIRIS (manifestations, marches, festivals)
    Couche source: osiris.events
    Style: polygones cyan transparent avec icone evenement
  -->
  <renderer-v2 type="singleSymbol" symbollevels="0">
    <symbols>
      <symbol type="fill" name="0" alpha="0.5">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="0,200,220,40"/>
            <Option type="QString" name="outline_color" value="0,180,200,180"/>
            <Option type="QString" name="outline_style" value="dot"/>
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
