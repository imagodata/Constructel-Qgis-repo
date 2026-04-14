<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering">
  <!--
    osiris_chantiers_proches.qml - Chantiers OSIRIS proches du reseau WYRE
    Couche source: osiris.v_chantiers_proches

    Graduated par dist_reseau_m (distance au reseau WYRE):
      < 50m    : rouge (impact direct)
      50-200m  : orange
      200-500m : jaune
      > 500m   : vert (eloigne)
  -->
  <renderer-v2 type="graduatedSymbol" attr="dist_reseau_m" symbollevels="0"
               graduatedMethod="GraduatedColor">
    <ranges>
      <range lower="0" upper="50" symbol="0" label="&lt; 50m (impact direct)" render="true"/>
      <range lower="50" upper="200" symbol="1" label="50 — 200m" render="true"/>
      <range lower="200" upper="500" symbol="2" label="200 — 500m" render="true"/>
      <range lower="500" upper="99999" symbol="3" label="&gt; 500m" render="true"/>
    </ranges>
    <symbols>
      <!-- < 50m: rouge -->
      <symbol type="fill" name="0" alpha="0.6">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="220,50,50,90"/>
            <Option type="QString" name="outline_color" value="180,20,20,220"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- 50-200m: orange -->
      <symbol type="fill" name="1" alpha="0.5">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="255,160,30,70"/>
            <Option type="QString" name="outline_color" value="220,120,0,200"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.5"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- 200-500m: jaune -->
      <symbol type="fill" name="2" alpha="0.4">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="255,220,50,50"/>
            <Option type="QString" name="outline_color" value="200,170,0,180"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- > 500m: vert -->
      <symbol type="fill" name="3" alpha="0.3">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="50,180,80,40"/>
            <Option type="QString" name="outline_color" value="30,140,50,150"/>
            <Option type="QString" name="outline_style" value="dash"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>

  <!-- Labels: impetrant + distance -->
  <labeling type="simple">
    <settings>
      <text-style fontFamily="Noto Sans" fontSize="7" fontWeight="50" textColor="40,40,40,255"
                  fieldName="coalesce(&quot;impetrant&quot;, '?') || '\n' || round(&quot;dist_reseau_m&quot;, 0) || 'm'"
                  isExpression="1" multilineAlign="1">
      </text-style>
      <text-buffer bufferDraw="1" bufferSize="0.8" bufferColor="255,255,255,200"/>
      <placement placement="0" dist="0"/>
      <rendering scaleMin="1" scaleMax="15000" scaleVisibility="1"/>
    </settings>
  </labeling>

  <rendering>
    <minScale>100000</minScale>
    <maxScale>1</maxScale>
  </rendering>

</qgis>
