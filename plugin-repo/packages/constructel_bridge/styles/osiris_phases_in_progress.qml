<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering">
  <!--
    osiris_phases_in_progress.qml - Phases de chantier en cours OSIRIS
    Couche source: osiris.phases_in_progress

    Categorise par status_fr (Autorisée, En cours, Avis flash).
  -->
  <renderer-v2 type="categorizedSymbol" attr="status_fr" symbollevels="0">
    <categories>
      <category value="Autorisée" symbol="0" label="Autorisée" render="true"/>
      <category value="Vergund" symbol="0" label="Vergund (Autorisée NL)" render="true"/>
      <category value="En cours" symbol="1" label="En cours" render="true"/>
      <category value="Avis flash" symbol="2" label="Avis flash" render="true"/>
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
      <!-- En cours: bleu -->
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
      <!-- Avis flash: orange vif -->
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
    </symbols>
  </renderer-v2>

  <!-- Labels: impetrant + phase_nr -->
  <labeling type="simple">
    <settings>
      <text-style fontFamily="Noto Sans" fontSize="7" fontWeight="50" textColor="40,40,40,255"
                  fieldName="impetrant_fr || ' (ph.' || phase_nr || ')'" isExpression="1">
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
