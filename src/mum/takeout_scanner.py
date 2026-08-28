"""Module de détection et d'inspection directe des archives Google Takeout (.zip et dossiers).

Permet de lire, analyser et prévisualiser les photos et vidéos DIRECTEMENT dans les archives
.zip sans nécessiter aucune décompression préalable sur le disque.
"""

import os
import io
import json
import zipfile
import hashlib
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageFile
import imagehash
import cv2
import numpy as np

Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True

from .config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, ALL_MEDIA_EXTENSIONS
from .database import insert_media_batch

def find_user_downloads_dir():
    """Détecte le dossier Téléchargements de l'utilisateur Windows."""
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        dl_path = Path(user_profile) / "Downloads"
        if dl_path.exists():
            return dl_path
    return None

def detect_takeout_archives():
    """Détecte automatiquement les fichiers Takeout .zip ou dossiers dans Téléchargements."""
    found = []
    dl_dir = find_user_downloads_dir()
    if not dl_dir or not dl_dir.exists():
        return found

    try:
        for entry in dl_dir.iterdir():
            # Cas 1 : Fichiers .zip Takeout
            if entry.is_file() and entry.suffix.lower() == '.zip':
                if 'takeout' in entry.name.lower() or entry.name.lower().startswith('takeout-'):
                    size_gb = round(entry.stat().st_size / (1024**3), 2)
                    found.append({
                        "type": "zip",
                        "name": entry.name,
                        "path": str(entry.resolve()),
                        "size_gb": size_gb,
                        "date": datetime.fromtimestamp(entry.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
                    })
            # Cas 2 : Dossier décompressé Takeout
            elif entry.is_dir() and ('takeout' in entry.name.lower() or entry.name.lower() == 'google photos'):
                found.append({
                    "type": "folder",
                    "name": entry.name,
                    "path": str(entry.resolve()),
                    "size_gb": 0,
                    "date": datetime.fromtimestamp(entry.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
                })
    except Exception:
        pass

    return found

def parse_takeout_json_metadata(json_bytes):
    """Extrait la vraie date de prise de vue depuis le fichier .json généré par Google Photos."""
    try:
        data = json.loads(json_bytes.decode('utf-8', errors='ignore'))
        # Google Photos JSON structure : photoTakenTime.timestamp
        taken_time = data.get('photoTakenTime', {})
        ts = taken_time.get('timestamp')
        if ts:
            dt = datetime.fromtimestamp(int(ts))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        pass
    return None

def scan_takeout_zip(zip_path_str, progress_dict, path_key):
    """Scanne une archive .zip Google Takeout en flux sans décompression sur disque."""
    zip_path = Path(zip_path_str)
    if not zip_path.exists():
        progress_dict[path_key] = {"count": 0, "status": "Archive introuvable", "done": True, "error": True}
        return

    progress_dict[path_key] = {"count": 0, "status": "Ouverture du fichier ZIP...", "done": False, "error": False}

    batch = []
    count = 0
    processed_entries = 0

    try:
        with zipfile.ZipFile(str(zip_path), 'r') as zf:
            infolist = zf.infolist()
            total_entries = len(infolist)
            progress_dict[path_key]["total"] = total_entries
            progress_dict[path_key]["percent"] = 0
            
            # Indexer d'abord les fichiers .json de métadonnées pour des recherches ultra-rapides
            json_meta_map = {}
            for info in infolist:
                if info.filename.lower().endswith('.json'):
                    json_meta_map[info.filename.lower()] = info

            progress_dict[path_key]["status"] = f"Analyse de {total_entries} éléments..."

            for info in infolist:
                processed_entries += 1
                percent = min(99, int((processed_entries / max(1, total_entries)) * 100))
                progress_dict[path_key]["percent"] = percent

                if info.is_dir():
                    continue

                ext = os.path.splitext(info.filename)[1].lower()
                if ext not in ALL_MEDIA_EXTENSIONS:
                    continue

                file_size = info.file_size
                if file_size < 1024:
                    continue

                file_name = os.path.basename(info.filename)
                media_type = "video" if ext in VIDEO_EXTENSIONS else "image"
                virtual_path = f"zip://{zip_path.resolve()}#{info.filename}"

                # Recherche du fichier JSON associé (ex: photo.jpg.json)
                json_key = (info.filename + '.json').lower()
                date_taken = None
                if json_key in json_meta_map:
                    try:
                        j_bytes = zf.read(json_meta_map[json_key])
                        date_taken = parse_takeout_json_metadata(j_bytes)
                    except Exception:
                        pass

                if not date_taken:
                    dt = datetime(*info.date_time)
                    date_taken = dt.strftime('%Y-%m-%d %H:%M:%S')

                # Analyse des données en mémoire
                raw_bytes = zf.read(info)
                sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
                
                resolution = "Inconnue"
                duration = 0.0
                p_hash = None
                rating = 5.0

                if media_type == "image":
                    try:
                        with Image.open(io.BytesIO(raw_bytes)) as img:
                            w, h = img.size
                            if w >= 150 and h >= 150:
                                resolution = f"{w}x{h}"
                                megapixels = (w * h) / 1_000_000
                                size_mb = file_size / (1024 * 1024)
                                rating = round(min(10.0, max(1.0, (size_mb * 1.2) + (megapixels * 0.8))), 1)
                                p_hash = str(imagehash.phash(img))
                    except Exception:
                        pass
                else:
                    # Cas Vidéo : décodage mémoire
                    try:
                        size_mb = file_size / (1024 * 1024)
                        rating = round(min(10.0, max(1.0, size_mb * 0.5)), 1)
                    except Exception:
                        pass

                source_label = f"📦 Google Takeout ({zip_path.name})"
                batch.append((
                    source_label,
                    0,
                    media_type,
                    virtual_path,
                    file_name,
                    file_size,
                    resolution,
                    duration,
                    date_taken,
                    sha256_hash,
                    p_hash,
                    rating,
                    None
                ))

                count += 1
                progress_dict[path_key]["count"] = count
                progress_dict[path_key]["status"] = f"Analyse ZIP : {count} médias trouvés ({percent}%)"

                if len(batch) >= 50:
                    insert_media_batch(batch)
                    batch = []

            if batch:
                insert_media_batch(batch)

        progress_dict[path_key]["percent"] = 100
        progress_dict[path_key]["status"] = f"Terminé ({count} médias indexés depuis le ZIP)"
        progress_dict[path_key]["done"] = True

    except Exception as e:
        progress_dict[path_key]["status"] = f"Erreur ZIP : {e}"
        progress_dict[path_key]["done"] = True
        progress_dict[path_key]["error"] = True

def extract_media_from_zip(virtual_path):
    """Extrait en mémoire les octets bruts d'un fichier stocké dans un .zip."""
    if not virtual_path.startswith("zip://"):
        return None
    try:
        content_part = virtual_path[6:]
        zip_path_str, internal_file = content_part.split("#", 1)
        with zipfile.ZipFile(zip_path_str, 'r') as zf:
            return zf.read(internal_file)
    except Exception:
        return None
