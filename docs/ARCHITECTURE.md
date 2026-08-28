# Architecture technique de MUM

## Vue d'ensemble

MUM est architecture autour d'un noyau Python integrant un serveur web Flask local et plusieurs modules specialises :

```text
mum/
├── config/                    # Configurations, variables d'environnement & dependances
│   ├── .env                   # Vos cles reelles (ignore par Git)
│   ├── .env.example           # Gabarit de configuration
│   ├── pyproject.toml         # Specifications PEP 518/621
│   └── requirements.txt       # Dependances Python
├── data/                      # Donnees locales d'execution (ignorees par Git)
│   ├── cache/                 # Cache des vignettes et apercus Google Drive
│   ├── db/                    # Base de donnees locale SQLite (memoire_photos.db)
│   ├── profiles/              # Profil Chrome dedie a l'assistant Takeout
│   └── tokens/                # Jetons d'authentification OAuth2 chiffres
├── docs/                      # Documentation technique et manuels
│   ├── ARCHITECTURE.md
│   ├── CHANGELOG.md           # Historique des versions (ISO 8601)
│   ├── CONFIGURATION.md
│   ├── CONTRIBUTING.md
│   ├── LICENSE                # Licence PolyForm Noncommercial 1.0.0
│   ├── README.md
│   └── SECURITY.md
├── src/                       # Modules applicatifs
│   └── mum/                   # Package Python MUM
├── .gitignore                 # Filtrage strict anti-fuite de donnees
└── mum.py                     # Script d'execution principal unique
```

## Composants cles

1. **Scanner de medias** (`scanner`) : Parcourt les chemins de stockage locaux (disques, USB, telephones WIA/MTP) et calcule les caracteristiques des images et videos.
2. **Connecteur Google Drive** (`gdrive`) : Interagit avec l'API Google Drive v3 pour recuperer les photos et videos sans export lourd.
3. **Scanner Takeout ZIP** (`takeout_scanner`) : Analyse et indexe les photos et videos directement dans les fichiers `.zip` sans decompression.
4. **Assistant Google Takeout** (`takeout`) : Automatise le guidage pas-a-pas dans Google Takeout via Playwright CDP.
5. **Moteur de deduplication** (`deduplicator`) : Rapproche les images par hachage exact (SHA-256) et visuel (pHash) pour isoler les doublons.
6. **Moteur de transfert securise** (`transfer`) : Sauvegarde atomique sur disque cible et nettoyage securise (hors telephone).
7. **Interface Web Locale** (`app`) : Serveur Flask leger delivrant une interface responsive (Tailwind CSS) avec interaction temps reel.
