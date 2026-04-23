# Dépôt QGIS Privé - Constructel

Dépôt privé de plugins QGIS et de ressources partagées, accessible **uniquement depuis le réseau interne Constructel**.

## Informations réseau

| Paramètre | Valeur |
|---|---|
| **Serveur** | `192.168.160.31` (wyre) |
| **Réseau autorisé** | `192.168.160.0/24` |
| **Port** | `8080` |
| **URL Plugin Repo** | `http://192.168.160.31:8080/plugin-repo/plugins.xml` |
| **URL Resource Sharing (HTTP/ZIP)** | `http://192.168.160.31:8080/resource-repo/` |
| **URL Resource Sharing (git push/pull)** | `http://192.168.160.31:9082/` |

> Si un DNS interne est configuré, remplacez l'IP par `gis-server.constructel.lan`.

## Structure

```
qgis_repo/
├── plugin-repo/                 # Dépôt de plugins QGIS
│   ├── plugins.xml              # Généré automatiquement
│   └── packages/                # Fichiers ZIP des plugins
├── resource-repo/               # Dépôt QGIS Resource Sharing
│   ├── metadata.ini             # Registre des collections
│   └── collections/
│       └── constructel_sketches/  # Collection Constructel
│           ├── symbol/          # Symboles XML
│           ├── svg/             # Fichiers SVG
│           ├── style/           # Styles QML
│           ├── image/           # Images raster
│           ├── processing/      # Scripts Processing
│           ├── models/          # Modèles Processing (.model3)
│           └── preview/         # Aperçus
├── scripts/                     # Scripts d'administration
├── serve.py                     # Serveur HTTP (filtrage IP intégré)
└── nginx.conf                   # Config Nginx (production)
```

## Sécurité réseau

L'accès est restreint au réseau Constructel `192.168.160.0/24` :
- **serve.py** : filtrage IP applicatif (403 Forbidden pour les IP hors réseau)
- **nginx.conf** : directives `allow`/`deny` au niveau du serveur web

Pour ajouter d'autres sous-réseaux Constructel :
```bash
# serve.py
python3 serve.py --allowed-networks 192.168.160.0/24 10.10.0.0/16

# nginx.conf : ajouter une ligne "allow X.X.X.X/XX;" avant "deny all;"
```

## Démarrage rapide

### 1. Ajouter un plugin au dépôt

```bash
./scripts/add_plugin.sh /chemin/vers/MonPlugin.1.0.zip --base-url http://192.168.160.31:8080

# Ou manuellement :
cp MonPlugin.1.0.zip plugin-repo/packages/
python3 scripts/update_plugin_repo.py --base-url http://192.168.160.31:8080
```

### 2. Ajouter des ressources partagées (côté serveur)

1. Placez vos fichiers dans `resource-repo/collections/<nom_collection>/` (symbol/, svg/, style/, etc.)
2. Ajoutez la collection dans `resource-repo/metadata.ini`
3. Générez les ZIPs :
   ```bash
   ./scripts/build_resource_zips.sh
   ```

### 3. Publier une collection depuis un poste utilisateur (git push)

Le dépôt `resource-repo.git` (bare) est exposé sur le port **9082** en
smart HTTP : tout poste du réseau interne peut `clone` / `pull` / `push`.

**Bootstrap unique (à exécuter une fois sur le serveur) :**
```bash
./scripts/sync_bare_from_worktree.sh
```
Aligne le bare repo sur le contenu actuel de `resource-repo/` et crée
`resource-repo/.sync-enabled` pour activer la synchro automatique via
le hook `post-receive`.

**Ensuite, depuis n'importe quel poste interne :**

Option A — via le plugin [FilterMate](https://github.com/imagodata/filter_mate)
(extension `favorites_sharing`) : bouton *Publish to Resource Sharing*
dans le gestionnaire de favoris. Le plugin écrit dans le clone local ;
il reste à faire `git push` dans ce clone.

Option B — via le helper shell fourni :
```bash
./scripts/publish_collection.sh /chemin/local/ma_collection nom_collection
```
Ce script clone le bare repo, copie `/chemin/local/ma_collection/`
sous `collections/nom_collection/`, commite et pousse. Le serveur
régénère automatiquement les ZIPs via le hook `post-receive`.

Option C — git à la main :
```bash
git clone http://192.168.160.31:9082/ resource-repo
cd resource-repo
# ... éditer collections/... ...
git add -A && git commit -m "update" && git push
```

> **Note :** `metadata.ini` doit être mis à jour manuellement pour
> référencer les nouvelles collections — le hook ne le fait pas
> automatiquement.

### 4. Lancer le serveur

**Développement / petite équipe :**
```bash
python3 serve.py --port 8080
```

**Production (Nginx) :**
```bash
sudo cp nginx.conf /etc/nginx/sites-available/qgis-repo
sudo ln -s /etc/nginx/sites-available/qgis-repo /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Pour activer le push git en production, installer `fcgiwrap` :
```bash
sudo apt install fcgiwrap
sudo systemctl enable --now fcgiwrap
# Le block `server { listen 9082; ... }` de nginx.conf fait le reste.
```

**Service systemd (démarrage automatique) :**
```bash
sudo cp qgis-repo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qgis-repo
```

## Configuration côté QGIS (pour les utilisateurs)

### Dépôt de plugins

1. QGIS > Extensions > Installer/Gérer les extensions > **Paramètres**
2. Cliquer **Ajouter...** sous "Dépôts d'extensions"
3. Nom : `Plugins Constructel`
4. URL : `http://192.168.160.31:8080/plugin-repo/plugins.xml`

### Resource Sharing

1. Installer le plugin **QGIS Resource Sharing** depuis le dépôt officiel
2. Extensions > Resource Sharing > **Open Resource Sharing**
3. Onglet **Settings** > **Add Repository**
4. Nom : `Ressources Constructel`
5. URL : `http://192.168.160.31:8080/resource-repo/`

## Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `QGIS_REPO_BASE_URL` | URL de base du serveur | `http://192.168.160.31:8080` |
