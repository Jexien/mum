"""Moteur de détection et d'analyse des sources de médias (Disques, Smartphones, Google)."""

import os
import sys
import string
import shutil
from pathlib import Path
import concurrent.futures
import multiprocessing

from .config import ALL_MEDIA_EXTENSIONS
from .media_processor import analyze_file
from .database import insert_media_batch

def get_system_drives():
    """Détecte l'ensemble des disques et supports de stockage connectés."""
    drives = []
    
    # 1. Détection sous Windows via les lettres de lecteur
    if os.name == 'nt':
        for letter in string.ascii_uppercase:
            drive_root = f"{letter}:\\"
            if os.path.exists(drive_root):
                try:
                    usage = shutil.disk_usage(drive_root)
                    total_gb = round(usage.total / (1024**3), 1)
                    free_gb = round(usage.free / (1024**3), 1)
                    used_gb = round((usage.total - usage.free) / (1024**3), 1)
                    percent = round(((usage.total - usage.free) / usage.total) * 100, 1) if usage.total > 0 else 0
                except Exception:
                    total_gb, free_gb, used_gb, percent = 0, 0, 0, 0

                label = f"Disque ({letter}:)"
                drive_type = "disk"
                if letter == 'C':
                    label = "Disque Système (C:)"
                elif letter in ('A', 'B'):
                    continue

                drives.append({
                    "id": letter,
                    "name": label,
                    "path": drive_root,
                    "type": drive_type,
                    "is_phone": False,
                    "total_gb": total_gb,
                    "free_gb": free_gb,
                    "used_gb": used_gb,
                    "percent": percent
                })

    # 2. Détection des Smartphones & périphériques portables (DCIM / WPD)
    phone_drives = detect_connected_smartphones()
    drives.extend(phone_drives)

    if not drives:
        drives.append({
            "id": "C",
            "name": "Disque Principal (C:)",
            "path": "C:\\",
            "type": "disk",
            "is_phone": False,
            "total_gb": 0, "free_gb": 0, "used_gb": 0, "percent": 0
        })

    return drives

def detect_connected_smartphones():
    """Détecte les téléphones Android / iPhone connectés en mode stockage / DCIM."""
    phones = []
    if os.name != 'nt':
        return phones

    dcim_candidates = []
    for letter in string.ascii_uppercase:
        if letter in ('C', 'A', 'B'):
            continue
        base = f"{letter}:\\"
        if os.path.exists(base):
            for candidate in ("DCIM", "Internal shared storage/DCIM", "Stockage interne/DCIM", "Phone/DCIM", "Card/DCIM"):
                full_cand = os.path.join(base, candidate)
                if os.path.exists(full_cand):
                    dcim_candidates.append((letter, full_cand))

    for letter, p_path in dcim_candidates:
        phones.append({
            "id": f"phone_{letter}",
            "name": f"Smartphone / Appareil Photo ({letter}:\\DCIM)",
            "path": p_path,
            "type": "phone",
            "is_phone": True,
            "total_gb": 0,
            "free_gb": 0,
            "used_gb": 0,
            "percent": 0
        })

    return phones

def scan_directory(source_name, target_path, is_phone, progress_dict, path_key):
    """Parcourt récursivement un dossier pour indexer photos et vidéos en base avec progression précise."""
    target = Path(target_path)
    if not target.exists():
        progress_dict[path_key] = {
            "count": 0, "total": 0, "percent": 0,
            "status": "Dossier introuvable", "done": True, "error": True, "current_file": ""
        }
        return

    progress_dict[path_key] = {
        "count": 0, "total": 0, "percent": 0,
        "status": "Découverte des fichiers...", "done": False, "error": False, "current_file": ""
    }

    ignored_dirs = {
        '$RECYCLE.BIN', 'RECYCLER', 'RECYCLED', 'SYSTEM VOLUME INFORMATION',
        'WINDOWS', 'PROGRAM FILES', 'PROGRAM FILES (X86)', 'PROGRAMDATA',
        'NODE_MODULES', '.GIT', '__PYCACHE__', 'APPDATA'
    }

    # 1. Découverte rapide de tous les fichiers médias
    candidate_files = []
    try:
        for root, dirs, files in os.walk(str(target)):
            dirs[:] = [d for d in dirs if d.upper() not in ignored_dirs and not d.startswith('.')]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in ALL_MEDIA_EXTENSIONS:
                    candidate_files.append(Path(root) / f)
    except Exception as e:
        progress_dict[path_key] = {
            "count": 0, "total": 0, "percent": 0,
            "status": f"Erreur d'accès : {e}", "done": True, "error": True, "current_file": ""
        }
        return

    total_candidates = len(candidate_files)
    if total_candidates == 0:
        progress_dict[path_key] = {
            "count": 0, "total": 0, "percent": 100,
            "status": "Aucun fichier photo ou vidéo trouvé", "done": True, "error": False, "current_file": ""
        }
        return

    progress_dict[path_key]["total"] = total_candidates
    progress_dict[path_key]["status"] = f"Analyse de {total_candidates} médias..."

    cpu_cores = multiprocessing.cpu_count() or 4
    optimal_threads = min(32, cpu_cores * 2)

    def process_file_task(file_path):
        try:
            info = analyze_file(file_path)
            if not info:
                return (None, file_path.name)
            record = (
                source_name,
                1 if is_phone else 0,
                info["media_type"],
                str(file_path),
                file_path.name,
                info["file_size"],
                info["resolution"],
                info["duration"],
                info["date_taken"],
                info["sha256"],
                info["phash"],
                info["rating"],
                None
            )
            return (record, file_path.name)
        except Exception:
            return (None, file_path.name)

    batch = []
    indexed_count = 0
    scanned_count = 0

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=optimal_threads) as executor:
            futures = [executor.submit(process_file_task, f_path) for f_path in candidate_files]
            
            for future in concurrent.futures.as_completed(futures):
                scanned_count += 1
                res, filename = future.result()
                if res:
                    batch.append(res)
                    indexed_count += 1

                percent = min(99, int((scanned_count / total_candidates) * 100))
                progress_dict[path_key]["count"] = indexed_count
                progress_dict[path_key]["percent"] = percent
                progress_dict[path_key]["current_file"] = filename
                progress_dict[path_key]["status"] = f"Analyse {scanned_count}/{total_candidates} ({percent}%) - {indexed_count} indexés"

                if len(batch) >= 100:
                    insert_media_batch(batch)
                    batch = []

            if batch:
                insert_media_batch(batch)
                batch = []

        progress_dict[path_key]["percent"] = 100
        progress_dict[path_key]["status"] = f"Terminé ({indexed_count} photos & vidéos indexées)"
        progress_dict[path_key]["done"] = True
    except Exception as e:
        progress_dict[path_key]["status"] = f"Erreur : {e}"
        progress_dict[path_key]["done"] = True
        progress_dict[path_key]["error"] = True
