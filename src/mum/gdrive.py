"""Module d'intégration avec Google Drive pour la récupération de photos et vidéos."""

import os
import io
import shutil
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import (
    BASE_DIR, TOKENS_DIR, CACHE_DIR,
    GOOGLE_DRIVE_SCOPES, GOOGLE_CLIENT_CONFIG
)
from .media_processor import analyze_file
from .database import insert_media_batch

def get_google_credentials(account_id):
    """Récupère ou renouvelle le jeton OAuth2 pour un compte Google Drive donné."""
    token_file = TOKENS_DIR / f'google_token_{account_id}.json'
    token_path_str = str(token_file)
    creds = None

    if os.path.exists(token_path_str):
        try:
            creds = Credentials.from_authorized_user_file(token_path_str, GOOGLE_DRIVE_SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        
        if not creds:
            flow = InstalledAppFlow.from_client_config(GOOGLE_CLIENT_CONFIG, GOOGLE_DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path_str, 'w') as token:
            token.write(creds.to_json())

    return creds

def scan_gdrive_account(account_id, progress_dict, path_key):
    """Scanne et télécharge les métadonnées/aperçus des photos et vidéos Google Drive."""
    progress_dict[path_key] = {"count": 0, "status": "Connexion à Google Drive...", "done": False, "error": False}

    account_cache_dir = CACHE_DIR / f"compte_{account_id}"
    account_cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        creds = get_google_credentials(account_id)
        service = build('drive', 'v3', credentials=creds)
        page_token = None
        batch = []
        count = 0

        # Requête pour lister TOUTES les images et TOUTES les vidéos
        query = "mimeType contains 'image/' or mimeType contains 'video/' and trashed = false"

        while True:
            progress_dict[path_key]["status"] = f"Récupération ({count} médias)..."
            results = service.files().list(
                q=query,
                pageSize=100,
                fields="nextPageToken, files(id, name, size, mimeType)",
                pageToken=page_token
            ).execute()

            items = results.get('files', [])
            if not items:
                break

            for item in items:
                file_id = item['id']
                file_name = item['name']
                mime_type = item.get('mimeType', '')
                is_video = 'video' in mime_type

                cache_path = account_cache_dir / f"{file_id}_{file_name}"
                
                # Téléchargement local de l'aperçu si nécessaire
                if not cache_path.exists():
                    request_dl = service.files().get_media(fileId=file_id)
                    with open(str(cache_path), 'wb') as fh:
                        downloader = MediaIoBaseDownload(fh, request_dl)
                        done = False
                        while not done:
                            _, done = downloader.next_chunk()

                info = analyze_file(str(cache_path))
                if info:
                    batch.append((
                        f"Google Drive (Compte {account_id})",
                        0,
                        info["media_type"],
                        str(cache_path),
                        file_name,
                        info["file_size"],
                        info["resolution"],
                        info["duration"],
                        info["date_taken"],
                        info["sha256"],
                        info["phash"],
                        info["rating"],
                        account_id
                    ))
                    count += 1
                    progress_dict[path_key]["count"] = count

                if len(batch) >= 50:
                    insert_media_batch(batch)
                    batch = []

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        if batch:
            insert_media_batch(batch)

        progress_dict[path_key]["status"] = f"Terminé ({count} médias récupérés)"
        progress_dict[path_key]["done"] = True

    except Exception as e:
        progress_dict[path_key]["status"] = f"Erreur Google Drive : {e}"
        progress_dict[path_key]["done"] = True
        progress_dict[path_key]["error"] = True
