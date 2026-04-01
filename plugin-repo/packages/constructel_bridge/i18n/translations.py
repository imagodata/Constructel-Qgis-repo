# -*- coding: utf-8 -*-
"""
Constructel Bridge — Dictionnaires de traduction fr / en / pt.

Convention des cles:  section.sous_section.element
Substitutions:       {variable} dans les valeurs
"""

TRANSLATIONS: dict[str, dict[str, str]] = {
    # =====================================================================
    # ENGLISH
    # =====================================================================
    "en": {
        # -- Menu / Actions --
        "menu.connect": "Constructel: Connect to WYRE",
        "menu.status": "Constructel: Status",
        "menu.onboarding": "Constructel: Onboarding",
        "menu.load_project": "Constructel: Load project",
        "menu.language": "Constructel: Language",

        # -- Connection dialog --
        "dialog.title": "Constructel Bridge - Connection",
        "dialog.header": "<b>Connection to WYRE FTTH database</b><br>"
                         "<small>Role: ftth_editor (infrastructure layer editing)</small>",
        "dialog.server": "Server:",
        "dialog.port": "Port:",
        "dialog.database": "Database:",
        "dialog.role": "Role:",
        "dialog.password": "Password:",
        "dialog.password_placeholder": "ftth_editor password",
        "dialog.show_password": "Show password",
        "dialog.hide_password": "Hide password",
        "dialog.save_password": "Remember password",

        # -- Connection messages --
        "conn.failed": "Connection failed:\n{error}",
        "conn.established": "Connection established (ftth_editor)",
        "conn.connected_as": "Connected as {user}",
        "conn.connect_first": "Connect first via 'Constructel: Connect to WYRE'.",

        # -- Status --
        "status.title": "Constructel Bridge - Status",
        "status.not_connected": "Not connected.\nUse 'Constructel: Connect to WYRE' to connect.",
        "status.connected_to": "Connected to: {host}:{port}/{dbname}\n"
                               "Role: {user}\n"
                               "User: {bridge_user}\n"
                               "User ID: {bridge_user_id}\n"
                               "Hooks active: {hooks}",

        # -- User registration --
        "user.existing": "Existing user: {username} (id={user_id})",
        "user.created": "User created: {username} (id={user_id})",
        "user.error": "User registration error: {error}",

        # -- Hooks --
        "hook.installed": "Hook installed: {layer}",
        "hook.all_installed": "Edit hooks installed on layers",
        "hook.commit_tagged": "app.current_user={user} for commit on {layer}",
        "hook.exec_error": "executeSql unavailable ({error})",

        # -- QGIS PG connection --
        "pg.configured": "QGIS connection 'constructel_bridge' configured",
        "pg.already_configured": "QGIS connection 'constructel_bridge' already set up — skipped",

        # -- Layer datasource check --
        "layers.bad_host": "{count} layer(s) still point to localhost ({names}). "
                           "Re-save the project with the correct server ({host}).",

        # -- Language dialog --
        "lang.title": "Constructel Bridge - Language",
        "lang.prompt": "Select language:",
        "lang.restart": "Language changed to {lang}. Restart QGIS or reconnect for full effect.",

        # -- Load project from DB --
        "project.title": "Constructel Bridge - Load project",
        "project.select": "Select a project to load:",
        "project.none_found": "No QGIS projects found in the database.",
        "project.no_table": "No QGIS project storage found in the database.\n"
                            "Save a project first via Project > Save to > PostgreSQL.",
        "project.loaded": "Project '{name}' loaded successfully.",
        "project.load_error": "Error loading project '{name}':\n{error}",
        "project.list_error": "Error listing projects:\n{error}",

        # -- Onboarding: Page 1 - User profile --
        "onboard.user.title": "User profile",
        "onboard.user.subtitle": "Your identity will be associated with every layer modification.",
        "onboard.user.welcome_new": "<b>Welcome!</b> You are a new user.<br>"
                                    "Your account has been created automatically in the WYRE database.",
        "onboard.user.welcome_back": "<b>Welcome back!</b> Your account already exists in the WYRE database.",
        "onboard.user.field_id": "Username:",
        "onboard.user.field_firstname": "First name:",
        "onboard.user.field_firstname_hint": "First name (optional)",
        "onboard.user.field_lastname": "Last name:",
        "onboard.user.field_lastname_hint": "Last name",
        "onboard.user.field_email": "Email:",
        "onboard.user.field_email_hint": "Email",
        "onboard.user.note": "<small>This information is stored in <code>ref.users</code> "
                             "and used to trace modifications.</small>",

        # -- Onboarding: Page 2 - Plugins --
        "onboard.plugins.title": "Recommended plugins",
        "onboard.plugins.subtitle": "These plugins are optional but improve the FTTH experience in QGIS.",
        "onboard.plugins.already_active": "{name}  [already installed and active]",
        "onboard.plugins.installed_inactive": "{name}  [installed, not active]",
        "onboard.plugins.note": "<small>Plugins will be installed from the official QGIS repository. "
                                "You can also install them manually via "
                                "<i>Extensions > Install/Manage Extensions</i>.</small>",

        # -- Plugin descriptions --
        "plugin.nominatim.desc": (
            "Address locator based on Nominatim (OpenStreetMap). "
            "Search for an address or place directly from the QGIS search bar and zoom to it."
        ),
        "plugin.filtermate.desc": (
            "Advanced multi-layer filtering. Quickly filter visible features "
            "across multiple layers simultaneously, ideal for isolating a POP zone or cable section."
        ),
        "plugin.qfieldsync.desc": (
            "Synchronization with QField (field application). "
            "Prepare a QGIS project for fieldwork, package PostGIS layers "
            "and synchronize modifications."
        ),
        "plugin.resource_sharing.desc": (
            "Resource sharing (QML styles, SVG symbols, layout templates). "
            "Download Constructel resources (FTTH layer styles) from the internal server. "
            "Essential for up-to-date styles."
        ),

        # -- Onboarding: Page 3 - Resource Sharing --
        "onboard.rs.title": "QGIS Resource Sharing",
        "onboard.rs.subtitle": "Constructel resource repository (QML styles, symbols, templates).",
        "onboard.rs.installed": "<b>QGIS Resource Sharing is installed.</b><br>"
                                "The Constructel repository will be configured automatically.",
        "onboard.rs.not_installed": "<b>QGIS Resource Sharing is not installed.</b><br>"
                                    "Install it via the previous page or manually, "
                                    "then re-run onboarding to configure the repository.",
        "onboard.rs.repo_name": "Repository name:",
        "onboard.rs.repo_url": "URL:",
        "onboard.rs.auto_configure": "Configure this repository automatically",
        "onboard.rs.note": "<small>This repository contains layer styles, SVG symbols "
                           "and layout templates specific to the WYRE FTTH project.<br>"
                           "Internal server URL: <code>http://192.168.160.31:9081/</code></small>",

        # -- Onboarding: Page 4 - Summary --
        "onboard.summary.title": "Configuration complete",
        "onboard.summary.subtitle": "Summary of actions performed.",
        "onboard.summary.header": "<b>Actions performed:</b><ul>",
        "onboard.summary.footer": "</ul><br><i>You can re-run this wizard at any time via "
                                  "Database menu > Constructel Bridge > Constructel: Onboarding.</i>",

        # -- Onboarding: Actions --
        "onboard.action.profile_updated": "Profile updated: {first_name} {last_name} ({email})",
        "onboard.action.profile_error": "Profile update error: {error}",
        "onboard.action.no_plugins": "No additional plugins selected",
        "onboard.action.installer_unavailable": "Plugin installer unavailable ({error}). "
                                                "Install plugins manually via Extensions > Install.",
        "onboard.action.plugin_activated": "Plugin activated: {pid}",
        "onboard.action.plugin_installed": "Plugin installed: {pid}",
        "onboard.action.plugin_error": "Plugin error {pid}: {error}",
        "onboard.action.rs_not_installed": "QGIS Resource Sharing not installed — repository not configured",
        "onboard.action.rs_updated": "Repository '{name}' updated: {url}",
        "onboard.action.rs_exists": "Repository '{name}' already configured",
        "onboard.action.rs_added": "Repository '{name}' added: {url}",
        "onboard.action.onboarding_done": "Onboarding marked as complete",

        # -- Wizard --
        "wizard.title": "Constructel Bridge - Initial setup",
    },

    # =====================================================================
    # FRANCAIS
    # =====================================================================
    "fr": {
        # -- Menu / Actions --
        "menu.connect": "Constructel: Connexion WYRE",
        "menu.status": "Constructel: Statut",
        "menu.onboarding": "Constructel: Onboarding",
        "menu.load_project": "Constructel: Charger un projet",
        "menu.language": "Constructel: Langue",

        # -- Connection dialog --
        "dialog.title": "Constructel Bridge - Connexion",
        "dialog.header": "<b>Connexion a la base WYRE FTTH</b><br>"
                         "<small>Role: ftth_editor (edition couches infrastructure)</small>",
        "dialog.server": "Serveur:",
        "dialog.port": "Port:",
        "dialog.database": "Base:",
        "dialog.role": "Role:",
        "dialog.password": "Mot de passe:",
        "dialog.password_placeholder": "Mot de passe ftth_editor",
        "dialog.show_password": "Afficher le mot de passe",
        "dialog.hide_password": "Masquer le mot de passe",
        "dialog.save_password": "Retenir le mot de passe",

        # -- Connection messages --
        "conn.failed": "Connexion impossible:\n{error}",
        "conn.established": "Connexion etablie (ftth_editor)",
        "conn.connected_as": "Connecte en tant que {user}",
        "conn.connect_first": "Connectez-vous d'abord via 'Constructel: Connexion WYRE'.",

        # -- Status --
        "status.title": "Constructel Bridge - Statut",
        "status.not_connected": "Non connecte.\nUtilisez 'Constructel: Connexion WYRE' pour vous connecter.",
        "status.connected_to": "Connecte a: {host}:{port}/{dbname}\n"
                               "Role: {user}\n"
                               "Utilisateur: {bridge_user}\n"
                               "User ID: {bridge_user_id}\n"
                               "Hooks actifs: {hooks}",

        # -- User registration --
        "user.existing": "Utilisateur existant: {username} (id={user_id})",
        "user.created": "Utilisateur cree: {username} (id={user_id})",
        "user.error": "Erreur registration user: {error}",

        # -- Hooks --
        "hook.installed": "Hook installe: {layer}",
        "hook.all_installed": "Hooks d'edition installes sur les couches",
        "hook.commit_tagged": "app.current_user={user} pour commit sur {layer}",
        "hook.exec_error": "executeSql indisponible ({error})",

        # -- QGIS PG connection --
        "pg.configured": "Connexion QGIS 'constructel_bridge' configuree",
        "pg.already_configured": "Connexion QGIS 'constructel_bridge' deja en place — ignoree",

        # -- Layer datasource check --
        "layers.bad_host": "{count} couche(s) pointent encore vers localhost ({names}). "
                           "Re-sauvegardez le projet avec le bon serveur ({host}).",

        # -- Language dialog --
        "lang.title": "Constructel Bridge - Langue",
        "lang.prompt": "Choisissez la langue:",
        "lang.restart": "Langue changee en {lang}. Redemarrez QGIS ou reconnectez-vous pour un effet complet.",

        # -- Load project from DB --
        "project.title": "Constructel Bridge - Charger un projet",
        "project.select": "Selectionnez un projet a charger:",
        "project.none_found": "Aucun projet QGIS trouve dans la base de donnees.",
        "project.no_table": "Aucun stockage de projet QGIS trouve dans la base.\n"
                            "Sauvegardez d'abord un projet via Projet > Enregistrer sous > PostgreSQL.",
        "project.loaded": "Projet '{name}' charge avec succes.",
        "project.load_error": "Erreur au chargement du projet '{name}':\n{error}",
        "project.list_error": "Erreur lors du listage des projets:\n{error}",

        # -- Onboarding: Page 1 - User profile --
        "onboard.user.title": "Profil utilisateur",
        "onboard.user.subtitle": "Votre identite sera associee a chaque modification de couche.",
        "onboard.user.welcome_new": "<b>Bienvenue !</b> Vous etes un nouvel utilisateur.<br>"
                                    "Votre compte a ete cree automatiquement dans la base WYRE.",
        "onboard.user.welcome_back": "<b>Bon retour !</b> Votre compte existe deja dans la base WYRE.",
        "onboard.user.field_id": "Identifiant:",
        "onboard.user.field_firstname": "Prenom:",
        "onboard.user.field_firstname_hint": "Prenom (facultatif)",
        "onboard.user.field_lastname": "Nom:",
        "onboard.user.field_lastname_hint": "Nom de famille",
        "onboard.user.field_email": "Email:",
        "onboard.user.field_email_hint": "Email",
        "onboard.user.note": "<small>Ces informations sont stockees dans <code>ref.users</code> "
                             "et utilisees pour tracer les modifications.</small>",

        # -- Onboarding: Page 2 - Plugins --
        "onboard.plugins.title": "Plugins recommandes",
        "onboard.plugins.subtitle": "Ces plugins sont facultatifs mais ameliorent l'experience FTTH dans QGIS.",
        "onboard.plugins.already_active": "{name}  [deja installe et actif]",
        "onboard.plugins.installed_inactive": "{name}  [installe, non actif]",
        "onboard.plugins.note": "<small>Les plugins seront installes depuis le depot officiel QGIS. "
                                "Vous pouvez aussi les installer manuellement via "
                                "<i>Extensions > Installer/Gerer les extensions</i>.</small>",

        # -- Plugin descriptions --
        "plugin.nominatim.desc": (
            "Localisateur d'adresses base sur Nominatim (OpenStreetMap). "
            "Permet de rechercher une adresse ou un lieu directement depuis "
            "la barre de recherche de QGIS et de zoomer dessus."
        ),
        "plugin.filtermate.desc": (
            "Filtrage avance multi-couches. Permet de filtrer rapidement "
            "les entites visibles sur plusieurs couches simultanement, "
            "ideal pour isoler une zone POP ou un troncon de cable."
        ),
        "plugin.qfieldsync.desc": (
            "Synchronisation avec QField (application terrain). "
            "Permet de preparer un projet QGIS pour le terrain, de packager "
            "les couches PostGIS et de synchroniser les modifications."
        ),
        "plugin.resource_sharing.desc": (
            "Partage de ressources (styles QML, symboles SVG, modeles de mise en page). "
            "Permet de telecharger les ressources Constructel (styles de couches FTTH) "
            "depuis le serveur interne. Indispensable pour avoir les styles a jour."
        ),

        # -- Onboarding: Page 3 - Resource Sharing --
        "onboard.rs.title": "QGIS Resource Sharing",
        "onboard.rs.subtitle": "Depot de ressources Constructel (styles QML, symboles, modeles).",
        "onboard.rs.installed": "<b>QGIS Resource Sharing est installe.</b><br>"
                                "Le depot Constructel sera configure automatiquement.",
        "onboard.rs.not_installed": "<b>QGIS Resource Sharing n'est pas installe.</b><br>"
                                    "Installez-le via la page precedente ou manuellement, "
                                    "puis relancez l'onboarding pour configurer le depot.",
        "onboard.rs.repo_name": "Nom du depot:",
        "onboard.rs.repo_url": "URL:",
        "onboard.rs.auto_configure": "Configurer ce depot automatiquement",
        "onboard.rs.note": "<small>Ce depot contient les styles de couches, les symboles SVG "
                           "et les modeles de mise en page specifiques au projet WYRE FTTH.<br>"
                           "URL du serveur interne: <code>http://192.168.160.31:9081/</code></small>",

        # -- Onboarding: Page 4 - Summary --
        "onboard.summary.title": "Configuration terminee",
        "onboard.summary.subtitle": "Resume des actions effectuees.",
        "onboard.summary.header": "<b>Actions effectuees:</b><ul>",
        "onboard.summary.footer": "</ul><br><i>Vous pouvez relancer cet assistant a tout moment via "
                                  "le menu Base de donnees > Constructel Bridge > Constructel: Onboarding.</i>",

        # -- Onboarding: Actions --
        "onboard.action.profile_updated": "Profil mis a jour: {first_name} {last_name} ({email})",
        "onboard.action.profile_error": "Erreur mise a jour profil: {error}",
        "onboard.action.no_plugins": "Aucun plugin supplementaire selectionne",
        "onboard.action.installer_unavailable": "Installeur de plugins indisponible ({error}). "
                                                "Installez les plugins manuellement via Extensions > Installer.",
        "onboard.action.plugin_activated": "Plugin active: {pid}",
        "onboard.action.plugin_installed": "Plugin installe: {pid}",
        "onboard.action.plugin_error": "Erreur plugin {pid}: {error}",
        "onboard.action.rs_not_installed": "QGIS Resource Sharing non installe — depot non configure",
        "onboard.action.rs_updated": "Depot '{name}' mis a jour: {url}",
        "onboard.action.rs_exists": "Depot '{name}' deja configure",
        "onboard.action.rs_added": "Depot '{name}' ajoute: {url}",
        "onboard.action.onboarding_done": "Onboarding marque comme termine",

        # -- Wizard --
        "wizard.title": "Constructel Bridge - Configuration initiale",
    },

    # =====================================================================
    # PORTUGUES
    # =====================================================================
    "pt": {
        # -- Menu / Actions --
        "menu.connect": "Constructel: Ligar ao WYRE",
        "menu.status": "Constructel: Estado",
        "menu.onboarding": "Constructel: Configuracao inicial",
        "menu.load_project": "Constructel: Carregar projeto",
        "menu.language": "Constructel: Idioma",

        # -- Connection dialog --
        "dialog.title": "Constructel Bridge - Ligacao",
        "dialog.header": "<b>Ligacao a base de dados WYRE FTTH</b><br>"
                         "<small>Papel: ftth_editor (edicao de camadas de infraestrutura)</small>",
        "dialog.server": "Servidor:",
        "dialog.port": "Porta:",
        "dialog.database": "Base de dados:",
        "dialog.role": "Papel:",
        "dialog.password": "Palavra-passe:",
        "dialog.password_placeholder": "Palavra-passe ftth_editor",
        "dialog.show_password": "Mostrar palavra-passe",
        "dialog.hide_password": "Ocultar palavra-passe",
        "dialog.save_password": "Guardar palavra-passe",

        # -- Connection messages --
        "conn.failed": "Ligacao impossivel:\n{error}",
        "conn.established": "Ligacao estabelecida (ftth_editor)",
        "conn.connected_as": "Ligado como {user}",
        "conn.connect_first": "Ligue-se primeiro via 'Constructel: Ligar ao WYRE'.",

        # -- Status --
        "status.title": "Constructel Bridge - Estado",
        "status.not_connected": "Nao ligado.\nUse 'Constructel: Ligar ao WYRE' para se ligar.",
        "status.connected_to": "Ligado a: {host}:{port}/{dbname}\n"
                               "Papel: {user}\n"
                               "Utilizador: {bridge_user}\n"
                               "User ID: {bridge_user_id}\n"
                               "Hooks ativos: {hooks}",

        # -- User registration --
        "user.existing": "Utilizador existente: {username} (id={user_id})",
        "user.created": "Utilizador criado: {username} (id={user_id})",
        "user.error": "Erro no registo do utilizador: {error}",

        # -- Hooks --
        "hook.installed": "Hook instalado: {layer}",
        "hook.all_installed": "Hooks de edicao instalados nas camadas",
        "hook.commit_tagged": "app.current_user={user} para commit em {layer}",
        "hook.exec_error": "executeSql indisponivel ({error})",

        # -- QGIS PG connection --
        "pg.configured": "Ligacao QGIS 'constructel_bridge' configurada",
        "pg.already_configured": "Ligacao QGIS 'constructel_bridge' ja configurada — ignorada",

        # -- Layer datasource check --
        "layers.bad_host": "{count} camada(s) ainda apontam para localhost ({names}). "
                           "Guarde novamente o projeto com o servidor correto ({host}).",

        # -- Language dialog --
        "lang.title": "Constructel Bridge - Idioma",
        "lang.prompt": "Selecione o idioma:",
        "lang.restart": "Idioma alterado para {lang}. Reinicie o QGIS ou volte a ligar para efeito completo.",

        # -- Load project from DB --
        "project.title": "Constructel Bridge - Carregar projeto",
        "project.select": "Selecione um projeto para carregar:",
        "project.none_found": "Nenhum projeto QGIS encontrado na base de dados.",
        "project.no_table": "Nenhum armazenamento de projetos QGIS encontrado na base.\n"
                            "Guarde primeiro um projeto via Projeto > Guardar como > PostgreSQL.",
        "project.loaded": "Projeto '{name}' carregado com sucesso.",
        "project.load_error": "Erro ao carregar o projeto '{name}':\n{error}",
        "project.list_error": "Erro ao listar os projetos:\n{error}",

        # -- Onboarding: Page 1 - User profile --
        "onboard.user.title": "Perfil do utilizador",
        "onboard.user.subtitle": "A sua identidade sera associada a cada modificacao de camada.",
        "onboard.user.welcome_new": "<b>Bem-vindo!</b> E um novo utilizador.<br>"
                                    "A sua conta foi criada automaticamente na base de dados WYRE.",
        "onboard.user.welcome_back": "<b>Bem-vindo de volta!</b> A sua conta ja existe na base de dados WYRE.",
        "onboard.user.field_id": "Identificador:",
        "onboard.user.field_firstname": "Nome:",
        "onboard.user.field_firstname_hint": "Nome (opcional)",
        "onboard.user.field_lastname": "Apelido:",
        "onboard.user.field_lastname_hint": "Apelido",
        "onboard.user.field_email": "Email:",
        "onboard.user.field_email_hint": "Email",
        "onboard.user.note": "<small>Estas informacoes sao armazenadas em <code>ref.users</code> "
                             "e utilizadas para rastrear modificacoes.</small>",

        # -- Onboarding: Page 2 - Plugins --
        "onboard.plugins.title": "Plugins recomendados",
        "onboard.plugins.subtitle": "Estes plugins sao opcionais mas melhoram a experiencia FTTH no QGIS.",
        "onboard.plugins.already_active": "{name}  [ja instalado e ativo]",
        "onboard.plugins.installed_inactive": "{name}  [instalado, nao ativo]",
        "onboard.plugins.note": "<small>Os plugins serao instalados a partir do repositorio oficial do QGIS. "
                                "Tambem pode instala-los manualmente via "
                                "<i>Extensoes > Instalar/Gerir Extensoes</i>.</small>",

        # -- Plugin descriptions --
        "plugin.nominatim.desc": (
            "Localizador de enderecos baseado no Nominatim (OpenStreetMap). "
            "Permite pesquisar um endereco ou local diretamente na barra de pesquisa "
            "do QGIS e fazer zoom ate ele."
        ),
        "plugin.filtermate.desc": (
            "Filtragem avancada multi-camadas. Permite filtrar rapidamente "
            "as entidades visiveis em varias camadas simultaneamente, "
            "ideal para isolar uma zona POP ou seccao de cabo."
        ),
        "plugin.qfieldsync.desc": (
            "Sincronizacao com QField (aplicacao de campo). "
            "Permite preparar um projeto QGIS para o terreno, empacotar "
            "as camadas PostGIS e sincronizar as modificacoes."
        ),
        "plugin.resource_sharing.desc": (
            "Partilha de recursos (estilos QML, simbolos SVG, modelos de layout). "
            "Permite descarregar os recursos Constructel (estilos de camadas FTTH) "
            "a partir do servidor interno. Indispensavel para ter os estilos atualizados."
        ),

        # -- Onboarding: Page 3 - Resource Sharing --
        "onboard.rs.title": "QGIS Resource Sharing",
        "onboard.rs.subtitle": "Repositorio de recursos Constructel (estilos QML, simbolos, modelos).",
        "onboard.rs.installed": "<b>QGIS Resource Sharing esta instalado.</b><br>"
                                "O repositorio Constructel sera configurado automaticamente.",
        "onboard.rs.not_installed": "<b>QGIS Resource Sharing nao esta instalado.</b><br>"
                                    "Instale-o na pagina anterior ou manualmente, "
                                    "depois volte a executar a configuracao inicial.",
        "onboard.rs.repo_name": "Nome do repositorio:",
        "onboard.rs.repo_url": "URL:",
        "onboard.rs.auto_configure": "Configurar este repositorio automaticamente",
        "onboard.rs.note": "<small>Este repositorio contem os estilos de camadas, simbolos SVG "
                           "e modelos de layout especificos do projeto WYRE FTTH.<br>"
                           "URL do servidor interno: <code>http://192.168.160.31:9081/</code></small>",

        # -- Onboarding: Page 4 - Summary --
        "onboard.summary.title": "Configuracao concluida",
        "onboard.summary.subtitle": "Resumo das acoes realizadas.",
        "onboard.summary.header": "<b>Acoes realizadas:</b><ul>",
        "onboard.summary.footer": "</ul><br><i>Pode voltar a executar este assistente a qualquer momento via "
                                  "menu Base de dados > Constructel Bridge > Constructel: Configuracao inicial.</i>",

        # -- Onboarding: Actions --
        "onboard.action.profile_updated": "Perfil atualizado: {first_name} {last_name} ({email})",
        "onboard.action.profile_error": "Erro na atualizacao do perfil: {error}",
        "onboard.action.no_plugins": "Nenhum plugin adicional selecionado",
        "onboard.action.installer_unavailable": "Instalador de plugins indisponivel ({error}). "
                                                "Instale os plugins manualmente via Extensoes > Instalar.",
        "onboard.action.plugin_activated": "Plugin ativado: {pid}",
        "onboard.action.plugin_installed": "Plugin instalado: {pid}",
        "onboard.action.plugin_error": "Erro no plugin {pid}: {error}",
        "onboard.action.rs_not_installed": "QGIS Resource Sharing nao instalado — repositorio nao configurado",
        "onboard.action.rs_updated": "Repositorio '{name}' atualizado: {url}",
        "onboard.action.rs_exists": "Repositorio '{name}' ja configurado",
        "onboard.action.rs_added": "Repositorio '{name}' adicionado: {url}",
        "onboard.action.onboarding_done": "Configuracao inicial marcada como concluida",

        # -- Wizard --
        "wizard.title": "Constructel Bridge - Configuracao inicial",
    },
}
