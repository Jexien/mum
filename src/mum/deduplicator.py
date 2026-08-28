"""Moteur de déduplication (doublons exacts et similaires/rafales)."""

import sqlite3
import imagehash
from .database import get_db_connection
from .config import SIMILARITY_HASH_THRESHOLD

def hamming_distance(hex_str1, hex_str2):
    """Calcule la distance de Hamming entre deux hexadécimaux de pHash."""
    if not hex_str1 or not hex_str2 or len(hex_str1) != len(hex_str2):
        return 999
    try:
        val1 = int(hex_str1, 16)
        val2 = int(hex_str2, 16)
        return bin(val1 ^ val2).count('1')
    except Exception:
        return 999

def get_master_sort_key(item, target_drive=None):
    """Clé de tri pour élire la meilleure copie :
    1. Note de qualité (résolution, netteté)
    2. Présence sur le disque cible
    3. Fichier local plutôt que cloud
    """
    # item = (id, source, path, res, rating, is_phone, gdrive_acc, media_type, duration, size, sha256, phash)
    path = item['file_path'] if isinstance(item, sqlite3.Row) else item[2]
    rating = item['rating'] if isinstance(item, sqlite3.Row) else item[4]
    is_target = 1 if target_drive and path.startswith(target_drive) else 0
    return (rating or 0.0, is_target)

def get_exact_duplicate_groups(page=1, per_page=20, target_drive=None):
    """Récupère les groupes de doublons 100% exacts (même SHA-256 ou même taille & nom)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    offset = (page - 1) * per_page

    # Recherche des groupes par SHA-256
    cursor.execute('''
        SELECT sha256, COUNT(*) as cnt, SUM(file_size) as total_size, media_type
        FROM photos 
        WHERE sha256 IS NOT NULL AND sha256 != ''
        GROUP BY sha256 
        HAVING cnt > 1 
        ORDER BY total_size DESC 
        LIMIT ? OFFSET ?
    ''', (per_page, offset))

    groups_summary = cursor.fetchall()
    groups = []

    for row in groups_summary:
        sha = row['sha256']
        cursor.execute('''
            SELECT id, source_name, file_path, file_name, file_size, resolution,
                   duration, date_taken, rating, is_phone, media_type
            FROM photos 
            WHERE sha256 = ?
        ''', (sha,))
        items = list(cursor.fetchall())
        if len(items) < 2:
            continue

        # Tri pour déterminer la meilleure version à conserver
        items.sort(key=lambda it: (it['rating'] or 0, 1 if target_drive and it['file_path'].startswith(target_drive) else 0), reverse=True)
        
        master = items[0]
        group_items = []
        for i, it in enumerate(items):
            group_items.append({
                "id": it['id'],
                "name": it['file_name'],
                "source": it['source_name'],
                "path": it['file_path'],
                "size_kb": round(it['file_size'] / 1024),
                "resolution": it['resolution'] or "N/A",
                "duration": it['duration'] or 0.0,
                "date": it['date_taken'] or "Inconnue",
                "is_phone": bool(it['is_phone']),
                "media_type": it['media_type'],
                "rating": it['rating'] or 0.0,
                "is_master": (i == 0)
            })

        groups.append({
            "group_id": sha[:12],
            "media_type": row['media_type'],
            "count": len(group_items),
            "file_name": master['file_name'],
            "size_str": f"{round(master['file_size'] / 1024)} Ko",
            "items": group_items
        })

    conn.close()
    return groups

def get_similar_media_groups(max_groups=30, threshold=SIMILARITY_HASH_THRESHOLD, target_drive=None):
    """Détecte les photos et vidéos similaires (rafales, versions recompressées ou recadrées)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Récupération de tous les médias avec un pHash valide
    cursor.execute('''
        SELECT id, source_name, file_path, file_name, file_size, resolution,
               duration, date_taken, rating, is_phone, media_type, phash, sha256
        FROM photos 
        WHERE phash IS NOT NULL AND phash != ''
        ORDER BY date_taken DESC, file_size DESC
    ''')
    rows = list(cursor.fetchall())
    conn.close()

    clusters = []
    visited_ids = set()

    for i in range(len(rows)):
        row_a = rows[i]
        if row_a['id'] in visited_ids:
            continue

        cluster = [row_a]
        phash_a = row_a['phash']

        for j in range(i + 1, min(i + 150, len(rows))):
            row_b = rows[j]
            if row_b['id'] in visited_ids:
                continue

            # Ne regrouper que des types compatibles (image avec image, vidéo avec vidéo)
            if row_a['media_type'] != row_b['media_type']:
                continue

            # Si c'est déjà un doublon exact de hash, il est déjà dans la section doublons exacts
            if row_a['sha256'] == row_b['sha256']:
                continue

            dist = hamming_distance(phash_a, row_b['phash'])
            if dist <= threshold:
                cluster.append(row_b)
                visited_ids.add(row_b['id'])

        if len(cluster) > 1:
            visited_ids.add(row_a['id'])
            # Tri interne : meilleure qualité en premier
            cluster.sort(key=lambda it: (it['rating'] or 0, it['file_size']), reverse=True)
            
            cluster_items = []
            for k, it in enumerate(cluster):
                cluster_items.append({
                    "id": it['id'],
                    "name": it['file_name'],
                    "source": it['source_name'],
                    "path": it['file_path'],
                    "size_kb": round(it['file_size'] / 1024),
                    "resolution": it['resolution'] or "N/A",
                    "duration": it['duration'] or 0.0,
                    "date": it['date_taken'] or "Inconnue",
                    "is_phone": bool(it['is_phone']),
                    "media_type": it['media_type'],
                    "rating": it['rating'] or 0.0,
                    "is_recommended": (k == 0)
                })

            clusters.append({
                "cluster_id": f"sim_{row_a['id']}",
                "media_type": row_a['media_type'],
                "count": len(cluster_items),
                "items": cluster_items
            })

        if len(clusters) >= max_groups:
            break

    return clusters
