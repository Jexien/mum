# MUM - Assistant Intelligent de Tri & Nettoyage de Photos et Vidéos Multi-Sources

**MUM** est une application locale dotée d'une interface web moderne permettant de scanner, trier, dédoublonner et centraliser automatiquement l'ensemble de vos **photos ET vidéos** stockées sur disques durs, smartphones, clés USB, Google Drive et Google Photos.

---

## 🌟 Fonctionnalités majeures

- 📸 **Photos ET Vidéos** :
  - Formats images : `.jpg`, `.jpeg`, `.png`, `.heic`, `.webp`, `.tiff`, `.bmp`, `.raw`, `.cr2`, `.nef`, `.arw`, `.dng`...
  - Formats vidéos : `.mp4`, `.mov`, `.avi`, `.mkv`, `.wmv`, `.m4v`, `.3gp`, `.webm`, `.mts`...
  - Extraction automatique des vignettes, durées, résolutions et dates de prise de vue.
- 📱 **Smartphones & Périphériques USB** :
  - Détection automatique des appareils photos et téléphones Android / iPhone connectés en USB (répertoires `DCIM`, `Camera`, `WhatsApp`).
  - 🛡️ **Garantie de Sécurité Téléphone** : Vos photos de smartphone sont sauvegardées sur le disque cible mais **JAMAIS effacées de votre téléphone**.
- ☁️ **Google Drive & Google Photos** :
  - Scan direct de l'ensemble de vos photos et vidéos Google Drive via l'API officielle.
  - Assistant interactif pas-à-pas pour l'exportation Google Photos (Takeout).
- ⚡ **Déduplication double niveau** :
  - **Doublons exacts (100%)** : Détection instantanée par hachage de contenu SHA-256 et suppression en 1 clic.
  - **Photos & Vidéos similaires (pHash)** : Rapprochement visuel des rafales et versions compressées avec interface comparative et badge "⭐ Recommandé".
- 💾 **Centralisation & Nettoyage sécurisé** :
  - Rassemblement de l'ensemble de vos médias sur le disque dur cible de votre choix.
  - Copie atomique et vérifiée octet par octet avant toute libération d'espace sur les disques sources.

---

## 🚀 Démarrage rapide

### 1. Installer les dépendances
```bash
pip install -r config/requirements.txt
playwright install
```

### 2. Configuration (optionnelle pour Google Drive)
Copiez `config/.env.example` vers `config/.env` et renseignez vos clés d'API Google si vous souhaitez connecter Google Drive.

### 3. Lancer l'application
```bash
python mum.py
```
L'interface s'ouvre automatiquement dans votre navigateur sur `http://127.0.0.1:5000`.

---

## 📂 Structure du projet

```text
mum/
├── config/                     # Configurations, variables d'environnement & dépendances
│   ├── .env                    # Vos clés réelles (ignoré par Git)
│   ├── .env.example            # Gabarit de configuration
│   ├── pyproject.toml          # Spécifications PEP 518/621
│   └── requirements.txt        # Dépendances Python
├── data/                       # Données locales d'exécution (ignorées par Git)
│   ├── cache/                  # Cache des miniatures & photos Google Drive
│   ├── db/                     # Base SQLite locale
│   ├── profiles/               # Profils de navigation temporaires
│   └── tokens/                 # Jetons d'authentification Google OAuth
├── docs/                       # Documentations complètes
├── src/                        # Code source modulaire
│   └── mum/
│       ├── config.py           # Configuration et constantes
│       ├── database.py         # Schéma de base de données photos & vidéos
│       ├── deduplicator.py     # Moteur de déduplication (exacte et pHash)
│       ├── gdrive.py           # Connecteur Google Drive
│       ├── media_processor.py  # Analyseur multimédia & vignettes
│       ├── scanner.py          # Scanner disques & téléphones
│       ├── takeout.py          # Assistant Google Takeout
│       ├── transfer.py         # Moteur de transfert et nettoyage sécurisé
│       └── app.py              # Serveur Flask et interface web
├── .gitignore                  # Protection stricte anti-fuite
└── mum.py                      # Point d'entrée principal unique
```

---

## 📄 Licence
Ce projet est distribué sous la licence **PolyForm Noncommercial License 1.0.0** (usage libre et gratuit, revente et exploitation commerciale interdites).
