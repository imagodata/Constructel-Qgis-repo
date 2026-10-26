<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Fields|Forms|MapTips|Rendering" hasScaleBasedVisibilityFlag="1" minScale="10000" maxScale="0">
  <!--
    duct_progress.qml - Avancement des fourreaux (plan 2 lot 1, migration 480)
    Couche source: wyre.v_duct_progress (jointure ducts + duct_progress,
    calculee par ref.fn_duct_progress_refresh)

    Regles, couleurs de ducts.qml / trench_segments.qml :
      bloque            halo rouge sous le trait (blocked_reason renseigne :
                        IMPORT_ONLY, UNCOVERED, DUCT_AHEAD)
      termine           vert foret plein (statut CONSTRUCTED ou AS_BUILT)
      progress_pct = 0  gris tirete          (rien de construit)
      0 < pct < 100     orange + etiquette « pct % » (construit en partie)
    Formulaire : rien de modifiable (vue derivee, lecture seule en base).
  -->
  <renderer-v2 type="RuleRenderer" symbollevels="0" forceraster="0" enableorderby="0">
    <rules key="{progress-root}">
      <rule key="{progress-blocked}" label="Bloque (blocked_reason)" filter="&quot;blocked_reason&quot; IS NOT NULL" symbol="0"/>
      <rule key="{progress-done}" label="Termine" filter="&quot;status&quot; IN ('CONSTRUCTED', 'AS_BUILT')" symbol="1"/>
      <rule key="{progress-zero}" label="Rien de construit" filter="&quot;progress_pct&quot; = 0" symbol="2"/>
      <rule key="{progress-partial}" label="Construit en partie" filter="&quot;progress_pct&quot; &gt; 0 AND &quot;progress_pct&quot; &lt; 100" symbol="3"/>
      <rule key="{progress-else}" label="Autre" filter="ELSE" symbol="4"/>
    </rules>
    <symbols>
      <!-- Bloque : halo rouge semi-transparent -->
      <symbol type="line" name="0" alpha="0.55" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="220,20,20,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="3.2"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <!-- Termine : liseré sombre + vert foret plein -->
      <symbol type="line" name="1" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="35,35,35,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="2.3"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="34,139,34,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="1.5"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <!-- Rien de construit : gris tirete -->
      <symbol type="line" name="2" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="158,158,158,255"/>
            <Option type="QString" name="line_style" value="dash"/>
            <Option type="QString" name="line_width" value="1.5"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <!-- Construit en partie : orange -->
      <symbol type="line" name="3" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="255,140,0,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="1.5"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <!-- Autre : magenta fin (etat inattendu) -->
      <symbol type="line" name="4" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="200,0,200,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="0.8"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>

  <!-- Etiquette : pourcentage, fourreaux partiels, a grande echelle -->
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fontFamily="Noto Sans" fontSize="7" fontWeight="50" textColor="40,40,40,255"
                  fieldName="CASE WHEN &quot;progress_pct&quot; &gt; 0 AND &quot;progress_pct&quot; &lt; 100 THEN &quot;progress_pct&quot; || ' %' END" isExpression="1"/>
      <text-buffer bufferDraw="1" bufferSize="0.8" bufferSizeUnits="MM" bufferColor="255,255,255,200"/>
      <placement placement="2" placementFlags="10" dist="1" distUnits="MM" repeatDistance="0"/>
      <rendering scaleVisibility="1" scaleMin="1" scaleMax="2000" obstacle="1"/>
    </settings>
  </labeling>

  <fieldConfiguration>
  </fieldConfiguration>

  <aliases>
    <alias field="id" index="0" name="Fourreau"/>
    <alias field="zone_pop_id" index="1" name="POP"/>
    <alias field="zone_mro_id" index="2" name="MRO"/>
    <alias field="model" index="3" name="Modele"/>
    <alias field="status" index="4" name="Statut"/>
    <alias field="progress_pct" index="5" name="Avancement (%)"/>
    <alias field="built_m" index="6" name="Construit (m)"/>
    <alias field="length_m" index="7" name="Longueur (m)"/>
    <alias field="blocked_reason" index="8" name="Blocage"/>
    <alias field="computed_at" index="9" name="Calcule le"/>
  </aliases>

  <editable>
    <field name="id" editable="0"/>
    <field name="zone_pop_id" editable="0"/>
    <field name="zone_mro_id" editable="0"/>
    <field name="model" editable="0"/>
    <field name="status" editable="0"/>
    <field name="progress_pct" editable="0"/>
    <field name="built_m" editable="0"/>
    <field name="length_m" editable="0"/>
    <field name="blocked_reason" editable="0"/>
    <field name="computed_at" editable="0"/>
  </editable>

  <mapTip enabled="1">[% "model" %] [% "status" %] - [% "progress_pct" %] % ([% format_number("built_m", 1) %] / [% format_number("length_m", 1) %] m)[% CASE WHEN "blocked_reason" IS NOT NULL THEN ' - ' || "blocked_reason" END %]</mapTip>
  <previewExpression>"model" || ' - ' || "progress_pct" || ' %'</previewExpression>
  <layerGeometryType>1</layerGeometryType>
</qgis>
