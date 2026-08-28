# Journal des modifications (Changelog)

Toutes les modifications notables apportées à ce projet sont documentées dans ce fichier.
Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/) et ce projet respecte la norme de datation **ISO 8601** (`AAAA-MM-JJ`).

## [1.0.0] - 2026-08-28

### Ajouté
- Initialisation du dépôt open source sous licence PolyForm Noncommercial 1.0.0.
- Module de scan local multi-disques (disques internes, externes, cartes SD, smartphones).
- Intégration Google Drive via OAuth2 et API Drive v3.
- Assistant interactif pas-à-pas pour l'exportation Google Takeout (Playwright CDP).
- Algorithmes de hachage perceptuel (`imagehash` / pHash, dHash, aHash) pour la détection de doublons.
- Algorithme de scoring de qualité d'image (résolution, netteté, ratio).
- Tableau de bord web interactif (Flask, Tailwind CSS).
- Structure de répertoires normalisée (`src/`, `data/`, `docs/`) avec isolation stricte des données et secrets.
- Protection stricte anti-fuite de données via `.gitignore`.
