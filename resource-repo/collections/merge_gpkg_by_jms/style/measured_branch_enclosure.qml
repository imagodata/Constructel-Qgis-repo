<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Sketches">
  <!--
    Style categorise pour couches measured_pxs_fo_branch_enclosure_infra.
    Classification par champ feature_name : cercles colores, taille 3.5, contour noir 0.3mm.
  -->
  <renderer-v2 type="categorizedSymbol" attr="feature_name" symbollevels="0" enableorderby="0">
    <categories>
      <category symbol="0" value="PXS_DTP-X" label="PXS_DTP-X"/>
      <category symbol="1" value="PXS_DTP-X400 HANDHOLE" label="PXS_DTP-X400 HANDHOLE"/>
      <category symbol="2" value="PXS_T-BRANCH SRV" label="PXS_T-BRANCH SRV"/>
    </categories>
    <symbols>
      <symbol name="0" type="marker" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" pass="0" locked="0" enabled="1">
          <prop k="name" v="circle"/>
          <prop k="color" v="0,100,255,255"/>
          <prop k="size" v="3.5"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_width" v="0.3"/>
        </layer>
      </symbol>
      <symbol name="1" type="marker" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" pass="0" locked="0" enabled="1">
          <prop k="name" v="circle"/>
          <prop k="color" v="34,180,34,255"/>
          <prop k="size" v="3.5"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_width" v="0.3"/>
        </layer>
      </symbol>
      <symbol name="2" type="marker" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" pass="0" locked="0" enabled="1">
          <prop k="name" v="circle"/>
          <prop k="color" v="255,140,0,255"/>
          <prop k="size" v="3.5"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_width" v="0.3"/>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
</qgis>
