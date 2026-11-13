# Recette manuelle — Constructel Bridge 1.9.0 (écran d'accueil, multi-opérateur, hors connexion)

> **STATUT : EN ATTENTE — exécution humaine sur vrai QGIS requise.**
> La suite automatisée tourne sur des doublures (stubs) de `qgis.*` : elle
> ne prouve ni la persistance dans le `.qgz`, ni le rendu Qt, ni le
> comportement réel de l'installeur d'extensions ou du gestionnaire de
> tâches. Cette fiche couvre exactement ces points « non vérifiables sur
> stubs ». **Aucune publication (`release.py 1.9.0 --cloture`) tant que tous les
> points non optionnels (sections A à M) ne sont pas cochés sur QGIS 3.28 ET sur une QGIS 4.x.**
>
> Consigner : date : ____ · QGIS exact (3.28.x) : ____ · QGIS exact (4.x) : ____ ·
> poste (Windows ?) : ____ · exécutant : ____ · commit du plugin : `git rev-parse --short HEAD` = ____

À exécuter par une personne disposant d'un vrai poste QGIS, **deux fois** :
QGIS 3.28 LTR (Python 3.9, Qt5) puis QGIS 4.x (Qt6). Chaque case porte
`☐ 3.28  ☐ 4.x` : remplacer `☐` par `☑` (OK) ou `✗` (KO, avec une note).
Un KO bloque la publication ; une déviation tolérée est notée « écart connu ».

**Règles de lecture**

- **Optionnel = non bloquant pour la publication.** Un point marqué « (optionnel) » peut être sauté, ou échouer, sans empêcher la publication ; l'échec se note quand même. Tout autre point est bloquant. Points optionnels de cette fiche : **J10** (serveur muet), **L1** (compte sans opérateur) et le compte **E** des prérequis.
- **Langue** : les messages cités sont ceux de l'interface en **français** ; exécuter QGIS en français sauf mention contraire (A3, H1 : changement de langue).
- **Dossier du profil** : Réglages > Profils utilisateur > Ouvrir le dossier du profil actif. Le fichier de réglages y est `QGIS/QGIS3.ini` (QGIS 3.x) ou `QGIS/QGIS4.ini` (QGIS 4.x).

## Prérequis

- **Plugin à tester** : le dossier `plugin-repo/packages/constructel_bridge` de la
  branche `feat/bridge-accueil-operateur`, copié dans le dossier `python/plugins`
  du profil QGIS (ou ZIP construit à la main). Ce n'est **pas** une release : ne
  rien publier, ne pas toucher `plugins.xml`.
- **Base de test** (pas la production) : le serveur Farois habituel, mais sur une
  base où écrire est sans conséquence. Aucune des vérifications ci-dessous n'exige
  de SQL.
- **Comptes** (login nominatif AD) :
  - **A** : scopes OPÉRATEUR Wyre **et** Orange (ou ADMIN/MANAGER, avec les schémas `wyre` et `orange` lisibles) ;
  - **B** : scope Wyre seul ;
  - **C** : scope Orange seul ;
  - **D** : compte en lecture seule (rôle sans écriture réseau, « VIEWER ») avec Orange ;
  - **E** (optionnel) : compte sans aucun scope opérateur utilisable.
- **Projets 1.8** : trois projets enregistrés (`.qgz`) avec le Bridge 1.8.4, chacun
  après « Initialiser le projet » sur une QGIS réglée en **FR**, en **EN**, puis en **PT**
  (groupes « Points de demande » / « Demand Points » / « Pontos de procura », « Infrastructure » / « Infraestrutura », « Zones » / « Zonas »).
  Les garder en lecture seule sur disque : **faire une copie avant chaque essai**.
- **Console Python QGIS** : coller une fois l'aide ci-dessous (reste valable pendant la session).

```python
from qgis.core import QgsProject, QgsLayerTree
def walk(g=None, d=0):
    g = g or QgsProject.instance().layerTreeRoot()
    for c in g.children():
        if QgsLayerTree.isGroup(c):
            print("  " * d + "[G]", c.name(), "| schema =", c.customProperty("constructel_bridge/operator_schema"),
                  "| kind =", c.customProperty("constructel_bridge/group"))
            walk(c, d + 1)
        else:
            print("  " * d + "-", c.name(), "|", c.layer().id() if c.layer() else "COUCHE ABSENTE")
def ident():
    p = QgsProject.instance()
    for k in ("operator", "operator_labels", "operator_suffix"):
        print(k, "=", p.readEntry("bridge", k))
    print("nb couches du projet :", len(p.mapLayers()))
```

---

## A. Hors connexion (aucun accès à la base)

Préparer : couper le réseau (VPN/câble/Wi-Fi), **fermer** QGIS, le relancer. Le plugin
démarre sans connexion.

- [ ] **A1 — L'accueil s'ouvre sans connexion.** Cliquer le bouton principal Constructel Bridge. → L'écran d'accueil s'ouvre ; en-tête « non connecté · Se connecter » ; message « Connecte-toi pour voir les opérateurs auxquels tu as accès » ; sélecteur d'opérateur et bouton de chargement désactivés ; tuile « Projet enregistré » désactivée ; Check-in, Diagnostic, Langue actives. Aucune boîte « Connectez-vous d'abord ». ☐ 3.28 ☐ 4.x
- [ ] **A2 — Diagnostic hors réseau.** Tuile Diagnostic. → La ligne « Vérification en cours… » apparaît puis le résultat arrive en **≈ 3 s au plus** : chacune des deux vérifications réseau (version du plugin, serveur) est bornée à 3 s et elles tournent en parallèle (deux fils), donc l'ensemble tient dans ≈ 3 s ; QGIS reste utilisable pendant l'attente ; « Serveur Farois … injoignable ou sans réponse » (erreur), « dépôt Constructel injoignable » (avertissement) ; les lignes d'extensions et d'identifiant restent calculées (sans réseau). Aucune invite de mot de passe maître de l'Auth Manager. ☐ 3.28 ☐ 4.x
- [ ] **A3 — Langue hors connexion.** Tuile Langue → choisir EN puis PT puis FR. → L'écran se redessine dans la langue choisie, les entrées du menu déroulant du bouton suivent (« Home · load layers », « Status and diagnostics »…). ☐ 3.28 ☐ 4.x
- [ ] **A4 — Menu déroulant (flèche).** → « Accueil · charger les couches » ouvre l'accueil ; « Statut et diagnostic » ouvre **le Diagnostic** (avec, en tête, « Non connecté. Utilisez… ») ; « Configuration initiale » ouvre le Check-in. ☐ 3.28 ☐ 4.x
- [ ] **A5 — Aucune tentative d'accès à la base hors connexion (obligatoire).** Contrainte globale : hors connexion, l'accueil, le Check-in, la Langue et le menu ne touchent **jamais** la base. **Cette préparation remplace celle « hors réseau » de la section A** : ici le poste reste **branché au réseau**, et c'est une règle de pare-feu sortante qui bloque l'accès à la base (le réseau n'est pas coupé). Poser la règle (étape 1) **avant de lancer QGIS** ; la tentative de connexion automatique du démarrage (comportement 1.8, hors périmètre de ce test) échoue et affiche son message : **attendre qu'elle soit terminée et fermer ce message**, puis seulement commencer. Vérifier, sans accès au serveur :
  1. *Pas de blocage ni d'erreur.* Poste branché au réseau mais avec une règle de pare-feu sortante qui **bloque le port PostgreSQL** du serveur Farois (Pare-feu Windows avec fonctions avancées > Règles de trafic sortant > Nouvelle règle > Personnalisée > protocole TCP, port distant = **port de la base** (celui de la connexion Farois : Navigateur QGIS > clic droit sur la connexion > Modifier la connexion), adresse distante `192.168.160.31` > Bloquer la connexion) : une connexion tentée vers la base resterait en attente de longues secondes. Ouvrir l'accueil, changer puis remettre la langue, parcourir le Check-in jusqu'au Résumé, ouvrir chaque entrée du menu déroulant. → Chaque écran apparaît **en moins d'une seconde**, sans message « Connexion impossible », sans nouvelle ligne de connexion dans le panneau Messages > Constructel Bridge.
  2. *Aucune connexion ouverte.* Pendant les mêmes manipulations, dans un terminal : `netstat -ano | findstr 192.168.160.31` (à répéter), ou PowerShell `Get-NetTCPConnection -RemoteAddress 192.168.160.31`. → Aucune ligne (`SYN_SENT`, `ESTABLISHED`) appartenant au PID de QGIS (`qgis-bin.exe`) pendant l'accueil, la Langue, le Check-in et le menu. Le Diagnostic, lui, ouvre volontairement des sondes TCP brèves (serveur, et dépôt sur le port 9080) : c'est attendu et vérifié en J11.
  3. *Optionnel dans ce point, si un admin est disponible :* `SELECT usename, client_addr, backend_start FROM pg_stat_activity WHERE client_addr = '<IP du poste>';` après les manipulations → aucune session du poste.
  Supprimer la règle de pare-feu à la fin. ☐ 3.28 ☐ 4.x
- [ ] **A6 — Se connecter depuis l'accueil.** Réseau rétabli (A1 à A4) et règle de pare-feu d'A5 supprimée, bouton « Se connecter ». → Le flux de connexion habituel se lance ; une fois connecté, l'en-tête affiche `login · périmètre`, le sélecteur d'opérateur et le bouton de chargement s'activent, « Projet enregistré » s'active. ☐ 3.28 ☐ 4.x

## B. Rendu Qt de l'écran d'accueil (connecté, compte A)

- [ ] **B1 — Mise en page.** Ouvrir l'accueil. → Deux colonnes (arbre des couches à gauche ; fonds de plan, style et boutons à droite) ; largeur minimale 820 px ; quatre tuiles secondaires sur deux lignes lisibles ; pastille de connexion verte ; aucun texte tronqué en FR, EN, PT ; aucune barre de défilement parasite. Vérifier aussi sur un écran 1366×768 et avec le thème sombre. ☐ 3.28 ☐ 4.x
- [ ] **B2 — Arbre à trois états.** Cocher/décocher un groupe de l'arbre « Couches de travail ». → Cocher un groupe coche ses enfants, l'état partiel s'affiche (carré), « Tout sélectionner » / « Tout désélectionner » fonctionnent. ☐ 3.28 ☐ 4.x
- [ ] **B3 — Couches déjà chargées grisées.** Après un premier chargement (D1), rouvrir l'accueil. → Les couches (et fonds de plan) déjà dans le projet sont **grisées et décochées** ; un groupe dont un enfant est déjà chargé peut afficher ☑ (état partiel) mais l'enfant grisé n'est jamais rechargé ; le résumé « Déjà dans le projet : ✓ Wyre · N couches · M couches communes · K fonds de plan » est exact. ☐ 3.28 ☐ 4.x
- [ ] **B4 — Boutons d'opérateur exclusifs.** Compte A : « Wyre » et « Orange » sont des boutons exclusifs ; recliquer le bouton déjà coché le laisse coché. Le libellé du bouton de chargement suit (« Initialiser · Wyre », puis « Ajouter les couches · Orange »). ☐ 3.28 ☐ 4.x
- [ ] **B5 — Redessin sans plantage.** Cliquer successivement Check-in, Diagnostic, Langue, Se connecter (si hors connexion) depuis l'accueil, en fermant chaque dialogue. → L'écran se redessine après chacun (`replaceWidget` + `deleteLater`), sans plantage ni scintillement gênant, et reste ouvert. ☐ 3.28 ☐ 4.x
- [ ] **B6 — Dialogues modaux imbriqués.** Au-dessus de l'accueil : assistant Check-in, Diagnostic, `QInputDialog` de langue, dialogue de connexion, `QMessageBox` d'erreur de chargement (provoquer une erreur : couper le réseau puis cliquer Initialiser). → Chacun apparaît au premier plan, se ferme proprement, l'accueil reste utilisable ; aucun dialogue caché derrière. ☐ 3.28 ☐ 4.x

## C. Un seul opérateur (compte B, ou A avec un seul opérateur choisi)

- [ ] **C1 — Affichage.** Compte B (scope Wyre seul). → L'opérateur est affiché **en texte** (pas de boutons), présélectionné ; case « Ajouter le nom de l'opérateur aux couches » **décochée** par défaut. ☐ 3.28 ☐ 4.x
- [ ] **C2 — Chargement sans suffixe.** Projet vierge, modèle « Infrastructure », case décochée, Initialiser · Wyre. → L'écran se ferme ; groupes : `Wyre` (Points de demande, Infrastructure, Zones), `Commun` (selon sélection), `Basemaps`, `Référence` ; noms de couches **sans suffixe** (« Câbles ») ; styles appliqués. Console : `walk()` puis `ident()` → `operator` = `wyre`, `operator_suffix` = `0`/absent. ☐ 3.28 ☐ 4.x
- [ ] **C3 — Suffixe optionnel mémorisé.** Nouveau projet vierge, cocher la case, charger. → Couches « Câbles · Wyre » ; rouvrir l'accueil sur un autre projet vierge : la case est **cochée** (dernier choix du poste, `QgsSettings` relu en texte). Décocher, recharger sur un troisième projet : décochée de nouveau. ☐ 3.28 ☐ 4.x
- [ ] **C4 — Capacités de l'ancien dialogue conservées.** Modèles et « -- Sélection manuelle -- » (description du modèle), arbre des couches par groupe, Tout sélectionner/désélectionner, arbre des fonds de plan, « Appliquer les styles depuis la base de données » (décoché : couches sans style de la base), mode Ajouter. ☐ 3.28 ☐ 4.x

## D. Parcours multi-opérateur : Wyre, puis ajouter Orange (compte A)

- [ ] **D1 — Wyre d'abord.** Projet vierge, Wyre, modèle complet, charger. → Voir C2 ; `Commun` contient Chantier, OSIRIS, Cadastre UrbIS, Urbanisme (selon sélection). ☐ 3.28 ☐ 4.x
- [ ] **D2 — Mode ajout.** Rouvrir l'accueil. → Bouton « Ajouter les couches · … » ; résumé « ✓ Wyre · N couches · … » ; Orange est sélectionnable, Wyre reste sélectionnable (pour compléter ses couches manquantes) ; **aucun opérateur hors de vos scopes** n'est proposé, même grisé. ☐ 3.28 ☐ 4.x
- [ ] **D3 — Suffixe obligatoire.** Choisir Orange. → La case du suffixe est **cochée et grisée**. Charger. → Groupes racine dans cet **ordre exact** : `Wyre`, `Orange`, `Commun`, `Basemaps`, `Référence` (`Orange` est inséré juste avant `Commun`). Couches Wyre **renommées** « … · Wyre » (le suffixe est aussi posé sur le premier opérateur), couches Orange « … · Orange » ; couches communes et fonds de plan **non dupliqués** (une seule « Chantier », un seul fond) et **sans suffixe**. L'ordre des sous-groupes à l'intérieur de `Wyre` et `Orange` n'est pas vérifié ici (écart connu : sous-groupes ajoutés en fin). ☐ 3.28 ☐ 4.x
- [ ] **D4 — Formulaire Orange.** Ouvrir le formulaire d'un câble « Câbles · Orange » (outil Identifier, ou table attributaire > formulaire). Dérouler le champ **POP Zone** (`zone_pop_id`). → La liste propose des POP **Orange** ; le même champ d'un câble Wyre propose des POP Wyre (les deux listes diffèrent). Choisir un autre POP de la liste du câble Orange et **enregistrer** (base de test). → L'enregistrement est accepté, sans erreur de clé étrangère (migration 543). Remettre ensuite la valeur d'origine. ☐ 3.28 ☐ 4.x
- [ ] **D5 — Infobulles.** Survol (infobulle) d'une zone **drop** Orange et d'une zone **distribution** Orange. → Les noms affichés viennent de la couche **Orange** (POP/zone Orange), pas de Wyre ; idem pour Wyre côté Wyre. ☐ 3.28 ☐ 4.x
- [ ] **D6 — Relations.** Projet > Propriétés > Relations. → Chaque opérateur a ses relations, qui relient des couches du **même** opérateur. L'identifiant dépend de l'**opérateur principal** (le premier de l'identité du projet, donc le premier chargé) : en projet Wyre puis Orange (ici), Wyre garde les identifiants historiques (`zone_pop_to_mro`…) et Orange reçoit le suffixe `__orange` (`zone_pop_to_mro__orange`) ; en projet **Orange seul** (section G), Orange est principal : `zone_pop_to_mro`, sans `__orange`. Documents : relations correctes pour les deux opérateurs. **Écart connu, non bloquant** : dans le formulaire d'une structure du deuxième opérateur, les éditeurs « câbles depuis/vers cette structure » listent les câbles du principal (liste vide). ☐ 3.28 ☐ 4.x
- [ ] **D7 — Couches communes intactes.** Si les couches communes avaient été stylées à la main avant d'ajouter Orange : leur symbologie reste inchangée après l'ajout. ☐ 3.28 ☐ 4.x
- [ ] **D8 — Chargements qui n'ajoutent rien.** Trois cas distincts.
  - **D8a — Rien de coché.** Rouvrir l'accueil (tout ce qui est chargé est grisé et décoché), ne rien cocher, cliquer Ajouter (si le bouton est actif). → **Aucun message**, aucun chargement, l'écran **reste ouvert et se redessine**, aucune couche en double (même comportement que F2b).
  - **D8b — Demandé mais rien d'ajouté (`init.nothing_added`).** Préparation : projet Wyre sans cadastre (modèle « Infrastructure + Chantier ») ; en administrateur, ajouter `127.0.0.1 geoservices-vector.irisnet.be` au fichier `hosts` (Windows : `C:\Windows\System32\drivers\etc\hosts`) pour que le service WFS UrbIS soit injoignable (base et reste du réseau inchangés). Accueil > cocher **uniquement** une couche « Cadastre UrbIS » jamais chargée sur ce poste (par ex. « Ilots » ; le cache réseau de QGIS pourrait sinon la rendre valide) > Ajouter. → Une couche WFS injoignable est invalide donc ignorée : barre de messages, avertissement ≈ 5 s : « Aucune couche ajoutée : déjà dans le projet ou invalide (voir le journal Constructel Bridge). » ; journal Constructel Bridge : « Couche invalide: wfs.urbisvector:Blocks » ; aucune couche ni aucun groupe créé ; l'écran **reste ouvert et se redessine**. Retirer ensuite la ligne du fichier `hosts`.
  - **D8c — Fond de plan seul.** Cocher un fond de plan pas encore dans le projet, rien d'autre > Ajouter. → L'écran se ferme ; message « Fonds de plan ajoutés : 1. ». ☐ 3.28 ☐ 4.x
- [ ] **D9 — Lecture seule (compte D).** Se connecter avec le compte en lecture seule, charger Orange. → Toutes les couches opérateur chargées sont en **lecture seule** (bouton d'édition indisponible) avec le message « … couche(s) réseau en lecture seule : votre compte est en lecture seule… » ; le périmètre du message de session cite les MRO/POP résolus dans **chaque** schéma opérateur. Compte A : couches éditables. ☐ 3.28 ☐ 4.x

## E. Persistance dans le `.qgz` (`setCustomProperty`, `insertGroup(index)`, identité)

- [ ] **E1 — Propriétés de groupe.** Après D3, enregistrer en `.qgz`, **Projet > Nouveau**, rouvrir. Console : `walk()`. → Les groupes `Wyre` et `Orange` portent `schema = wyre`/`orange` ; `Commun` porte `kind = Commun` ; les sous-groupes canoniques (Points de demande, Infrastructure, Zones, Chantier…) portent `kind` ; les couches ne sont pas « COUCHE ABSENTE ». Même résultat en enregistrant en `.qgs` (chercher `constructel_bridge/operator_schema` dans le XML). ☐ 3.28 ☐ 4.x
- [ ] **E2 — Identité.** `ident()` → `operator` = `wyre,orange` (ordre de chargement), `operator_labels` = JSON `{"wyre": "Wyre", "orange": "Orange"}`, `operator_suffix` = `1`. `@bridge_operator` (variable de projet) = `wyre,orange`. ☐ 3.28 ☐ 4.x
- [ ] **E3 — Position des groupes créés (`insertGroup(index)`).** **Préparation exacte** : projet vierge ; Accueil > opérateur **Wyre** seul ; modèle **« Infrastructure + Chantier »** (il apporte les couches communes du chantier, donc le groupe `Commun`) ; **cocher au moins un fond de plan** dans l'arbre des fonds (donc le groupe `Basemaps`) ; Initialiser. Le groupe `Référence` est créé avec la couche `v_form_lists`. Contrôler avant l'étape 1 : racine = `Wyre`, `Commun`, `Basemaps`, `Référence` (`walk()`).
  1. Créer un groupe personnel `Perso` (clic droit sur la racine > Ajouter un groupe) et le glisser entre `Wyre` et `Commun`. Racine = `Wyre`, `Perso`, `Commun`, `Basemaps`, `Référence`. Enregistrer.
  2. Accueil > **Orange** > Ajouter. → `Orange` est créé **juste avant `Commun`**, donc après `Perso` : racine exacte = `Wyre`, `Perso`, `Orange`, `Commun`, `Basemaps`, `Référence` (`Orange` à l'index 2). `Perso` est intact, aucun groupe en double.
  3. Supprimer le groupe `Commun` (clic droit > Supprimer le groupe, confirmer). Accueil > Wyre > cocher une couche commune (par ex. Chantier) > Ajouter. → `Commun` est recréé **avant `Basemaps`** : racine exacte = `Wyre`, `Perso`, `Orange`, `Commun`, `Basemaps`, `Référence` ; `Commun` contient la couche cochée.
  4. Enregistrer en `.qgz`, Projet > Nouveau, rouvrir. → Même ordre exact des groupes racine, mêmes propriétés (`walk()`), aucun doublon. ☐ 3.28 ☐ 4.x
- [ ] **E4 — Rouvrir ne modifie pas.** Rouvrir ce `.qgz` : aucun groupe n'est renommé ni déplacé à l'ouverture, le projet n'est pas marqué modifié par le plugin (pas d'astérisque dû au Bridge). ☐ 3.28 ☐ 4.x

## F. Réorganisation d'un projet 1.8 (clic « Ajouter » seulement)

Pour **chacun** des trois projets (FR, EN, PT) : travailler sur une copie.

- [ ] **F1 — Ouvrir ne change rien.** Ouvrir le projet 1.8 (réseau coupé ou non). → L'arbre est identique à celui enregistré ; `walk()` ne montre aucun groupe `Wyre` ni `Commun`. ☐ 3.28 ☐ 4.x (FR ☐ EN ☐ PT ☐)
- [ ] **F2 — Réorganisation au clic.** *Avant tout clic* : lancer `walk()` (copier toute la sortie : c'est la **référence**), `ident()` (nombre de couches) et noter la visibilité et l'état replié de quelques couches. Puis Accueil > choisir un opérateur > **cocher au moins un élément nouveau** (une couche absente du projet, ou un fond de plan) > Ajouter. Comportement réel : la réorganisation a lieu dans le chargement, **avant** l'ajout des couches, dès qu'au moins une couche ou un fond est demandé, **même si rien n'est finalement ajouté** (message « Aucune couche ajoutée… », la réorganisation reste faite). → Message « Projet réorganisé par opérateur (groupes Wyre et Commun) : enregistre-le… » ; les groupes Points de demande / Infrastructure / Zones sont **dans** le groupe `Wyre`, les groupes Chantier / OSIRIS / Cadastre / Urbanisme **dans** `Commun` ; **aucun groupe vide ni doublon** resté à la racine ; noms FR/EN/PT reconnus (pas de second « Points de demande »). ☐ 3.28 ☐ 4.x (FR ☐ EN ☐ PT ☐)
- [ ] **F2b — Rien de coché : rien ne bouge.** Sur une copie neuve du projet 1.8, Accueil > ne rien cocher (couches déjà présentes grisées, aucun fond) > Ajouter (si le bouton est actif). → Aucun chargement, aucune réorganisation, aucun message « Projet réorganisé » : `walk()` identique à la référence. ☐ 3.28 ☐ 4.x
- [ ] **F3 — `clone()` + `removeChildNode` : aucune couche perdue, y compris après réouverture.** Après F2 : `walk()` à nouveau et comparaison avec la référence d'avant → mêmes identifiants de couche (colonne après `|`), mêmes noms hors suffixe, mêmes états visible/replié, aucune ligne « COUCHE ABSENTE » ; `len(mapLayers())` **inchangé** (+ les éventuelles couches ajoutées). Risque visé : le pont registre/arbre de QGIS peut supprimer une couche dont le nœud disparaît de l'arbre ; le plugin ajoute le clone avant de retirer l'original. Puis **enregistrer le projet (`.qgz`), Projet > Nouveau, rouvrir** : `walk()` encore identique, **aucune couche manquante** (pas d'avertissement « couches introuvables », aucune couche invalide), symbologie, filtres (`subsetString`) et ordre de rendu conservés, couches en cours d'édition intactes. ☐ 3.28 ☐ 4.x (FR ☐ EN ☐ PT ☐)
- [ ] **F4 — Suffixe.** Un seul opérateur, case décochée : couches sans suffixe après réorganisation. Ajouter ensuite Orange : couches Wyre suffixées « · Wyre ». ☐ 3.28 ☐ 4.x
- [ ] **F5 — Idempotence.** Recliquer Ajouter (ou rouvrir le projet réorganisé enregistré puis Ajouter) : pas de « Wyre » dans « Wyre », pas de second `Commun`, pas de « Câbles · Wyre · Wyre ». ☐ 3.28 ☐ 4.x
- [ ] **F6 — Groupes personnels et projet partagé.** Un groupe perso (nom libre) et une couche perso restent à leur place. Un projet partagé en base reste en lecture seule hors administrateurs : le message invite à l'enregistrer en local. ☐ 3.28 ☐ 4.x
- [ ] **F7 — Opérateur hors scopes dans un projet partagé.** Ouvrir un projet contenant des couches d'un opérateur absent de vos scopes. → Jamais proposé dans le sélecteur ; le résumé « Déjà dans le projet » le nomme ; ses couches ne sont pas réorientées vers un autre opérateur. ☐ 3.28 ☐ 4.x

## G. Projet Orange seul (compte C)

- [ ] **G1 — Chargement et formulaires.** Projet vierge, opérateur Orange seul, charger. → Groupe `Orange` + `Commun` ; formulaires et infobulles ciblent les couches Orange ; les listes de valeurs des couches **communes** (Chantier…) ne renvoient pas d'erreur (réécrites vers la seule couche valide) ; Projet > Propriétés > Relations : identifiants **sans** `__orange` (Orange est l'opérateur principal : `zone_pop_to_mro`). ☐ 3.28 ☐ 4.x
- [ ] **G2 — Pas d'accès Wyre.** Aucune couche Wyre n'est tentée ni proposée ; pas de « permission denied for schema wyre » dans le journal. ☐ 3.28 ☐ 4.x

## H. Changement de langue sur un projet à deux opérateurs

- [ ] **H1 — Connecté.** Sur le projet D3 : Langue → EN. → `Commun` devient `Common` (PT : `Comum`), les sous-groupes traduits (Points de demande / Demand Points, Infrastructure, Zones) suivent, les couches deviennent « Cables · Wyre », « Cables · Orange » (suffixe conservé, jamais doublé) ; les groupes `Wyre`/`Orange` portent le libellé de l'opérateur, jamais traduit. Puis PT (« Comum »), puis FR. ☐ 3.28 ☐ 4.x
- [ ] **H2 — Cibles intactes.** Après chaque changement : le formulaire d'un câble Orange propose toujours des POP Orange, celui d'un câble Wyre des POP Wyre ; infobulles inchangées. ☐ 3.28 ☐ 4.x
- [ ] **H3 — Hors connexion.** Rouvrir ce projet réseau coupé (couches grisées), tuile Langue → autre langue. → Le suffixe suit la langue, aucune erreur ; une fois reconnecté, les formulaires ciblent toujours le bon opérateur. ☐ 3.28 ☐ 4.x

## I. Check-in hors connexion (QWizard) et installation d'extensions

- [ ] **I1 — Page Profil absente.** Réseau coupé, tuile Check-in. → L'assistant démarre sur « Plugins recommandés » (pas de page Profil) ; pas de bouton « Précédent » sur la première page ; les pages s'enchaînent (Plugins → Resource Sharing → Résumé) ; le résumé dit « Profil : disponible une fois connecté ». Aucun accès à la base. ☐ 3.28 ☐ 4.x
- [ ] **I2 — Premier vrai check-in.** À la première connexion qui suit un check-in hors ligne, l'assistant complet (avec Profil) est proposé : le check-in hors ligne n'a pas posé « onboarding terminé » (choix du plan, T7-c1 ; à valider par Simon). ☐ 3.28 ☐ 4.x
- [ ] **I3 — Installation réussie signalée comme réussie.** Réseau **rétabli**, désinstaller une extension recommandée (ex. un des plugins de la liste du Check-in), relancer le Check-in, la cocher. → Le résumé affiche « Plugin installé: … » (**pas** « Erreur plugin … ») ; l'extension est ensuite installée **et** activée dans le Gestionnaire d'extensions. Ceci prouve que `qgis.utils.available_plugins` est rafraîchi par `installPlugin` réel (sinon le plugin serait signalé en erreur à tort). ☐ 3.28 ☐ 4.x
- [ ] **I4 — Échec réel signalé.** Réseau coupé, tenter d'installer une extension absente. → « Erreur plugin … » (ou « Installeur de plugins indisponible ») et **jamais** « Plugin installé ». ☐ 3.28 ☐ 4.x
- [ ] **I5 — Mise à jour d'une extension déjà installée** (Diagnostic ou Check-in) : l'extension passe à la dernière version sans erreur ; si elle était désactivée, elle est d'abord activée (action « Activer »). ☐ 3.28 ☐ 4.x

## J. Diagnostic (connecté ou non)

- [ ] **J1 — Contenu.** En tête : message de statut (connecté à `host:port/db`, mode nominatif, périmètre) ; puis lignes OK (✔) / avertissement (⚠) / erreur (✖) : version du plugin, une ligne par extension recommandée, serveur Farois, identifiant nominatif ; symboles et couleurs lisibles (Windows, thème sombre), retours à la ligne corrects. ☐ 3.28 ☐ 4.x
- [ ] **J2 — Version du plugin.** Dépôt joignable : « Plugin Constructel Bridge 1.9.0 : à jour » (ou « la version X est disponible » si le dépôt publie plus récent). ☐ 3.28 ☐ 4.x
- [ ] **J3 — `QgsTask`.** Ouvrir le Diagnostic : une tâche « Constructel Bridge - Diagnostic » apparaît dans le gestionnaire de tâches (panneau en bas à droite / Vue > Panneaux > Gestionnaire de tâches) ; le résultat arrive dans le fil de l'interface (lignes mises à jour, pas de traceback) ; l'annulation depuis le panneau ne plante pas. ☐ 3.28 ☐ 4.x
- [ ] **J4 — Fermer pendant la tâche.** Réseau coupé (la tâche dure ≈ 3 s), ouvrir le Diagnostic et le **fermer aussitôt**. → Aucun plantage ni message d'erreur Python ; réouvrir le Diagnostic fonctionne ; QGIS se ferme proprement ensuite. ☐ 3.28 ☐ 4.x
- [ ] **J5 — Action « Installer ».** Extension absente → bouton « Installer ». → L'interface peut se figer brièvement (fetch de l'installeur dans le fil de l'interface, accepté) sans plantage ni deadlock ; la ligne passe à OK ; l'extension est installée et activée. ☐ 3.28 ☐ 4.x
- [ ] **J6 — « Activer » tient après redémarrage.** Désactiver une extension recommandée dans le Gestionnaire d'extensions, Diagnostic → « Activer ». → La ligne passe à OK. **Fermer QGIS, le relancer** : l'extension est toujours active (case cochée dans le Gestionnaire ; dans le fichier .ini du profil (`QGIS3.ini` ou `QGIS4.ini` selon la version), section `[PythonPlugins]`, la clé de l'extension vaut `true`). Relancer encore une fois pour confirmer. ☐ 3.28 ☐ 4.x
- [ ] **J7 — Mise à jour du Bridge lui-même depuis le Diagnostic.** Le Gestionnaire d'extensions de QGIS interroge les dépôts **configurés dans QGIS** ; la variable `CONSTRUCTEL_PLUGIN_REPO_URL` ne sert qu'à la ligne « version » du Diagnostic. Il faut donc les deux. Version installée avant le test : 1.9.0 (la copie de la branche).
  1. *Construire le dépôt de test* (dossier `depot-test`, hors du dépôt git ; remplacer `SRC` par le dossier `plugin-repo/packages/constructel_bridge` de la branche) :

     ```python
     import re, zipfile
     from pathlib import Path
     SRC = Path(r"/chemin/vers/plugin-repo/packages/constructel_bridge")
     OUT = Path("depot-test"); (OUT / "packages").mkdir(parents=True, exist_ok=True)
     with zipfile.ZipFile(OUT / "packages" / "constructel_bridge.zip", "w", zipfile.ZIP_DEFLATED) as zf:
         for f in sorted(SRC.rglob("*")):
             if f.is_file() and "__pycache__" not in f.parts:
                 arc = (Path("constructel_bridge") / f.relative_to(SRC)).as_posix()
                 if f.name == "metadata.txt" and f.parent == SRC:   # version bidon 1.9.1
                     zf.writestr(arc, re.sub(r"(?m)^version=.*$", "version=1.9.1", f.read_text(encoding="utf-8")))
                 else:
                     zf.write(f, arc)
     (OUT / "plugins.xml").write_text("""<?xml version="1.0" encoding="UTF-8"?>
     <plugins>
       <pyqgis_plugin name="Constructel Bridge" version="1.9.1">
         <description><![CDATA[Version bidon 1.9.1 pour la recette]]></description>
         <about><![CDATA[Test de mise a jour depuis le Diagnostic]]></about>
         <version>1.9.1</version>
         <qgis_minimum_version>3.28</qgis_minimum_version>
         <qgis_maximum_version>4.99</qgis_maximum_version>
         <author_name><![CDATA[recette]]></author_name>
         <homepage><![CDATA[http://localhost:8000]]></homepage>
         <tracker><![CDATA[http://localhost:8000]]></tracker>
         <repository><![CDATA[http://localhost:8000]]></repository>
         <tags><![CDATA[test]]></tags>
         <experimental>False</experimental>
         <deprecated>False</deprecated>
         <server>False</server>
         <file_name>constructel_bridge.zip</file_name>
         <download_url>http://localhost:8000/packages/constructel_bridge.zip</download_url>
       </pyqgis_plugin>
     </plugins>
     """, encoding="utf-8")
     ```

  2. *Servir* : `cd depot-test` puis `python -m http.server 8000` (laisser tourner).
  3. *Ajouter le dépôt dans QGIS* : Extensions > Gérer et installer les extensions > Paramètres > Ajouter… : nom `bridge-test`, URL `http://localhost:8000/plugins.xml`.
  4. *Lancer QGIS avec la variable*, depuis un terminal où elle est définie (cmd : `set CONSTRUCTEL_PLUGIN_REPO_URL=http://localhost:8000/plugins.xml` puis lancer QGIS depuis **ce** terminal ; Linux : `CONSTRUCTEL_PLUGIN_REPO_URL=http://localhost:8000/plugins.xml qgis`).
  5. Tuile Diagnostic. → Ligne d'avertissement « Plugin Constructel Bridge 1.9.0 : la version 1.9.1 est disponible » avec le bouton « Gestionnaire d'extensions ». Cliquer. → Le Gestionnaire s'ouvre. Le Diagnostic étant modal, ses clics peuvent y être bloqués : dans ce cas, fermer le Diagnostic (le Gestionnaire reste ouvert). Dans les deux cas, continuer.
  6. Dans le Gestionnaire, onglet « Mises à jour installables » (ou « Installées ») : Constructel Bridge > **Mettre à jour l'extension** (1.9.1).
  7. **Attendu (tranché)** : (a) **aucun traceback Python** (panneau Messages, onglet « Python Error », vide) et QGIS reste stable (ni plantage ni blocage) ; (b) le dialogue du Diagnostic est **fermé, ou inerte** : s'il reste affiché, ne pas cliquer ses boutons, et le fermer (croix, Échap) ne produit aucune erreur ; (c) le Gestionnaire indique Constructel Bridge **1.9.1 installé et actif** (si QGIS demande un redémarrage, redémarrer) ; le bouton Constructel Bridge et son menu fonctionnent ; le Diagnostic rouvert dit « Plugin Constructel Bridge 1.9.1 : à jour » (variable toujours définie).
  8. *Nettoyage* : retirer le dépôt `bridge-test` des paramètres, arrêter le serveur, supprimer `depot-test`, ne plus définir la variable, **remettre la copie 1.9.0 de la branche** dans le dossier du plugin (le zip 1.9.1 l'a remplacée), redémarrer QGIS. ☐ 3.28 ☐ 4.x
- [ ] **J8 — Derrière un proxy d'entreprise.** Poste Windows avec un proxy système (Options Internet / WinINET) qui **ne joint pas** `192.168.160.31`, et/ou un proxy réglé dans QGIS (Options > Réseau). → Diagnostic : le dépôt interne reste **joignable** (« à jour »), **pas** « dépôt injoignable » : `plugins.xml` (`http://192.168.160.31:9080/plugin-repo/plugins.xml`, variable `CONSTRUCTEL_PLUGIN_REPO_URL` non définie) est lu sans proxy. Le Gestionnaire d'extensions de QGIS peut continuer à utiliser le proxy. ☐ 3.28 ☐ 4.x
- [ ] **J9 — Certificat et `VERIFY_X509_STRICT`.** Console : `import sys, ssl; print(sys.version_info[:3], bool(ssl.create_default_context().verify_flags & ssl.VERIFY_X509_STRICT))`.
  - **Python ≥ 3.13** (affiche `True`, typiquement QGIS 4.x) : le Diagnostic dit « Serveur Farois … : joignable, certificat valide ». Sinon noter l'erreur (`certificat refusé (…)`) : un certificat serveur non conforme aux contrôles stricts est à corriger **côté serveur**, pas dans le plugin ; le signaler (KO de déploiement, bloquant pour la publication).
  - **Python < 3.13** (affiche `False`, typiquement QGIS 3.28 avec Python 3.9) : **N/A pour le mode strict** ; noter la version de Python ; l'attendu reste « joignable, certificat valide » (vérification normale : CA du paquet et nom d'hôte). ☐ 3.28 ☐ 4.x
- [ ] **J10 — Serveur qui accepte le TCP sans répondre (optionnel).** Sur un poste de test, pointer `host`/`port` du `credentials.json` vers un écouteur muet (`nc -l 5433`) : le Diagnostic rend « injoignable ou sans réponse » en ≈ 3 s, sans bloquer QGIS. Restaurer ensuite `credentials.json`. ☐ 3.28 ☐ 4.x
- [ ] **J11 — Aucun secret, aucune session.** Pendant le Diagnostic (connecté ou non) : (a) **aucune invite** du mot de passe maître de l'Auth Manager ; (b) `netstat -ano | findstr 192.168.160.31` répété pendant l'exécution : seulement des connexions **brèves** du PID de QGIS (≤ 3 s : sonde TLS sur le port de la base, dépôt sur le port 9080), qui disparaissent seules, aucune connexion maintenue (`ESTABLISHED` durable) ; (c) si un admin est disponible : `pg_stat_activity` ne montre aucune nouvelle session pour l'IP du poste (la sonde s'arrête avant le paquet de démarrage) et le journal serveur aucun échec d'authentification. ☐ 3.28 ☐ 4.x

## K. Navigateur QGIS et « Projet enregistré » (§ 6.7)

- [ ] **K1 — Navigateur, compte A.** Navigateur QGIS > PostgreSQL > connexion Farois (« wyre »). Après connexion, ses schémas sont ceux des **opérateurs utilisables** (`wyre`, `orange`, …) plus `osiris` ; un schéma opérateur non utilisable n'y figure pas. ☐ 3.28 ☐ 4.x
- [ ] **K2 — Navigateur, comptes B et C.** Compte B : `wyre` + `osiris`. Compte C : `orange` + `osiris`. (Le rafraîchissement se fait à la **connexion** : après un changement de scope, se reconnecter.) La connexion `be` n'est jamais modifiée. ☐ 3.28 ☐ 4.x
- [ ] **K3 — « Projet enregistré » liste Orange.** Sur la base de test, enregistrer un projet dans le schéma `orange` (Projet > Enregistrer vers > PostgreSQL), puis Accueil > « Projet enregistré ». → La liste contient les projets des schémas des opérateurs utilisables (dont `orange`) et `public`, pas ceux d'un schéma non utilisable ; l'écran se ferme avant le choix, le projet choisi s'ouvre. ☐ 3.28 ☐ 4.x
- [ ] **K4 — Repli 1.8.** Registre d'opérateurs illisible (par ex. compte BE sans accès à `ref.operateurs`) : comportement 1.8 (`wyre,osiris` pour le navigateur ; `wyre` et `public` pour les projets), l'accueil charge Wyre. ☐ 3.28 ☐ 4.x

## L. Compte sans opérateur (optionnel, compte E)

- [ ] **L1.** L'accueil affiche « Aucun opérateur accessible : demande un scope opérateur à un administrateur Farois. » ; sélecteur et chargement désactivés ; Check-in, Diagnostic, Langue restent utilisables. ☐ 3.28 ☐ 4.x

## M. Régression rapide

- [ ] **M1.** Connexion nominative (login AD) et message de session inchangés ; couches de la 1.8 chargées en Wyre seul ; menu déroulant : toutes les entrées (Connexion, Réessayer accès nominatif, Statut et diagnostic, Configuration initiale, Charger un projet, Accueil, Langue) présentes ; décharger/recharger le plugin (Plugin Reloader) sans erreur. ☐ 3.28 ☐ 4.x
- [ ] **M2.** Journal « Constructel Bridge » (panneau Messages) : aucun traceback Python pendant tout le parcours. ☐ 3.28 ☐ 4.x

---

## Sortie de recette

- Tout coché sur 3.28 **et** 4.x → la publication peut être demandée à Simon (`release.py 1.9.0 --cloture`, geste séparé).
- Un KO → noter le numéro, la version de QGIS, le message exact ; ne pas publier.
- Résultats à consigner dans la PR du chantier (copie de cette fiche cochée).
