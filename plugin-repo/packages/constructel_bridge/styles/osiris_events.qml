<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering">
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

  <labeling type="simple">
    <settings>
      <text-style fontFamily="Noto Sans" fontSize="7" fontWeight="50" textColor="0,160,180,255"
                  fontItalic="1"
                  fieldName="name_fr" isExpression="0">
      </text-style>
      <text-buffer bufferDraw="1" bufferSize="0.8" bufferColor="255,255,255,200"/>
      <placement placement="0" dist="0"/>
      <rendering scaleMin="1" scaleMax="20000" scaleVisibility="1"/>
    </settings>
  </labeling>

  <rendering>
    <minScale>100000</minScale>
    <maxScale>1</maxScale>
  </rendering>
</qgis>
