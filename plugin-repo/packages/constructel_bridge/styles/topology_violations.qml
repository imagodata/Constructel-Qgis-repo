<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering">
  <!--
    topology_violations.qml - Style QGIS pour les violations topologiques
    Couche source: infra.topology_violations

    Categorise par severite (critical, error, warning).
  -->
  <renderer-v2 type="categorizedSymbol" attr="severity" symbollevels="0" enableorderby="0">
    <categories>
      <category value="critical" symbol="0" label="Critique" render="true"/>
      <category value="error" symbol="1" label="Erreur" render="true"/>
      <category value="warning" symbol="2" label="Avertissement" render="true"/>
      <category value="" symbol="3" label="Autre" render="true"/>
    </categories>
    <symbols>
      <!-- critical: rouge -->
      <symbol type="marker" name="0" alpha="1">
        <layer class="SimpleMarker" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="220,30,30,220"/>
            <Option type="QString" name="outline_color" value="150,0,0,255"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="size" value="3.5"/>
            <Option type="QString" name="size_unit" value="MM"/>
            <Option type="QString" name="name" value="cross2"/>
          </Option>
        </layer>
      </symbol>
      <!-- error: orange -->
      <symbol type="marker" name="1" alpha="1">
        <layer class="SimpleMarker" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="240,140,20,220"/>
            <Option type="QString" name="outline_color" value="180,100,0,255"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="size" value="3"/>
            <Option type="QString" name="size_unit" value="MM"/>
            <Option type="QString" name="name" value="triangle"/>
          </Option>
        </layer>
      </symbol>
      <!-- warning: jaune -->
      <symbol type="marker" name="2" alpha="1">
        <layer class="SimpleMarker" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="240,220,40,200"/>
            <Option type="QString" name="outline_color" value="180,160,0,255"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="size" value="2.5"/>
            <Option type="QString" name="size_unit" value="MM"/>
            <Option type="QString" name="name" value="diamond"/>
          </Option>
        </layer>
      </symbol>
      <!-- autre: gris -->
      <symbol type="marker" name="3" alpha="0.7">
        <layer class="SimpleMarker" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="160,160,160,150"/>
            <Option type="QString" name="outline_color" value="100,100,100,200"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="size" value="2"/>
            <Option type="QString" name="size_unit" value="MM"/>
            <Option type="QString" name="name" value="circle"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>

  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fieldName="violation_type" fontSize="7" fontWeight="50" textColor="80,30,30,200">
        <text-buffer bufferSize="0.8" bufferColor="255,255,255,200" bufferDraw="1"/>
      </text-style>
      <placement placement="0" dist="1.5" priority="3" maxScale="0" minScale="10000"/>
    </settings>
  </labeling>
</qgis>
