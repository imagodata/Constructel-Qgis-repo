<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering">
  <!--
    osiris_worksites.qml - Style QGIS pour tous les chantiers OSIRIS
    Couche source: osiris.worksites

    Categorise par procedure (OSIRIS, PCA, OSIRIS_LIGHT, URGENCE).
    Labels: impetrant + reference dossier.
  -->
  <renderer-v2 type="categorizedSymbol" attr="procedure" symbollevels="0" enableorderby="0">
    <categories>
      <category value="OSIRIS" symbol="0" label="OSIRIS (standard)" render="true"/>
      <category value="PCA" symbol="1" label="PCA (pre-chantier)" render="true"/>
      <category value="OSIRIS_LIGHT" symbol="2" label="OSIRIS Light" render="true"/>
      <category value="URGENCE" symbol="3" label="Urgence" render="true"/>
      <category value="" symbol="4" label="Autre" render="true"/>
    </categories>
    <symbols>
      <!-- OSIRIS: bleu -->
      <symbol type="fill" name="0" alpha="0.4">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="70,130,200,60"/>
            <Option type="QString" name="outline_color" value="40,90,160,180"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- PCA: vert -->
      <symbol type="fill" name="1" alpha="0.4">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="80,180,80,60"/>
            <Option type="QString" name="outline_color" value="40,130,40,180"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- OSIRIS_LIGHT: jaune -->
      <symbol type="fill" name="2" alpha="0.4">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="220,200,60,60"/>
            <Option type="QString" name="outline_color" value="180,160,30,180"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- URGENCE: rouge -->
      <symbol type="fill" name="3" alpha="0.5">
        <layer class="SimpleFill" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="220,60,60,80"/>
            <Option type="QString" name="outline_color" value="180,30,30,200"/>
            <Option type="QString" name="outline_width" value="0.5"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- Autre: gris -->
      <symbol type="fill" name="4" alpha="0.3">
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
    </symbols>
  </renderer-v2>

  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fieldName="imp_fr" fontSize="8" fontWeight="50" textColor="50,50,50,200">
        <text-buffer bufferSize="1" bufferColor="255,255,255,200" bufferDraw="1"/>
      </text-style>
      <placement placement="0" dist="0" priority="5" maxScale="0" minScale="25000"/>
    </settings>
  </labeling>

  <rendering maxScale="0" minScale="100000"/>
</qgis>
