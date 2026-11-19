<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling|Rendering" hasScaleBasedVisibilityFlag="1" minScale="200000" maxScale="1" labelsEnabled="0">
  <!--
    osiris_frozen_zones.qml - Zones gelees OSIRIS, classees selon le temps
    restant avant la FIN DU GEL (decision Simon du 19/11/2026).
    Couches stylees (meme fichier, meme rendu) :
      - osiris.frozen_zones           (table, toutes les zones)
      - osiris.v_frozen_zones_actives (vue : fin >= now() - 30 j)
    Champs lus : start_date, end_date (TIMESTAMPTZ), presents dans les deux
    relations. Aucune colonne calculee de la vue (statut_gel, jours_restants)
    n'est utilisee : le meme rendu marche sur la table.

    Recalcule a chaque ouverture / rafraichissement : now() est evalue par QGIS.
    Une seule mesure, jours restants = day(age("end_date", now())) (negatif si
    expire), seuils en jours : 3 mois = 91, 12 mois = 365, 2 ans = 730.

    Classes (exclusives, chaque zone dans exactement une) :
      Gel a venir     start_date > now()                  hachures (prioritaire)
      Gel commence (parent : start_date passe, ou NULL) :
        fin < 3 mois    0 <= jours < 91                   vert clair
        fin 3-12 mois   91 <= jours < 365                 jaune
        fin 1-2 ans     365 <= jours < 730                orange
        fin > 2 ans     jours >= 730                      rouge fonce
        fin inconnue    end_date NULL                     violet clair, tirete
        expire          jours < 0                         gris clair, DECOCHE
    L'ancienne borne glissante « fin >= 1er janvier » (demande du 18/11) est
    retiree : l'expire, masque par defaut, tient en une classe grise limitee a
    1:50 000.
    Aucune etiquette (decision Simon du 19/11) : labelsEnabled="0", pas de
    bloc <labeling>.
    Test : tests/unit/test_osiris_styles_fields.py (champs, classes).
  -->
  <renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="0" forceraster="0">
    <rules key="{fz-root}">
   <rule key="{fz-futur}" filter="coalesce(&quot;start_date&quot; &gt; now(), false)" label="Gel à venir (pas encore commencé)" symbol="0" description="start_date dans le futur : hachures, quelle que soit la date de fin"/>
      <rule key="{fz-commence}" filter="NOT coalesce(&quot;start_date&quot; &gt; now(), false)" label="Gel commencé : selon la date de fin" description="start_date passé ou inconnu : classé selon day(age(end_date, now()))">
    <rule key="{fz-fin-moins-3m}" filter="day(age(&quot;end_date&quot;, now())) &gt;= 0 AND day(age(&quot;end_date&quot;, now())) &lt; 91" label="Fin du gel dans moins de 3 mois" symbol="1" description="Bientôt libre : 0 à 90 jours restants"/>
    <rule key="{fz-fin-3-12m}" filter="day(age(&quot;end_date&quot;, now())) &gt;= 91 AND day(age(&quot;end_date&quot;, now())) &lt; 365" label="Fin du gel dans 3 à 12 mois" symbol="2" description="91 à 364 jours restants"/>
    <rule key="{fz-fin-1-2a}" filter="day(age(&quot;end_date&quot;, now())) &gt;= 365 AND day(age(&quot;end_date&quot;, now())) &lt; 730" label="Fin du gel dans 1 à 2 ans" symbol="3" description="365 à 729 jours restants"/>
    <rule key="{fz-fin-plus-2a}" filter="day(age(&quot;end_date&quot;, now())) &gt;= 730" label="Fin du gel dans plus de 2 ans" symbol="4" description="730 jours restants ou plus"/>
    <rule key="{fz-fin-inconnue}" filter="&quot;end_date&quot; IS NULL" label="Fin du gel inconnue" symbol="5" description="end_date NULL (gel déjà commencé ou début inconnu)"/>
    <rule key="{fz-expire}" filter="day(age(&quot;end_date&quot;, now())) &lt; 0" label="Gel expiré (masqué par défaut)" symbol="6" checkstate="0" scalemindenom="1" scalemaxdenom="50000" description="end_date dépassée : décochée par défaut, visible sous 1:50 000 si cochée"/>
      </rule>
    </rules>
    <symbols>
      <!-- 0 : gel a venir - hachures bleu-gris -->
      <symbol type="fill" name="0" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="70,100,150,25"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="outline_color" value="50,80,130,230"/>
            <Option type="QString" name="outline_style" value="dash"/>
            <Option type="QString" name="outline_width" value="0.7"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
        <layer class="LinePatternFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="angle" value="45"/>
            <Option type="QString" name="color" value="50,80,130,200"/>
            <Option type="QString" name="distance" value="3.5"/>
            <Option type="QString" name="distance_unit" value="MM"/>
            <Option type="QString" name="line_width" value="0.45"/>
            <Option type="QString" name="line_width_unit" value="MM"/>
            <Option type="QString" name="offset" value="0"/>
          </Option>
        </layer>
      </symbol>
      <!-- 1 : fin < 3 mois - vert clair (bientot libre) -->
      <symbol type="fill" name="1" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="140,210,100,60"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="outline_color" value="90,170,60,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- 2 : fin 3 a 12 mois - jaune -->
      <symbol type="fill" name="2" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="255,215,0,60"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="outline_color" value="200,160,0,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- 3 : fin 1 a 2 ans - orange -->
      <symbol type="fill" name="3" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="255,140,0,60"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="outline_color" value="220,100,0,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- 4 : fin > 2 ans - rouge fonce -->
      <symbol type="fill" name="4" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="150,20,20,60"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="outline_color" value="120,10,10,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.7"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- 5 : fin inconnue - violet clair, contour tirete -->
      <symbol type="fill" name="5" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="180,130,210,50"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="outline_color" value="140,90,170,255"/>
            <Option type="QString" name="outline_style" value="dash"/>
            <Option type="QString" name="outline_width" value="0.6"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <!-- 6 : expire - gris clair (decoche par defaut) -->
      <symbol type="fill" name="6" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="200,200,200,40"/>
            <Option type="QString" name="joinstyle" value="bevel"/>
            <Option type="QString" name="offset" value="0,0"/>
            <Option type="QString" name="outline_color" value="170,170,170,160"/>
            <Option type="QString" name="outline_style" value="dot"/>
            <Option type="QString" name="outline_width" value="0.3"/>
            <Option type="QString" name="outline_width_unit" value="MM"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
</qgis>
