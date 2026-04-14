<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44.6-Solothurn" styleCategories="AllStyleCategories" readOnly="0" autoRefreshTime="0" autoRefreshMode="Disabled" hasScaleBasedVisibilityFlag="0" minScale="1e+08" maxScale="0" symbologyReferenceScale="-1">
  <flags>
    <Identifiable>1</Identifiable>
    <Removable>1</Removable>
    <Searchable>1</Searchable>
    <Private>0</Private>
  </flags>
  <fieldConfiguration>
    <field name="id" configurationFlags="NoFlag">
      <editWidget type="Hidden"><config><Option/></config></editWidget>
    </field>
    <field name="structure_id" configurationFlags="NoFlag">
      <editWidget type="Hidden"><config><Option/></config></editWidget>
    </field>
    <field name="cable_id" configurationFlags="NoFlag">
      <editWidget type="Hidden"><config><Option/></config></editWidget>
    </field>
    <field name="cable_nomenclature" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config><Option type="Map">
          <Option name="IsMultiline" value="false" type="bool"/>
          <Option name="UseHtml" value="false" type="bool"/>
        </Option></config>
      </editWidget>
    </field>
    <field name="cable_cable_type" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config><Option type="Map">
          <Option name="IsMultiline" value="false" type="bool"/>
          <Option name="UseHtml" value="false" type="bool"/>
        </Option></config>
      </editWidget>
    </field>
    <field name="cable_status" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config><Option type="Map">
          <Option name="IsMultiline" value="false" type="bool"/>
          <Option name="UseHtml" value="false" type="bool"/>
        </Option></config>
      </editWidget>
    </field>
    <field name="continuity_type" configurationFlags="NoFlag">
      <editWidget type="ValueMap">
        <config><Option type="Map">
          <Option name="map" type="List">
            <Option type="Map"><Option name="PASS_THROUGH" value="PASS_THROUGH" type="QString"/></Option>
            <Option type="Map"><Option name="SPLICE_TO" value="SPLICE_TO" type="QString"/></Option>
            <Option type="Map"><Option name="TERMINAL (extrémité)" value="TERMINAL" type="QString"/></Option>
          </Option>
        </Option></config>
      </editWidget>
    </field>
    <field name="continues_as_cable_id" configurationFlags="NoFlag">
      <editWidget type="Hidden"><config><Option/></config></editWidget>
    </field>
    <field name="is_spliced" configurationFlags="NoFlag">
      <editWidget type="CheckBox">
        <config><Option type="Map">
          <Option name="CheckedState" value="true" type="QString"/>
          <Option name="UncheckedState" value="false" type="QString"/>
          <Option name="TextDisplayMethod" value="0" type="int"/>
        </Option></config>
      </editWidget>
    </field>
    <field name="spliced_by" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config><Option type="Map">
          <Option name="IsMultiline" value="false" type="bool"/>
          <Option name="UseHtml" value="false" type="bool"/>
        </Option></config>
      </editWidget>
    </field>
    <field name="splice_date" configurationFlags="NoFlag">
      <editWidget type="DateTime">
        <config><Option type="Map">
          <Option name="allow_null" value="true" type="bool"/>
          <Option name="calendar_popup" value="true" type="bool"/>
          <Option name="display_format" value="yyyy-MM-dd" type="QString"/>
          <Option name="field_format" value="yyyy-MM-dd" type="QString"/>
          <Option name="field_iso_format" value="false" type="bool"/>
        </Option></config>
      </editWidget>
    </field>
    <field name="notes" configurationFlags="NoFlag">
      <editWidget type="TextEdit">
        <config><Option type="Map">
          <Option name="IsMultiline" value="true" type="bool"/>
          <Option name="UseHtml" value="false" type="bool"/>
        </Option></config>
      </editWidget>
    </field>
    <field name="created_at" configurationFlags="NoFlag">
      <editWidget type="Hidden"><config><Option/></config></editWidget>
    </field>
    <field name="updated_at" configurationFlags="NoFlag">
      <editWidget type="Hidden"><config><Option/></config></editWidget>
    </field>
  </fieldConfiguration>
  <editform tolerant="1"></editform>
  <editforminit/>
  <editforminitcodesource>0</editforminitcodesource>
  <editforminitfilepath></editforminitfilepath>
  <editforminitcode><![CDATA[]]></editforminitcode>
  <featformsuppress>0</featformsuppress>
  <editorlayout>tablayout</editorlayout>
  <attributeEditorForm>
    <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
      <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
    </labelStyle>
    <!-- Onglet principal : action de soudure -->
    <attributeEditorContainer name="Soudure" type="Tab" groupBox="0" showLabel="1" columnCount="1"
        verticalStretch="0" horizontalStretch="1"
        collapsed="0" collapsedExpression="" collapsedExpressionEnabled="0"
        visibilityExpressionEnabled="0" visibilityExpression="">
      <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
        <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
      </labelStyle>
      <!-- Identification du cable (read-only) -->
      <attributeEditorContainer name="Cable" type="GroupBox" groupBox="1" showLabel="1" columnCount="2"
          verticalStretch="0" horizontalStretch="1"
          collapsed="0" collapsedExpression="" collapsedExpressionEnabled="0"
          visibilityExpressionEnabled="0" visibilityExpression="">
        <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
          <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
        </labelStyle>
        <attributeEditorField name="cable_nomenclature" showLabel="1" index="-1" verticalStretch="0" horizontalStretch="1">
          <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
            <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
          </labelStyle>
        </attributeEditorField>
        <attributeEditorField name="cable_cable_type" showLabel="1" index="-1" verticalStretch="0" horizontalStretch="1">
          <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
            <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
          </labelStyle>
        </attributeEditorField>
        <attributeEditorField name="cable_status" showLabel="1" index="-1" verticalStretch="0" horizontalStretch="1">
          <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
            <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
          </labelStyle>
        </attributeEditorField>
        <attributeEditorField name="continuity_type" showLabel="1" index="-1" verticalStretch="0" horizontalStretch="1">
          <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
            <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
          </labelStyle>
        </attributeEditorField>
      </attributeEditorContainer>
      <!-- Action soudure -->
      <attributeEditorContainer name="Etat soudure" type="GroupBox" groupBox="1" showLabel="1" columnCount="2"
          verticalStretch="0" horizontalStretch="1"
          collapsed="0" collapsedExpression="" collapsedExpressionEnabled="0"
          visibilityExpressionEnabled="0" visibilityExpression="">
        <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
          <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
        </labelStyle>
        <attributeEditorField name="is_spliced" showLabel="1" index="-1" verticalStretch="0" horizontalStretch="1">
          <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
            <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
          </labelStyle>
        </attributeEditorField>
        <attributeEditorField name="splice_date" showLabel="1" index="-1" verticalStretch="0" horizontalStretch="1">
          <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
            <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
          </labelStyle>
        </attributeEditorField>
        <attributeEditorField name="spliced_by" showLabel="1" index="-1" verticalStretch="0" horizontalStretch="1">
          <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
            <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
          </labelStyle>
        </attributeEditorField>
        <attributeEditorField name="notes" showLabel="1" index="-1" verticalStretch="0" horizontalStretch="2">
          <labelStyle overrideLabelColor="0" labelColor="" overrideLabelFont="0">
            <labelFont style="" description="MS Shell Dlg 2,8.3,-1,5,50,0,0,0,0,0" strikethrough="0" bold="0" underline="0" italic="0"/>
          </labelStyle>
        </attributeEditorField>
      </attributeEditorContainer>
    </attributeEditorContainer>
  </attributeEditorForm>
  <editable>
    <field name="id" editable="0"/>
    <field name="structure_id" editable="0"/>
    <field name="cable_id" editable="0"/>
    <field name="cable_nomenclature" editable="0"/>
    <field name="cable_cable_type" editable="0"/>
    <field name="cable_status" editable="0"/>
    <field name="continuity_type" editable="0"/>
    <field name="continues_as_cable_id" editable="0"/>
    <field name="is_spliced" editable="1"/>
    <field name="spliced_by" editable="1"/>
    <field name="splice_date" editable="1"/>
    <field name="notes" editable="1"/>
    <field name="created_at" editable="0"/>
    <field name="updated_at" editable="0"/>
  </editable>
  <labelOnTop>
    <field name="id" labelOnTop="0"/>
    <field name="structure_id" labelOnTop="0"/>
    <field name="cable_id" labelOnTop="0"/>
    <field name="cable_nomenclature" labelOnTop="0"/>
    <field name="cable_cable_type" labelOnTop="0"/>
    <field name="cable_status" labelOnTop="0"/>
    <field name="continuity_type" labelOnTop="0"/>
    <field name="continues_as_cable_id" labelOnTop="0"/>
    <field name="is_spliced" labelOnTop="0"/>
    <field name="spliced_by" labelOnTop="0"/>
    <field name="splice_date" labelOnTop="0"/>
    <field name="notes" labelOnTop="0"/>
    <field name="created_at" labelOnTop="0"/>
    <field name="updated_at" labelOnTop="0"/>
  </labelOnTop>
  <reuseLastValue>
    <field name="is_spliced" reuseLastValue="0"/>
    <field name="spliced_by" reuseLastValue="0"/>
    <field name="splice_date" reuseLastValue="0"/>
    <field name="notes" reuseLastValue="0"/>
  </reuseLastValue>
  <dataDefinedFieldProperties/>
  <widgets/>
  <previewExpression>COALESCE("cable_nomenclature", "cable_id")</previewExpression>
  <mapTip enabled="1"></mapTip>
  <actions>
    <actionsetting id="flash-cable-on-map" type="1" name="Flash cable sur la carte" shortTitle="Flash" icon="" action="
from qgis.core import QgsProject, QgsFeatureRequest
from qgis.utils import iface
from qgis.PyQt.QtGui import QColor
cable_id = '[% cable_id %]'
layers = QgsProject.instance().mapLayersByName('cables')
if not layers:
    iface.messageBar().pushWarning('Flash', 'Couche cables introuvable')
else:
    layer = layers[0]
    req = QgsFeatureRequest()
    req.setFilterExpression('id = \'%s\'' % cable_id)
    feats = [f.id() for f in layer.getFeatures(req)]
    if feats:
        iface.mapCanvas().flashFeatureIds(layer, feats, QColor('#FF6600'), QColor('#FFCC00'), 5, 1000)
    else:
        iface.messageBar().pushWarning('Flash', 'Cable %s non trouve dans cables' % cable_id)
" capture="0" showInAttributeTable="1" isEnabledOnlyWhenEditable="0">
      <actionScope id="Feature"/>
    </actionsetting>
  </actions>
  <layerGeometryType>4</layerGeometryType>
</qgis>
