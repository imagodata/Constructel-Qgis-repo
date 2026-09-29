<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!-- Connecteurs As-Built : ligne fine en pointillé court du point géocodé vers
     l'extrémité de son segment (axe décalé). Couleurs = depth_category.qml. -->
<qgis version="3.44.6-Solothurn" styleCategories="Symbology">
  <renderer-v2 forceraster="0" symbollevels="0" enableorderby="0" referencescale="-1" type="categorizedSymbol" attr="depth_category">
    <categories>
      <category value="vert" label="Vert — conforme (≥ 55 cm)" symbol="0" render="true" type="string"/>
      <category value="orange" label="Orange — limite (50–55 cm)" symbol="1" render="true" type="string"/>
      <category value="rouge" label="Rouge — non conforme (&lt; 50 cm)" symbol="2" render="true" type="string"/>
      <category value="manquante" label="Manquante — non mesurée" symbol="3" render="true" type="string"/>
    </categories>
    <symbols>
      <symbol alpha="0.85" clip_to_extent="1" frame_rate="10" name="0" is_animated="0" type="line" force_rhr="0">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" name="name" type="QString"/>
            <Option name="properties"/>
            <Option value="collection" name="type" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleLine" locked="0" pass="0" enabled="1">
          <Option type="Map">
            <Option value="0" name="align_dash_pattern" type="QString"/>
            <Option value="flat" name="capstyle" type="QString"/>
            <Option value="1;1.2" name="customdash" type="QString"/>
            <Option value="MM" name="customdash_unit" type="QString"/>
            <Option value="round" name="joinstyle" type="QString"/>
            <Option value="42,157,61,255" name="line_color" type="QString"/>
            <Option value="solid" name="line_style" type="QString"/>
            <Option value="0.35" name="line_width" type="QString"/>
            <Option value="MM" name="line_width_unit" type="QString"/>
            <Option value="0" name="offset" type="QString"/>
            <Option value="MM" name="offset_unit" type="QString"/>
            <Option value="1" name="use_custom_dash" type="QString"/>
          </Option>
        </layer>
      </symbol>
      <symbol alpha="0.85" clip_to_extent="1" frame_rate="10" name="1" is_animated="0" type="line" force_rhr="0">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" name="name" type="QString"/>
            <Option name="properties"/>
            <Option value="collection" name="type" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleLine" locked="0" pass="0" enabled="1">
          <Option type="Map">
            <Option value="0" name="align_dash_pattern" type="QString"/>
            <Option value="flat" name="capstyle" type="QString"/>
            <Option value="1;1.2" name="customdash" type="QString"/>
            <Option value="MM" name="customdash_unit" type="QString"/>
            <Option value="round" name="joinstyle" type="QString"/>
            <Option value="255,127,0,255" name="line_color" type="QString"/>
            <Option value="solid" name="line_style" type="QString"/>
            <Option value="0.35" name="line_width" type="QString"/>
            <Option value="MM" name="line_width_unit" type="QString"/>
            <Option value="0" name="offset" type="QString"/>
            <Option value="MM" name="offset_unit" type="QString"/>
            <Option value="1" name="use_custom_dash" type="QString"/>
          </Option>
        </layer>
      </symbol>
      <symbol alpha="0.85" clip_to_extent="1" frame_rate="10" name="2" is_animated="0" type="line" force_rhr="0">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" name="name" type="QString"/>
            <Option name="properties"/>
            <Option value="collection" name="type" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleLine" locked="0" pass="0" enabled="1">
          <Option type="Map">
            <Option value="0" name="align_dash_pattern" type="QString"/>
            <Option value="flat" name="capstyle" type="QString"/>
            <Option value="1;1.2" name="customdash" type="QString"/>
            <Option value="MM" name="customdash_unit" type="QString"/>
            <Option value="round" name="joinstyle" type="QString"/>
            <Option value="255,35,35,255" name="line_color" type="QString"/>
            <Option value="solid" name="line_style" type="QString"/>
            <Option value="0.35" name="line_width" type="QString"/>
            <Option value="MM" name="line_width_unit" type="QString"/>
            <Option value="0" name="offset" type="QString"/>
            <Option value="MM" name="offset_unit" type="QString"/>
            <Option value="1" name="use_custom_dash" type="QString"/>
          </Option>
        </layer>
      </symbol>
      <symbol alpha="0.85" clip_to_extent="1" frame_rate="10" name="3" is_animated="0" type="line" force_rhr="0">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" name="name" type="QString"/>
            <Option name="properties"/>
            <Option value="collection" name="type" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleLine" locked="0" pass="0" enabled="1">
          <Option type="Map">
            <Option value="0" name="align_dash_pattern" type="QString"/>
            <Option value="flat" name="capstyle" type="QString"/>
            <Option value="1;1.2" name="customdash" type="QString"/>
            <Option value="MM" name="customdash_unit" type="QString"/>
            <Option value="round" name="joinstyle" type="QString"/>
            <Option value="153,153,153,255" name="line_color" type="QString"/>
            <Option value="solid" name="line_style" type="QString"/>
            <Option value="0.35" name="line_width" type="QString"/>
            <Option value="MM" name="line_width_unit" type="QString"/>
            <Option value="0" name="offset" type="QString"/>
            <Option value="MM" name="offset_unit" type="QString"/>
            <Option value="1" name="use_custom_dash" type="QString"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
    <rotation/>
    <sizescale/>
  </renderer-v2>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerGeometryType>1</layerGeometryType>
</qgis>
