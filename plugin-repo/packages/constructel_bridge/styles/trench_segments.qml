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
    <field name="id" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field name="zone_pop_id" configurationFlags="NoFlag">
      <editWidget type="ValueRelation">
        <config>
          <Option type="Map">
            <Option name="AllowMulti" type="bool" value="false"/>
            <Option name="AllowNull" type="bool" value="true"/>
            <Option name="Key" type="QString" value="id"/>
            <Option name="Layer" type="invalid"/>
            <Option name="LayerName" type="QString" value="zone_pop"/>
            <Option name="LayerProviderName" type="QString" value="postgres"/>
            <Option name="OrderByKey" type="bool" value="false"/>
            <Option name="OrderByValue" type="bool" value="true"/>
            <Option name="UseCompleter" type="bool" value="true"/>
            <Option name="Value" type="QString" value="code"/>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="zone_mro_id" configurationFlags="NoFlag">
      <editWidget type="ValueRelation">
        <config>
          <Option type="Map">
            <Option name="AllowMulti" type="bool" value="false"/>
            <Option name="AllowNull" type="bool" value="true"/>
            <Option name="Key" type="QString" value="id"/>
            <Option name="Layer" type="invalid"/>
            <Option name="LayerName" type="QString" value="zone_mro"/>
            <Option name="LayerProviderName" type="QString" value="postgres"/>
            <Option name="OrderByKey" type="bool" value="false"/>
            <Option name="OrderByValue" type="bool" value="true"/>
            <Option name="UseCompleter" type="bool" value="true"/>
            <Option name="Value" type="QString" value="name"/>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="length_m" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field name="geom_fingerprint" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field name="start_node_type" configurationFlags="NoFlag">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option name="map" type="List">
              <Option type="Map">
                <Option name="🏗️ Chambre" type="QString" value="STRUCTURE"/>
              </Option>
              <Option type="Map">
                <Option name="🔀 Carrefour (3 segments ou plus)" type="QString" value="JUNCTION"/>
              </Option>
              <Option type="Map">
                <Option name="➖ Nœud (2 segments)" type="QString" value="NODE"/>
              </Option>
              <Option type="Map">
                <Option name="⏹️ Extrémité libre" type="QString" value="END"/>
              </Option>
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="end_node_type" configurationFlags="NoFlag">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option name="map" type="List">
              <Option type="Map">
                <Option name="🏗️ Chambre" type="QString" value="STRUCTURE"/>
              </Option>
              <Option type="Map">
                <Option name="🔀 Carrefour (3 segments ou plus)" type="QString" value="JUNCTION"/>
              </Option>
              <Option type="Map">
                <Option name="➖ Nœud (2 segments)" type="QString" value="NODE"/>
              </Option>
              <Option type="Map">
                <Option name="⏹️ Extrémité libre" type="QString" value="END"/>
              </Option>
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="start_structure_id" configurationFlags="NoFlag">
      <editWidget type="ValueRelation">
        <config>
          <Option type="Map">
            <Option name="AllowMulti" type="bool" value="false"/>
            <Option name="AllowNull" type="bool" value="true"/>
            <Option name="Key" type="QString" value="id"/>
            <Option name="Layer" type="invalid"/>
            <Option name="LayerName" type="QString" value="structures"/>
            <Option name="LayerProviderName" type="QString" value="postgres"/>
            <Option name="OrderByKey" type="bool" value="false"/>
            <Option name="OrderByValue" type="bool" value="true"/>
            <Option name="UseCompleter" type="bool" value="true"/>
            <Option name="Value" type="QString" value="nomenclature"/>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="end_structure_id" configurationFlags="NoFlag">
      <editWidget type="ValueRelation">
        <config>
          <Option type="Map">
            <Option name="AllowMulti" type="bool" value="false"/>
            <Option name="AllowNull" type="bool" value="true"/>
            <Option name="Key" type="QString" value="id"/>
            <Option name="Layer" type="invalid"/>
            <Option name="LayerName" type="QString" value="structures"/>
            <Option name="LayerProviderName" type="QString" value="postgres"/>
            <Option name="OrderByKey" type="bool" value="false"/>
            <Option name="OrderByValue" type="bool" value="true"/>
            <Option name="UseCompleter" type="bool" value="true"/>
            <Option name="Value" type="QString" value="nomenclature"/>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="duct_count" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field name="duct_models" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field name="status" configurationFlags="NoFlag">
      <editWidget type="ValueRelation">
        <config>
          <Option type="Map">
            <Option name="AllowMulti" type="bool" value="false"/>
            <Option name="AllowNull" type="bool" value="false"/>
            <Option name="CompleterMatchFlags" type="int" value="2"/>
            <Option name="Description" type="invalid"/>
            <Option name="DisplayGroupName" type="bool" value="false"/>
            <Option name="FilterExpression" type="QString" value="&quot;category&quot; = 'status_trench_segments'"/>
            <Option name="Key" type="QString" value="code"/>
            <Option name="Layer" type="invalid"/>
            <Option name="LayerName" type="QString" value="v_form_lists"/>
            <Option name="LayerProviderName" type="QString" value="postgres"/>
            <Option name="LayerSource" type="QString" value="dbname='farois_ftth' host=192.168.160.31 port=5432 user='ftth_editor' sslmode=require key='rid' estimatedmetadata=true checkPrimaryKeyUnicity='0' table=&quot;ref&quot;.&quot;v_form_lists&quot;"/>
            <Option name="NofColumns" type="int" value="1"/>
            <Option name="OrderByDescending" type="bool" value="false"/>
            <Option name="OrderByField" type="bool" value="true"/>
            <Option name="OrderByFieldName" type="QString" value="sort_order"/>
            <Option name="OrderByKey" type="bool" value="false"/>
            <Option name="OrderByValue" type="bool" value="false"/>
            <Option name="UseCompleter" type="bool" value="false"/>
            <Option name="Value" type="QString" value="label_fr"/>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="transition_source" configurationFlags="NoFlag">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option name="map" type="List">
              <Option type="Map">
                <Option name="✏️ Saisie manuelle" type="QString" value="MANUAL"/>
              </Option>
              <Option type="Map">
                <Option name="📡 BEON" type="QString" value="BEON"/>
              </Option>
              <Option type="Map">
                <Option name="🤖 Automatique" type="QString" value="AUTO"/>
              </Option>
              <Option type="Map">
                <Option name="📥 Import (statuts Marlin)" type="QString" value="IMPORT"/>
              </Option>
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="completion_date" configurationFlags="NoFlag">
      <editWidget type="DateTime">
        <config>
          <Option type="Map">
            <Option name="allow_null" type="bool" value="true"/>
            <Option name="calendar_popup" type="bool" value="true"/>
            <Option name="display_format" type="QString" value="dd/MM/yyyy"/>
            <Option name="field_format" type="QString" value="yyyy-MM-dd"/>
            <Option name="field_format_overwrite" type="bool" value="false"/>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="review_reason" configurationFlags="NoFlag">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option name="map" type="List">
              <Option type="Map">
                <Option name="⚠️ Aucun fourreau rattaché" type="QString" value="NO_DUCT"/>
              </Option>
              <Option type="Map">
                <Option name="⚠️ Doublon parallèle" type="QString" value="PARALLEL_DUPLICATE"/>
              </Option>
              <Option type="Map">
                <Option name="⚠️ Statuts de fourreaux mélangés" type="QString" value="MIXED_DUCT_STATUS"/>
              </Option>
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="carried_from_id" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field name="created_at" configurationFlags="NoFlag">
      <editWidget type="DateTime">
        <config>
          <Option type="Map">
            <Option name="allow_null" type="bool" value="true"/>
            <Option name="calendar_popup" type="bool" value="false"/>
            <Option name="display_format" type="QString" value="dd/MM/yyyy HH:mm"/>
            <Option name="field_format" type="QString" value="yyyy-MM-dd HH:mm:ss"/>
            <Option name="field_format_overwrite" type="bool" value="false"/>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="updated_at" configurationFlags="NoFlag">
      <editWidget type="DateTime">
        <config>
          <Option type="Map">
            <Option name="allow_null" type="bool" value="true"/>
            <Option name="calendar_popup" type="bool" value="false"/>
            <Option name="display_format" type="QString" value="dd/MM/yyyy HH:mm"/>
            <Option name="field_format" type="QString" value="yyyy-MM-dd HH:mm:ss"/>
            <Option name="field_format_overwrite" type="bool" value="false"/>
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

  <!-- Formulaire calque sur ducts.qml : memes onglets et groupes ; colonnes NOT NULL en texte (PR #1029) -->
  <editform tolerant="1"></editform>
  <editforminit/>
  <editforminitcodesource>0</editforminitcodesource>
  <featformsuppress>0</featformsuppress>
  <editorlayout>tablayout</editorlayout>
  <attributeEditorForm>
    <attributeEditorContainer name="General" type="Tab" groupBox="0" columnCount="1" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
      <attributeEditorContainer name="⚡ Actions Terrain" type="GroupBox" groupBox="1" columnCount="2" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
        <attributeEditorField name="status" index="11" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
      </attributeEditorContainer>
      <attributeEditorContainer name="📅 Dates" type="GroupBox" groupBox="1" columnCount="3" showLabel="1" collapsed="0" visibilityExpressionEnabled="1" visibilityExpression="&quot;status&quot; IN ('CONSTRUCTED', 'AS_BUILT') OR &quot;completion_date&quot; IS NOT NULL" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
        <attributeEditorField name="completion_date" index="13" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
      </attributeEditorContainer>
      <attributeEditorContainer name="⚠️ À revoir" type="GroupBox" groupBox="1" columnCount="2" showLabel="1" collapsed="0" visibilityExpressionEnabled="1" visibilityExpression="&quot;review_reason&quot; IS NOT NULL" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
        <attributeEditorField name="review_reason" index="14" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
      </attributeEditorContainer>
    </attributeEditorContainer>
    <attributeEditorContainer name="🔧 Technique" type="Tab" groupBox="0" columnCount="1" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
      <attributeEditorContainer name="🔀 Extrémités" type="GroupBox" groupBox="1" columnCount="2" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
        <attributeEditorTextElement name="Extremite debut" showLabel="1" horizontalStretch="0" verticalStretch="0">[% represent_value("start_node_type") %]</attributeEditorTextElement>
        <attributeEditorField name="start_structure_id" index="7" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
        <attributeEditorTextElement name="Extremite fin" showLabel="1" horizontalStretch="0" verticalStretch="0">[% represent_value("end_node_type") %]</attributeEditorTextElement>
        <attributeEditorField name="end_structure_id" index="8" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
      </attributeEditorContainer>
      <attributeEditorContainer name="📏 Dimensions" type="GroupBox" groupBox="1" columnCount="2" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
        <attributeEditorTextElement name="Longueur (m)" showLabel="1" horizontalStretch="0" verticalStretch="0">[% format_number("length_m", 1) %]</attributeEditorTextElement>
        <attributeEditorTextElement name="Fourreaux" showLabel="1" horizontalStretch="0" verticalStretch="0">[% "duct_count" %]</attributeEditorTextElement>
        <attributeEditorField name="duct_models" index="10" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
      </attributeEditorContainer>
    </attributeEditorContainer>
    <attributeEditorContainer name="📍 Localisation" type="Tab" groupBox="0" columnCount="1" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
      <attributeEditorContainer name="🗺️ Zones" type="GroupBox" groupBox="1" columnCount="2" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
        <attributeEditorField name="zone_pop_id" index="1" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
        <attributeEditorField name="zone_mro_id" index="2" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
      </attributeEditorContainer>
    </attributeEditorContainer>
    <attributeEditorContainer name="ℹ️ Info" type="Tab" groupBox="0" columnCount="1" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
      <attributeEditorContainer name="🔑 IDs" type="GroupBox" groupBox="1" columnCount="2" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
        <attributeEditorTextElement name="Empreinte geometrique" showLabel="1" horizontalStretch="0" verticalStretch="0">[% "geom_fingerprint" %]</attributeEditorTextElement>
        <attributeEditorField name="carried_from_id" index="15" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
      </attributeEditorContainer>
      <attributeEditorContainer name="💾 Source &amp; Audit" type="GroupBox" groupBox="1" columnCount="2" showLabel="1" collapsed="0" visibilityExpressionEnabled="0" visibilityExpression="" collapsedExpressionEnabled="0" collapsedExpression="" horizontalStretch="0" verticalStretch="0">
        <attributeEditorTextElement name="Source du statut" showLabel="1" horizontalStretch="0" verticalStretch="0">[% represent_value("transition_source") %]</attributeEditorTextElement>
        <attributeEditorField name="created_at" index="16" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
        <attributeEditorField name="updated_at" index="17" showLabel="1" horizontalStretch="0" verticalStretch="0"/>
      </attributeEditorContainer>
    </attributeEditorContainer>
  </attributeEditorForm>

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

  <mapTip enabled="1">&lt;div style="font-family:Arial;font-size:11px;background:#e6f3ff;padding:8px;border-radius:6px;border:1px solid #4a90d9;">&lt;strong&gt;[% "status" %]&lt;/strong&gt; ([% represent_value("transition_source") %])&lt;br/&gt;Long: [% format_number("length_m", 1) %] m&lt;br/&gt;Fourreaux: [% "duct_count" %][% CASE WHEN "duct_models" IS NOT NULL THEN ' (' || "duct_models" || ')' END %][% CASE WHEN "review_reason" IS NOT NULL THEN '&lt;br/&gt;&lt;span style="color:#E65100;font-weight:bold;"&gt;' || represent_value("review_reason") || '&lt;/span&gt;' END %]&lt;/div&gt;</mapTip>
  <previewExpression>"status" || ' - ' || format_number("length_m", 1) || ' m'</previewExpression>
  <layerGeometryType>1</layerGeometryType>
</qgis>
