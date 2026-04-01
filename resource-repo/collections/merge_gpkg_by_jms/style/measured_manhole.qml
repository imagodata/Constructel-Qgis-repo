<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Sketches">
  <!--
    Style categorise pour couches measured_pxs_fo_manhole_infra.
    Classification par champ feature_name : carres colores, taille 4.0, contour noir 0.3mm.
  -->
  <renderer-v2 type="categorizedSymbol" attr="feature_name" symbollevels="0" enableorderby="0">
    <categories>
      <category symbol="0" value="PXS_SMALL BAC ZTTH-4 CONCRETE" label="PXS_SMALL BAC ZTTH-4 CONCRETE"/>
      <category symbol="1" value="PXS_MOD BAC 1615X750X950" label="PXS_MOD BAC 1615X750X950"/>
      <category symbol="2" value="PXS_SMALL BAC MOD 1615X450X950" label="PXS_SMALL BAC MOD 1615X450X950"/>
      <category symbol="3" value="PXS_BIG BAC MOD 1600X750X950" label="PXS_BIG BAC MOD 1600X750X950"/>
      <category symbol="4" value="PXS_SMALL BAC MONO 1615X450X950" label="PXS_SMALL BAC MONO 1615X450X950"/>
    </categories>
    <symbols>
      <symbol name="0" type="marker" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" pass="0" locked="0" enabled="1">
          <prop k="name" v="square"/>
          <prop k="color" v="180,0,180,255"/>
          <prop k="size" v="4.0"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_width" v="0.3"/>
        </layer>
      </symbol>
      <symbol name="1" type="marker" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" pass="0" locked="0" enabled="1">
          <prop k="name" v="square"/>
          <prop k="color" v="0,150,130,255"/>
          <prop k="size" v="4.0"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_width" v="0.3"/>
        </layer>
      </symbol>
      <symbol name="2" type="marker" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" pass="0" locked="0" enabled="1">
          <prop k="name" v="square"/>
          <prop k="color" v="100,60,150,255"/>
          <prop k="size" v="4.0"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_width" v="0.3"/>
        </layer>
      </symbol>
      <symbol name="3" type="marker" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" pass="0" locked="0" enabled="1">
          <prop k="name" v="square"/>
          <prop k="color" v="200,80,0,255"/>
          <prop k="size" v="4.0"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_width" v="0.3"/>
        </layer>
      </symbol>
      <symbol name="4" type="marker" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" pass="0" locked="0" enabled="1">
          <prop k="name" v="square"/>
          <prop k="color" v="0,120,200,255"/>
          <prop k="size" v="4.0"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_width" v="0.3"/>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
</qgis>
