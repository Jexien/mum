"""Moteur de centralisation sécurisée, déduplication et nettoyage des disques sources."""

import os
import shutil
import time
from pathlib import Path
from .database import get_db_connection
from .media_processor import calculate_sha256

transfer_progress = {
    "running": False,
    "total": 0,
    "current": 0,
    "moved": 0,
    "copied_phone": 0,
    "duplicates_merged": 0,
    "errors": 0,
    "status": "Inactif"
}

def safe_centralize_and_clean(dest_dir_str):
    """Centralise toutes les photos et vidéos sur le disque cible,
    fusionne les doublons exacts, et efface les sources (sauf téléphone).
    """
    global transfer_progress
    transfer_progress["running"] = True
    transfer_progress["status"] = "Vérification des volumes..."

    dest_dir = Path(dest_dir_str)
    dest_dir.mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, source_name, is_phone, media_type, file_path,
               file_name, file_size, sha256, date_taken
        FROM photos 
        ORDER BY sha256, is_phone DESC, file_size DESC
    ''')
    media_list = list(cursor.fetchall())
    
    total_files = len(media_list)
    transfer_progress["total"] = total_files
    transfer_progress["current"] = 0
    transfer_progress["moved"] = 0
    transfer_progress["copied_phone"] = 0
    transfer_progress["duplicates_merged"] = 0
    transfer_progress["errors"] = 0

    seen_hashes = set()
    processed_count = 0

    for item in media_list:
        processed_count += 1
        transfer_progress["current"] = processed_count
        transfer_progress["status"] = f"Transfert {processed_count}/{total_files} : {item['file_name']}"

        pid = item['id']
        path_str = item['file_path']
        name = item['file_name']
        is_phone = bool(item['is_phone'])
        sha256 = item['sha256']
        expected_size = item['file_size']

        source_file = Path(path_str)

        # 1. Gestion des doublons exacts : si ce hash a déjà été transféré
        if sha256 and sha256 in seen_hashes:
            transfer_progress["duplicates_merged"] += 1
            # Si ce n'est pas un téléphone, on supprime cette copie redondante de la source
            if not is_phone and source_file.exists() and not str(source_file).startswith(str(dest_dir)):
                try:
                    os.remove(str(source_file))
                except Exception:
                    pass
            cursor.execute('DELETE FROM photos WHERE id = ?', (pid,))
            conn.commit()
            continue

        # Si le fichier est déjà à destination finale
        if str(source_file).startswith(str(dest_dir)):
            if sha256:
                seen_hashes.add(sha256)
            continue

        if not source_file.exists():
            transfer_progress["errors"] += 1
            continue

        # 2. Préparation du chemin cible
        # Résolution des conflits de noms de fichiers
        target_final = dest_dir / name
        counter = 1
        while target_final.exists():
            # Si le fichier existant à destination a déjà le même hash, pas besoin de recréer
            existing_hash = calculate_sha256(str(target_final), max_blocks=50)
            if existing_hash == sha256:
                break
            name_parts = os.path.splitext(name)
            target_final = dest_dir / f"{name_parts[0]}_{counter}{name_parts[1]}"
            counter += 1

        target_temp = dest_dir / f"{target_final.name}.mum_tmp"
        copy_success = False

        try:
            # 3. Copie de sécurité vers .tmp
            shutil.copy2(str(source_file), str(target_temp))

            # 4. Vérification d'intégrité industrielle (taille exacte)
            if target_temp.stat().st_size == expected_size:
                target_temp.replace(target_final)  # Renommage atomique
                copy_success = True
            else:
                if target_temp.exists():
                    target_temp.unlink()
        except Exception:
            if target_temp.exists():
                try:
                    target_temp.unlink()
                except Exception:
                    pass

        # 5. Validation et action sur la source
        if copy_success:
            if sha256:
                seen_hashes.add(sha256)

            if not is_phone:
                # DÉPLACEMENT SÉCURISÉ : la source est supprimée (copie validée)
                try:
                    os.remove(str(source_file))
                except Exception:
                    pass
                transfer_progress["moved"] += 1
                cursor.execute('UPDATE photos SET file_path = ?, source_name = "Disque Cible" WHERE id = ?', (str(target_final), pid))
            else:
                # 🛡️ PROTECTION DU TÉLÉPHONE : L'original reste INTACT sur le smartphone
                transfer_progress["copied_phone"] += 1
                cursor.execute('UPDATE photos SET file_path = ?, source_name = "Disque Cible (Original Téléphone Préservé)" WHERE id = ?', (str(target_final), pid))
            
            conn.commit()
        else:
            transfer_progress["errors"] += 1

    conn.close()
    transfer_progress["status"] = "Terminé avec succès !"
    transfer_progress["running"] = False
    return transfer_progress
