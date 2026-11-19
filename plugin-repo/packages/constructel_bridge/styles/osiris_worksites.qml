<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering" hasScaleBasedVisibilityFlag="1" minScale="100000" maxScale="1" labelsEnabled="0">
  <!--
    osiris_worksites.qml - Style QGIS pour tous les chantiers OSIRIS
    Couche source: osiris.worksites

    Categorise par procedure, sur les codes reellement importes d'OSIRIS
    (A, E, PCA, CA, AVIS ; constat prod du 18/11/2026). Libelles : docs/integrations/OSIRIS_BRUSSELS.md §4.1-4.2.
    AVIS n'y est pas documente : libelle = code brut (a confirmer).
    Les anciennes categories OSIRIS / OSIRIS_LIGHT / URGENCE etaient le
    vocabulaire des dossiers Farois (chantier.*), jamais present ici.
    Aucune etiquette (decision Simon du 19/11/2026) : labelsEnabled="0".

    Rendu par regles (PR #1361, demande Simon du 18/11/2026) :
      - groupe « Procédure » : une regle par code (A, E, PCA, CA, AVIS) et une
        regle ELSE « Autre / non renseigné », un symbole distinct par regle.
        Le groupe isole le ELSE : il ne se compare qu'a ses soeurs, donc un
        chantier P1 garde son remplissage de procedure ;
      - regle « Urgent (P1) », soeur du groupe donc NON exclusive :
        "urgence" = 'P1' (14 643 en prod), contour rouge epais sans
        remplissage, dessine AU-DESSUS des remplissages (niveaux de symboles
        actifs : remplissages pass=0, contour P1 pass=1). P2 (18) et NULL
        restent sans contour. Visible dans la legende.
    Champs lus : procedure, urgence -> uniquement osiris.worksites
    (tests/unit/test_osiris_styles_fields.py).
  -->
  <renderer-v2 type="RuleRenderer" symbollevels="1" enableorderby="0" forceraster="0">
    <rules key="{ws-root}">
      <rule key="{ws-procedure}" label="Procédure">
        <rule key="{ws-proc-a}" filter="&quot;procedure&quot; = 'A'" label="A — Autorisation" symbol="0"/>
        <rule key="{ws-proc-e}" filter="&quot;procedure&quot; = 'E'" label="E — Exemption (OSIRIS Light)" symbol="2"/>
        <rule key="{ws-proc-pca}" filter="&quot;procedure&quot; = 'PCA'" label="PCA — Programmation + CA" symbol="1"/>
        <rule key="{ws-proc-ca}" filter="&quot;procedure&quot; = 'CA'" label="CA — Coordination + Autorisation" symbol="3"/>
        <rule key="{ws-proc-avis}" filter="&quot;procedure&quot; = 'AVIS'" label="AVIS" symbol="5"/>
        <rule key="{ws-proc-autre}" filter="ELSE" label="Autre / non renseigné" symbol="4"/>
      </rule>
      <rule key="{ws-urgence-p1}" filter="&quot;urgence&quot; = 'P1'" label="Urgent (P1)" symbol="6" description="Chantier OSIRIS urgent P1 : contour seul, au-dessus du remplissage"/>
    </rules>
    <symbols>
      <!-- A (autorisation): bleu -->
      <symbol type="fill" name="0" alpha="0.4">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="70,130,200,60"/>
            <Option type="QString" name="outline_color" value="40,90,160,180"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- PCA: vert -->
      <symbol type="fill" name="1" alpha="0.4">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="80,180,80,60"/>
            <Option type="QString" name="outline_color" value="40,130,40,180"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- E (exemption, OSIRIS Light): jaune -->
      <symbol type="fill" name="2" alpha="0.4">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="220,200,60,60"/>
            <Option type="QString" name="outline_color" value="180,160,30,180"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- CA (coordination + autorisation): violet -->
      <symbol type="fill" name="3" alpha="0.5">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="150,80,190,70"/>
            <Option type="QString" name="outline_color" value="110,50,150,200"/>
            <Option type="QString" name="outline_width" value="0.5"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- Autre: gris -->
      <symbol type="fill" name="4" alpha="0.3">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="160,160,160,50"/>
            <Option type="QString" name="outline_color" value="120,120,120,150"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- AVIS: cyan -->
      <symbol type="fill" name="5" alpha="0.4">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="60,180,190,60"/>
            <Option type="QString" name="outline_color" value="30,130,140,180"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- Urgent (P1) : contour rouge vif 0.9 mm, sans remplissage, pass=1 (au-dessus) -->
      <symbol type="fill" name="6" alpha="1">
        <layer class="SimpleFill" enabled="1" locked="0" pass="1">
          <Option type="Map">
            <Option type="QString" name="color" value="230,20,20,0"/>
            <Option type="QString" name="outline_color" value="230,20,20,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.9"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="joinstyle" value="miter"/>
            <Option type="QString" name="style" value="no"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>

  <!-- Visibilite par echelle : portee par les attributs de <qgis>
       (hasScaleBasedVisibilityFlag / minScale / maxScale), forme ecrite et lue
       par QGIS. L'ancien element <rendering minScale="100000"/> etait ignore :
       les ~118 000 chantiers s'affichaient a toutes les echelles. Seuil
       inchange : visible a partir de 1:100 000. -->
</qgis>
