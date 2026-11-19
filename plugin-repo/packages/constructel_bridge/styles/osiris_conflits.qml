<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering" hasScaleBasedVisibilityFlag="1" minScale="100000" maxScale="1" labelsEnabled="0">
  <!--
    osiris_conflits.qml - Conflits zones gelees OSIRIS vs chantiers WYRE
    Couche source: osiris.v_conflits_zones_gelees

    Regles par severite:
      BLOQUANT     : rouge plein, bordure epaisse
      A_RISQUE     : orange hachure
      VIGILANCE    : jaune transparent
      INFO         : gris leger
  -->
  <renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="1" forceraster="0">
    <rules key="{root}">

      <rule key="{conf-bloquant}" filter="&quot;severite&quot; = 'BLOQUANT'" label="BLOQUANT — gel actif" symbol="0"
            description="Zone gelee active, travaux reseau bloques">
      </rule>

      <rule key="{conf-risque}" filter="&quot;severite&quot; = 'A_RISQUE'" label="A RISQUE — chevauchement temporel" symbol="1"
            description="Chevauchement dates WYRE/OSIRIS">
      </rule>

      <rule key="{conf-vigilance}" filter="&quot;severite&quot; = 'VIGILANCE'" label="VIGILANCE — gel expire &lt;30j" symbol="2"
            description="Gel expire depuis moins de 30 jours">
      </rule>

      <rule key="{conf-info}" filter="&quot;severite&quot; = 'INFO'" label="INFO" symbol="3"
            description="Conflit informatif, pas de blocage">
      </rule>

    </rules>
    <symbols>

      <!-- BLOQUANT: rouge plein + hachures -->
      <symbol type="fill" name="0" alpha="1" clip_to_extent="1">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="220,30,30,100"/>
            <Option type="QString" name="outline_color" value="180,0,0,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="1.0"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
        <layer class="LinePatternFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="angle" value="45"/>
            <Option type="QString" name="color" value="180,0,0,160"/>
            <Option type="QString" name="distance" value="3"/>
            <Option type="QString" name="distance_unit" value="MM"/>
            <Option type="QString" name="line_width" value="0.5"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
          </Option>
        </layer>
      </symbol>

      <!-- A_RISQUE: orange hachure -->
      <symbol type="fill" name="1" alpha="1" clip_to_extent="1">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="255,140,0,70"/>
            <Option type="QString" name="outline_color" value="220,100,0,220"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.7"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
        <layer class="LinePatternFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="angle" value="135"/>
            <Option type="QString" name="color" value="220,100,0,120"/>
            <Option type="QString" name="distance" value="4"/>
            <Option type="QString" name="distance_unit" value="MM"/>
            <Option type="QString" name="line_width" value="0.4"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
          </Option>
        </layer>
      </symbol>

      <!-- VIGILANCE: jaune transparent -->
      <symbol type="fill" name="2" alpha="1" clip_to_extent="1">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="255,220,50,50"/>
            <Option type="QString" name="outline_color" value="200,170,0,180"/>
            <Option type="QString" name="outline_style" value="dash"/>
            <Option type="QString" name="outline_width" value="0.5"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>

      <!-- INFO: gris leger -->
      <symbol type="fill" name="3" alpha="1" clip_to_extent="1">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="160,160,160,30"/>
            <Option type="QString" name="outline_color" value="120,120,120,120"/>
            <Option type="QString" name="outline_style" value="dot"/>
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
