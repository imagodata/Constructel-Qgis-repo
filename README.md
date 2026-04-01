# Dépôt QGIS Privé - Constructel

Dépôt privé de plugins QGIS et de ressources partagées, accessible **uniquement depuis le réseau interne Constructel**.

## Informations réseau

| Paramètre | Valeur |
|---|---|
| **Serveur** | `192.168.160.31` (wyre) |
| **Réseau autorisé** | `192.168.160.0/24` |
| **Port** | `8080` |
| **URL Plugin Repo** | `http://192.168.160.31:8080/plugin-repo/plugins.xml` |
| **URL Resource Sharing** | `http://192.168.160.31:8080/resource-repo/` |

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

### 2. Ajouter des ressources partagées

1. Placez vos fichiers dans `resource-repo/collections/<nom_collection>/` (symbol/, svg/, style/, etc.)
2. Ajoutez la collection dans `resource-repo/metadata.ini`
3. Générez les ZIPs :
   ```bash
   ./scripts/build_resource_zips.sh
   ```

### 3. Lancer le serveur

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
