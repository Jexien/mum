# Architecture technique de MUM

## 📐 Vue d'ensemble

MUM est architecturé autour d'un noyau Python intégrant un serveur web Flask local et plusieurs modules spécialisés :

```
mum/
├── data/                      # Données locales d'exécution (ignorées par Git)
│   ├── cache/                 # Cache des vignettes et aperçus Google Drive
│   ├── db/                    # Base de données locale SQLite (memoire_photos.db)
│   ├── profiles/              # Profil Chrome dédié à l'assistant Takeout
│   └── tokens/                # Jetons d'authentification OAuth2 chiffrés
├── docs/                      # Documentation technique et manuels
│   ├── ARCHITECTURE.md
│   └── CONFIGURATION.md
├── src/                       # Modules applicatifs
│   └── mum/                   # Package Python MUM
├── .env.example               # Modèle de variables d'environnement
├── .gitignore                 # Filtrage strict anti-fuite de données
├── CHANGELOG.md               # Historique des versions (ISO 8601)
├── CONTRIBUTING.md            # Guide des contributeurs
├── LICENSE                    # Licence PolyForm Noncommercial 1.0.0
├── main.py                    # Point d'entrée standard
├── mum.py                     # Script d'exécution principal
├── pyproject.toml             # Spécification du projet PEP 518/621
├── README.md                  # Présentation générale
└── requirements.txt           # Dépendances Python
```

## ⚙️ Composants clés

1. **Scanner de médias** (`scanner`) : Parcourt les chemins de stockage locaux (disques, USB, téléphones WIA/MTP) et calcule les caractéristiques des images (dimensions, hachage perceptuel `imagehash`).
2. **Connecteur Google Drive** (`gdrive`) : Interagit avec l'API Google Drive v3 pour récupérer les photos en haute résolution sans nécessiter d'export lourd.
3. **Assistant Google Takeout** (`takeout`) : Automatise le guidage pas-à-pas dans Google Takeout via Playwright CDP connecté à une instance Chrome sécurisée.
4. **Moteur de déduplication** : Rapproche les images par hachage exact et visuel (tolérance paramétrable) pour isoler les doublons.
5. **Interface Web Locale** : Serveur Flask léger délivrant une interface responsive (Tailwind CSS) avec interaction temps réel via API REST.
