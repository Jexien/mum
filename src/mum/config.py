"""Configuration centrale de l'application MUM."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Chemins principaux
BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
PROFILES_DIR = DATA_DIR / "profiles"
TOKENS_DIR = DATA_DIR / "tokens"
DB_DIR = DATA_DIR / "db"
DOCS_DIR = BASE_DIR / "docs"

# Création automatique des répertoires de stockage
for directory in (CACHE_DIR, PROFILES_DIR, TOKENS_DIR, DB_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# Base de données
DB_PATH = str(DB_DIR / "memoire_photos.db")

# Chargement du fichier .env
load_dotenv()
if (CONFIG_DIR / ".env").exists():
    load_dotenv(dotenv_path=CONFIG_DIR / ".env")

# Formats multimédias pris en charge
IMAGE_EXTENSIONS = (
    '.jpg', '.jpeg', '.png', '.heic', '.webp', 
    '.tiff', '.tif', '.bmp', '.gif', 
    '.raw', '.cr2', '.nef', '.arw', '.dng', '.orf', '.rw2', '.pef'
)

VIDEO_EXTENSIONS = (
    '.mp4', '.mov', '.avi', '.mkv', '.wmv', 
    '.m4v', '.3gp', '.webm', '.flv', '.mts', '.m2ts', '.ts'
)

ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS + VIDEO_EXTENSIONS

# Google Drive API Configuration
GOOGLE_DRIVE_SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly'
]

GOOGLE_CLIENT_CONFIG = {
    "installed": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "project_id": os.getenv("GOOGLE_PROJECT_ID", "mon-assistant-photo"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "redirect_uris": [os.getenv("GOOGLE_REDIRECT_URI", "http://localhost")]
    }
}

# Seuil de similarité pour les images (distance de Hamming sur pHash, 0 = identique, <= 6 = très proche/rafale)
SIMILARITY_HASH_THRESHOLD = 6

def find_chrome_exe():
    """Localise l'exécutable Google Chrome installé sur la machine (Windows)."""
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LocalAppData", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
        path, _ = winreg.QueryValueEx(key, None)
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
    return None
