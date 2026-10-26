<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Fields|Forms|MapTips|Rendering" hasScaleBasedVisibilityFlag="1" minScale="10000" maxScale="0">
  <!--
    trench_segments.qml - Segments de tranchee (genie civil), migration 475
    Couche source: wyre.trench_segments (calculee par ref.fn_trench_segments_rebuild)

    Regles par statut de genie civil, couleurs de ducts.qml :
      TODO        gris tirete          (a faire)
      CP          vert clair tirete    (planifie)
      CONSTRUCTED vert foret plein     (construit)
      AS_BUILT    vert fonce plein     (recole)
    Halo orange sous le trait quand review_reason est renseigne
    (NO_DUCT, PARALLEL_DUPLICATE, MIXED_DUCT_STATUS).
    Formulaire : seuls status et completion_date sont modifiables (droits SQL
    identiques : ftth_editor n'a l'UPDATE que sur ces deux colonnes).
  -->
  <renderer-v2 type="RuleRenderer" symbollevels="0" forceraster="0" enableorderby="0">
    <rules key="{trench-root}">
      <rule key="{trench-review}" label="A revoir (review_reason)" filter="&quot;review_reason&quot; IS NOT NULL" symbol="0"/>
      <rule key="{trench-todo}" label="TODO - a faire" filter="&quot;status&quot; = 'TODO'" symbol="1"/>
      <rule key="{trench-cp}" label="CP - planifie" filter="&quot;status&quot; = 'CP'" symbol="2"/>
      <rule key="{trench-constructed}" label="CONSTRUCTED - construit" filter="&quot;status&quot; = 'CONSTRUCTED'" symbol="3"/>
      <rule key="{trench-asbuilt}" label="AS_BUILT - recole" filter="&quot;status&quot; = 'AS_BUILT'" symbol="4"/>
      <rule key="{trench-else}" label="Autre statut" filter="ELSE" symbol="5"/>
    </rules>
    <symbols>
      <!-- A revoir : halo orange semi-transparent -->
      <symbol type="line" name="0" alpha="0.55" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="255,140,0,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="3.2"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <!-- TODO : gris tirete -->
      <symbol type="line" name="1" alpha="1" clip_to_extent="1" force_rhr="0">
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
      <!-- CP : vert clair tirete -->
      <symbol type="line" name="2" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleLine" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="line_color" value="102,187,106,255"/>
            <Option type="QString" name="line_style" value="dash"/>
            <Option type="QString" name="line_width" value="1.5"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <!-- CONSTRUCTED : liseré sombre + vert foret plein -->
      <symbol type="line" name="3" alpha="1" clip_to_extent="1" force_rhr="0">
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
      <!-- AS_BUILT : liseré sombre + vert fonce plein -->
      <symbol type="line" name="4" alpha="1" clip_to_extent="1" force_rhr="0">
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
            <Option type="QString" name="line_color" value="0,100,0,255"/>
            <Option type="QString" name="line_style" value="solid"/>
            <Option type="QString" name="line_width" value="1.5"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="capstyle" value="round"/>
            <Option type="QString" name="joinstyle" value="round"/>
          </Option>
        </layer>
      </symbol>
      <!-- Autre : magenta fin (statut inattendu) -->
      <symbol type="line" name="5" alpha="1" clip_to_extent="1" force_rhr="0">
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

  <!-- Etiquette : longueur, a grande echelle -->
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fontFamily="Noto Sans" fontSize="7" fontWeight="50" textColor="40,40,40,255"
                  fieldName="format_number(&quot;length_m&quot;, 1) || ' m'" isExpression="1"/>
      <text-buffer bufferDraw="1" bufferSize="0.8" bufferSizeUnits="MM" bufferColor="255,255,255,200"/>
      <placement placement="2" placementFlags="10" dist="1" distUnits="MM" repeatDistance="0"/>
      <rendering scaleVisibility="1" scaleMin="1" scaleMax="2000" obstacle="1"/>
    </settings>
  </labeling>

  <fieldConfiguration>
    <field name="status" configurationFlags="NoFlag">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option type="List" name="map">
              <Option type="Map"><Option type="QString" name="TODO - a faire" value="TODO"/></Option>
              <Option type="Map"><Option type="QString" name="CP - planifie" value="CP"/></Option>
              <Option type="Map"><Option type="QString" name="CONSTRUCTED - construit" value="CONSTRUCTED"/></Option>
              <Option type="Map"><Option type="QString" name="AS_BUILT - recole" value="AS_BUILT"/></Option>
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="completion_date" configurationFlags="NoFlag">
      <editWidget type="DateTime">
        <config>
          <Option type="Map">
            <Option type="bool" name="allow_null" value="true"/>
            <Option type="bool" name="calendar_popup" value="true"/>
            <Option type="QString" name="display_format" value="dd/MM/yyyy"/>
            <Option type="QString" name="field_format" value="yyyy-MM-dd"/>
            <Option type="bool" name="field_iso_format" value="false"/>
          </Option>
        </config>
      </editWidget>
    </field>
  </fieldConfiguration>

  <aliases>
    <alias field="id" index="0" name="Identifiant"/>
    <alias field="zone_pop_id" index="1" name="POP"/>
    <alias field="zone_mro_id" index="2" name="MRO"/>
    <alias field="length_m" index="3" name="Longueur (m)"/>
    <alias field="geom_fingerprint" index="4" name="Empreinte geometrique"/>
    <alias field="start_node_type" index="5" name="Extremite debut"/>
    <alias field="end_node_type" index="6" name="Extremite fin"/>
    <alias field="start_structure_id" index="7" name="Chambre debut"/>
    <alias field="end_structure_id" index="8" name="Chambre fin"/>
    <alias field="duct_count" index="9" name="Fourreaux"/>
    <alias field="duct_models" index="10" name="Modeles de fourreaux"/>
    <alias field="status" index="11" name="Statut genie civil"/>
    <alias field="transition_source" index="12" name="Source du statut"/>
    <alias field="completion_date" index="13" name="Date de construction"/>
    <alias field="review_reason" index="14" name="A revoir"/>
    <alias field="carried_from_id" index="15" name="Statut reporte de"/>
    <alias field="created_at" index="16" name="Cree le"/>
    <alias field="updated_at" index="17" name="Modifie le"/>
  </aliases>

  <editable>
    <field name="id" editable="0"/>
    <field name="zone_pop_id" editable="0"/>
    <field name="zone_mro_id" editable="0"/>
    <field name="length_m" editable="0"/>
    <field name="geom_fingerprint" editable="0"/>
    <field name="start_node_type" editable="0"/>
    <field name="end_node_type" editable="0"/>
    <field name="start_structure_id" editable="0"/>
    <field name="end_structure_id" editable="0"/>
    <field name="duct_count" editable="0"/>
    <field name="duct_models" editable="0"/>
    <field name="status" editable="1"/>
    <field name="transition_source" editable="0"/>
    <field name="completion_date" editable="1"/>
    <field name="review_reason" editable="0"/>
    <field name="carried_from_id" editable="0"/>
    <field name="created_at" editable="0"/>
    <field name="updated_at" editable="0"/>
  </editable>

  <mapTip enabled="1">[% "status" %] ([% "transition_source" %]) - [% format_number("length_m", 1) %] m - [% "duct_models" %][% CASE WHEN "review_reason" IS NOT NULL THEN ' - a revoir : ' || "review_reason" END %]</mapTip>
  <previewExpression>"status" || ' - ' || format_number("length_m", 1) || ' m'</previewExpression>
  <layerGeometryType>1</layerGeometryType>
</qgis>
