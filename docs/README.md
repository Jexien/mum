# MUM - Assistant Intelligent de Tri & Nettoyage de Photos / Cloud

**MUM** est une application locale dotée d'une interface web moderne permettant de scanner, trier, dédoublonner et organiser efficacement vos collections de photos stockées sur disque local, disques externes ou sur Google Drive / Google Photos (via Takeout).

---

## 🌟 Fonctionnalités

- 🔍 **Scan multi-sources** : Détection des disques locaux, clés USB/cartes SD, et intégration Google Drive via API OAuth.
- ⚡ **Dédoublonnage intelligent** : Algorithme de hachage perceptuel (`imagehash` / pHash, aHash, dHash) pour détecter les doublons exacts et visuels.
- ⭐ **Évaluation & Scoring automatique** : Notation automatique de la qualité des clichés (résolution, netteté, ratio).
- 🧹 **Nettoyage sécurisé** : Suppression ciblée des doublons ou déplacement vers un dossier d'archivage sans risque de perte accidentelle.
- 🌐 **Interface Web interactive** : Tableau de bord local complet en Flask & Tailwind CSS avec prévisualisation des photos.
- 🔐 **Respect de la vie privée** : Traitement 100% local, aucun envoi de données ou photos vers des serveurs tiers.

---

## 🚀 Installation & Démarrage

### 1. Prérequis
- **Python 3.9+** installé sur votre machine.
- Google Chrome (requis pour le module d'exportation Google Takeout).

### 2. Cloner le dépôt
```bash
git clone https://github.com/votre-nom/mum.git
cd mum
```

### 3. Installer les dépendances
```bash
pip install -r requirements.txt
playwright install
```

### 4. Configuration
Copiez le fichier d'exemple `.env.example` en `.env` :
```bash
cp .env.example .env
```
Remplissez les informations dans le fichier `.env` avec vos identifiants Google OAuth si vous souhaitez utiliser l'intégration Google Drive.

### 5. Lancer l'application
```bash
python mum.py
```
L'interface s'ouvrira automatiquement sur `http://127.0.0.1:5000`.

---

## 🔒 Confidentialité & Sécurité des données

Le projet intègre une configuration `.gitignore` stricte afin d'éviter toute fuite accidentelle :
- Les fichiers `.env` et jetons OAuth (`google_token_*.json`, `credentials.json`) ne sont jamais versionnés.
- La base de données locale (`memoire_photos.db`), les dossiers de cache (`cache_google_drive/`) et les profils temporaires (`chrome_takeout_profile/`) sont exclus du suivi Git.
- Les fichiers multimédias locaux sont ignorés par défaut.

---

## 📄 Licence

Ce projet est distribué sous la licence **PolyForm Noncommercial License 1.0.0**.

- ✅ **Utilisation personnelle & non-commerciale autorisée** : Vous êtes libre d'utiliser, modifier, adapter et partager ce logiciel pour vos besoins personnels, éducatifs ou communautaires.
- ❌ **Revente & Exploitation commerciale strictement interdite** : Toute revente, intégration dans un produit payant ou exploitation commerciale du code source (ou de ses dérivés) est formellement interdite sans accord écrit préalable.
