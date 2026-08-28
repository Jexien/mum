# Guide de configuration de MUM

## 🔧 Variables d'environnement (.env)

Pour activer les fonctionnalités cloud (Google Drive), copiez le fichier d'exemple et définissez vos clés :

```bash
cp .env.example .env
```

### Paramètres disponibles

| Variable | Description | Exemple |
| :--- | :--- | :--- |
| `GOOGLE_CLIENT_ID` | Identifiant client OAuth 2.0 généré sur Google Cloud Console | `12345-abc.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | Secret client OAuth 2.0 | `GOCSPX-xxxxxxxx` |
| `GOOGLE_PROJECT_ID` | Nom ou ID du projet Google Cloud | `mon-projet-photos` |
| `GOOGLE_REDIRECT_URI` | URI de redirection OAuth locale | `http://localhost` |

---

## 🔑 Création des identifiants Google Cloud

1. Rendez-vous sur la [Google Cloud Console](https://console.cloud.google.com/).
2. Créez un nouveau projet (ex: `mum-photo-assistant`).
3. Activez l'API **Google Drive API** dans la bibliothèque d'APIs.
4. Dans l'onglet **Identifiants** :
   - Cliquez sur **Créer des identifiants** > **ID client OAuth**.
   - Type d'application : **Application pour ordinateur de bureau** (Desktop App).
5. Copiez le Client ID et le Client Secret dans votre fichier `.env`.
