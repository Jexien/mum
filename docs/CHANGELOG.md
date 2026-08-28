# Journal des modifications (Changelog)

Toutes les modifications notables apportées à ce projet sont documentées dans ce fichier.
Format conforme à [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/) et norme **ISO 8601** (`AAAA-MM-JJ`).

## [2.0.0] - 2026-08-28

### Ajouté
- **Prise en charge complète des Vidéos** : support de `.mp4`, `.mov`, `.avi`, `.mkv`, `.wmv`, `.m4v`, `.webm`... avec extraction des durées, résolutions et vignettes dynamiques via OpenCV.
- **Détection des Smartphones USB** : scan des répertoires `DCIM` et médias Android / iPhone connectés en USB.
- **Protection absolue des téléphones** : garde-fou garantissant qu'aucune suppression n'est jamais effectuée sur les smartphones lors des opérations de nettoyage.
- **Moteur de déduplication double niveau** :
  - Doublons 100% exacts (hachage de contenu SHA-256).
  - Médias similaires et rafales (distance de Hamming sur hachage perceptuel `pHash`).
- **Moteur de centralisation sécurisée** : copie atomique vers un fichier `.tmp`, validation de l'intégrité de la copie avant suppression sécurisée sur les disques sources.
- **Interface utilisateur enrichie** : sélecteur de disque cible avec jauge d'espace libre, onglet dédié aux doublons exacts, galerie comparative des similaires et barre de progression en temps réel.
- **Architecture modulaire (`src/mum/`)** : séparation claire en modules spécialisés (`config`, `database`, `media_processor`, `scanner`, `gdrive`, `takeout`, `deduplicator`, `transfer`, `app`).

## [1.0.0] - 2026-08-28

### Ajouté
- Initialisation du dépôt open source sous licence PolyForm Noncommercial 1.0.0.
- Première version du scanner de photos et connecteur Google Drive.
- Protection stricte anti-fuite de données via `.gitignore`.
