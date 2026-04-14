<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering">
  <!--
    osiris_frozen_zones.qml - Style QGIS pour les zones gelees OSIRIS
    Couche source: osiris.v_frozen_zones_actives

    Regles:
      1. ACTIF (gel en cours) : hachures rouges diagonales, bordure rouge epaisse
      2. FUTUR (gel a venir)  : hachures orange pointillees
      3. EXPIRE_RECENT (<30j) : gris transparent, bordure pointillee
  -->
  <renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="1" forceraster="0">
    <rules key="{root}">

      <!-- Regle 1: Zones gelees ACTIVES -->
      <rule key="{fz-actif}" filter="&quot;statut_gel&quot; = 'ACTIF'" label="Zone gelée ACTIVE" symbol="0" description="Gel en cours - travaux interdits">
      </rule>

      <!-- Regle 2: Zones gelees FUTURES -->
      <rule key="{fz-futur}" filter="&quot;statut_gel&quot; = 'FUTUR'" label="Zone gelée FUTURE" symbol="1" description="Gel a venir">
      </rule>

      <!-- Regle 3: Zones gelees EXPIREES recemment -->
      <rule key="{fz-expire}" filter="&quot;statut_gel&quot; = 'EXPIRE_RECENT'" label="Zone gelée expirée (&lt;30j)" symbol="2" scalemindenom="1" scalemaxdenom="50000" description="Gel expire depuis moins de 30 jours">
      </rule>

    </rules>
    <symbols>

      <!-- Symbol 0: ACTIF - Rouge hachure -->
      <symbol type="fill" name="0" alpha="1" clip_to_extent="1" force_rhr="0">
        <!-- Couche 1: Remplissage rouge semi-transparent -->
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="border_width_map_unit_scale" value="3x:0,0,0,0,0,0"/>
            <Option type="QString" name="color" value="220,40,40,50"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="outline_color" value="200,30,30,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.8"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
        <!-- Couche 2: Hachures diagonales rouges -->
        <layer class="LinePatternFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="angle" value="45"/>
            <Option type="QString" name="color" value="200,30,30,180"/>
            <Option type="QString" name="distance" value="4"/>
            <Option type="QString" name="distance_unit" value="MM"/>
            <Option type="QString" name="line_width" value="0.5"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="offset" value="0"/>
          </Option>
        </layer>
      </symbol>

      <!-- Symbol 1: FUTUR - Orange pointille -->
      <symbol type="fill" name="1" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="255,165,0,30"/>
            <Option type="QString" name="outline_color" value="255,140,0,200"/>
            <Option type="QString" name="outline_style" value="dash"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
        <layer class="LinePatternFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="angle" value="135"/>
            <Option type="QString" name="color" value="255,140,0,120"/>
            <Option type="QString" name="distance" value="5"/>
            <Option type="QString" name="distance_unit" value="MM"/>
            <Option type="QString" name="line_width" value="0.3"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
          </Option>
        </layer>
      </symbol>

      <!-- Symbol 2: EXPIRE_RECENT - Gris transparent -->
      <symbol type="fill" name="2" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="150,150,150,20"/>
            <Option type="QString" name="outline_color" value="120,120,120,100"/>
            <Option type="QString" name="outline_style" value="dot"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>

    </symbols>
  </renderer-v2>

  <!-- Labels -->
  <labeling type="rule-based">
    <rules key="{label-root}">
      <!-- Label zones actives -->
      <rule key="{label-actif}" filter="&quot;statut_gel&quot; = 'ACTIF'" scalemindenom="1" scalemaxdenom="25000">
        <settings calloutType="simple">
          <text-style fontFamily="Noto Sans" fontSize="8" fontWeight="75" textColor="180,30,30,255"
                      fieldName="'GEL ' || to_char(&quot;end_date&quot;, 'DD/MM/YYYY') || '\n' || &quot;jours_restants&quot; || 'j restants'"
                      isExpression="1" multilineAlign="1" previewBkgrdColor="255,255,255,255">
          </text-style>
          <text-buffer bufferDraw="1" bufferSize="1" bufferColor="255,255,255,200"/>
          <placement placement="0" dist="0"/>
        </settings>
      </rule>
      <!-- Label zones futures -->
      <rule key="{label-futur}" filter="&quot;statut_gel&quot; = 'FUTUR'" scalemindenom="1" scalemaxdenom="15000">
        <settings calloutType="simple">
          <text-style fontFamily="Noto Sans" fontSize="7" fontWeight="50" textColor="200,120,0,255"
                      fieldName="'Gel du ' || to_char(&quot;start_date&quot;, 'DD/MM/YYYY')"
                      isExpression="1">
          </text-style>
          <text-buffer bufferDraw="1" bufferSize="0.8" bufferColor="255,255,255,180"/>
          <placement placement="0" dist="0"/>
        </settings>
      </rule>
    </rules>
  </labeling>

  <!-- Rendering: scale-dependent visibility -->
  <rendering>
    <minScale>200000</minScale>
    <maxScale>1</maxScale>
  </rendering>

</qgis>
