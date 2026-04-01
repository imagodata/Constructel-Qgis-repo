<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Sketches">
  <!--
    Exemple de style QML pour couches cadastrales.
    Exportez vos styles depuis QGIS :
      Clic droit sur la couche > Properties > Sketches > Style > Save Style...
    Puis placez le fichier .qml ici.
  -->
  <renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0">
    <symbols>
      <symbol name="0" type="fill" alpha="0.5" clip_to_extent="1">
        <layer class="SimpleFill" pass="0" locked="0" enabled="1">
          <prop k="color" v="255,255,204,128"/>
          <prop k="style" v="solid"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_width" v="0.26"/>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
</qgis>
