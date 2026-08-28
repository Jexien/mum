# MUM - Assistant de Tri & Nettoyage de Photos et Videos Multi-Sources

MUM est une application locale dotee d'une interface web permettant de scanner, trier, dedoublonner et centraliser automatiquement l'ensemble de vos photos et videos stockees sur disques durs, smartphones, cles USB, Google Drive et Google Photos.

---

## Fonctionnalites majeures

- **Photos et Videos** :
  - Formats images : `.jpg`, `.jpeg`, `.png`, `.heic`, `.webp`, `.tiff`, `.bmp`, `.raw`, `.cr2`, `.nef`, `.arw`, `.dng`...
  - Formats videos : `.mp4`, `.mov`, `.avi`, `.mkv`, `.wmv`, `.m4v`, `.3gp`, `.webm`, `.mts`...
  - Extraction automatique des vignettes, durees, resolutions et dates de prise de vue.
- **Smartphones et Peripheriques USB** :
  - Detection automatique des appareils photos et telephones Android / iPhone connectes en USB (repertoires `DCIM`, `Camera`, `WhatsApp`).
  - **Garantie de Securite Telephone** : Vos photos de smartphone sont sauvegardees sur le disque cible mais **JAMAIS effacees de votre telephone**.
- **Google Drive et Google Photos** :
  - Scan direct de l'ensemble de vos photos et videos Google Drive via l'API officielle.
  - Inspection et indexation directe dans les fichiers `.zip` Google Takeout sans decompression requise.
  - Assistant interactif pour l'exportation Google Photos.
- **Dedoublonnage double niveau** :
  - **Doublons exacts (100%)** : Detection instantanee par hachage de contenu SHA-256 et suppression en 1 clic.
  - **Photos et Videos similaires (pHash)** : Rapprochement visuel des rafales et versions compressees avec interface comparative et badge "Recommande".
- **Centralisation et Nettoyage securise** :
  - Rassemblement de l'ensemble de vos medias sur le disque dur cible de votre choix.
  - Copie atomique et verifiee octet par octet avant toute liberation d'espace sur les disques sources.

---

## Demarrage rapide

### 1. Installer les dependances
```bash
pip install -r config/requirements.txt
playwright install
```

### 2. Configuration (optionnelle pour Google Drive)
Copiez `config/.env.example` vers `config/.env` et renseignez vos cles d'API Google si vous souhaitez connecter Google Drive.

### 3. Lancer l'application
```bash
python mum.py
```
L'interface s'ouvre automatiquement dans votre navigateur sur `http://127.0.0.1:5000`.

---

## Structure du projet

```text
mum/
├── config/                     # Configurations, variables d'environnement & dependances
│   ├── .env                    # Vos cles reelles (ignore par Git)
│   ├── .env.example            # Gabarit de configuration
│   ├── pyproject.toml          # Specifications PEP 518/621
│   └── requirements.txt        # Dependances Python
├── data/                       # Donnees locales d'execution (ignorees par Git)
│   ├── cache/                  # Cache des miniatures & photos Google Drive
│   ├── db/                     # Base SQLite locale
│   ├── profiles/               # Profils de navigation temporaires
│   └── tokens/                 # Jetons d'authentification Google OAuth
├── docs/                       # Documentations completes
├── src/                        # Code source modulaire
│   └── mum/
│       ├── config.py           # Configuration et constantes
│       ├── database.py         # Schema de base de donnees photos & videos
│       ├── deduplicator.py     # Moteur de dedoublonnage (exacte et pHash)
│       ├── gdrive.py           # Connecteur Google Drive
│       ├── media_processor.py  # Analyseur multimedia & vignettes
│       ├── scanner.py          # Scanner disques & telephones
│       ├── takeout.py          # Assistant Google Takeout
│       ├── takeout_scanner.py  # Scanner d'archives ZIP Takeout en streaming
│       ├── transfer.py         # Moteur de transfert et nettoyage securise
│       └── app.py              # Serveur Flask et interface web
├── .gitignore                  # Protection stricte anti-fuite
└── mum.py                      # Point d'entree principal unique
```

---

## Licence
Ce projet est distribue sous la licence **PolyForm Noncommercial License 1.0.0** (usage libre et gratuit, revente et exploitation commerciale interdites).
