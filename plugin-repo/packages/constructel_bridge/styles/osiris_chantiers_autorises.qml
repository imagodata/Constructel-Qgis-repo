<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering">
  <!--
    osiris_chantiers_autorises.qml - Style QGIS pour les chantiers autorises OSIRIS
    Couche source: osiris.v_chantiers_proches ou osiris.chantiers_autorises

    Categorise par procedure (OSIRIS, PCA, OSIRIS_LIGHT, URGENCE).
  -->
  <renderer-v2 type="categorizedSymbol" attr="procedure" symbollevels="0" enableorderby="0">
    <categories>
      <category value="OSIRIS" symbol="0" label="OSIRIS (standard)" render="true"/>
      <category value="PCA" symbol="1" label="PCA (pre-chantier)" render="true"/>
      <category value="OSIRIS_LIGHT" symbol="2" label="OSIRIS Light (simplifie)" render="true"/>
      <category value="URGENCE" symbol="3" label="Urgence" render="true"/>
      <category value="" symbol="4" label="Autre" render="true"/>
    </categories>
    <symbols>
      <!-- OSIRIS: vert -->
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
      <!-- OSIRIS_LIGHT: jaune-vert -->
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
      <!-- URGENCE: rouge-orange -->
      <symbol type="fill" name="3" alpha="0.5">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="255,80,30,80"/>
            <Option type="QString" name="outline_color" value="220,50,20,200"/>
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

  <!-- Labels -->
  <labeling type="simple">
    <settings>
      <text-style fontFamily="Noto Sans" fontSize="7" fontWeight="50" textColor="40,40,40,255"
                  fieldName="impetrant" isExpression="0">
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
