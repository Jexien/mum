# Politique de sécurité & Signalement de vulnérabilités

## 🔒 Confidentialité par conception

MUM est conçu pour fonctionner **100% en local** sur la machine de l'utilisateur :
- Aucune photo ou métadonnée n'est transmise à des serveurs tiers.
- Les identifiants Google Drive OAuth restent cantonnés sur votre machine dans le sous-dossier `data/tokens/`.
- Le fichier `.gitignore` est préconfiguré pour bloquer tout envoi de secrets ou données utilisateur.

## 🚨 Signaler une vulnérabilité

Si vous découvrez une faille de sécurité ou un problème de fuite potentielle de données :
- **Ne publiez pas de ticket public (issue)** avec des détails exploitables.
- Contactez directement les mainteneurs du projet par email ou via un canal sécurisé.
