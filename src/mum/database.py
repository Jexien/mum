"""Gestion de la base de données SQLite pour l'indexation des photos et vidéos."""

import sqlite3
import os
from .config import DB_PATH

def get_db_connection():
    """Crée une connexion optimisée à la base de données SQLite."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.row_factory = sqlite3.Row
    return conn

def init_db(reset=False):
    """Initialise le schéma de la base de données."""
    if reset and os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except Exception:
            pass

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT,
            is_phone BOOLEAN DEFAULT 0,
            media_type TEXT DEFAULT 'image',
            file_path TEXT UNIQUE,
            file_name TEXT,
            file_size INTEGER,
            resolution TEXT,
            duration REAL DEFAULT 0.0,
            date_taken TEXT,
            sha256 TEXT,
            phash TEXT,
            rating REAL,
            gdrive_account_id INTEGER
        )
    ''')

    # Index pour accélérer les recherches de doublons et tris
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_name_size ON photos(file_name, file_size)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sha256 ON photos(sha256)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_phash ON photos(phash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_type ON photos(media_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_is_phone ON photos(is_phone)')
    
    conn.commit()
    conn.close()

def insert_media_batch(batch):
    """Insère un lot de fichiers multimédias dans la base de données."""
    if not batch:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany('''
        INSERT OR REPLACE INTO photos (
            source_name, is_phone, media_type, file_path, file_name,
            file_size, resolution, duration, date_taken, sha256, phash, rating, gdrive_account_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', batch)
    conn.commit()
    conn.close()

def delete_media_by_ids(ids):
    """Supprime des enregistrements de la base par leurs IDs."""
    if not ids:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany('DELETE FROM photos WHERE id = ?', [(pid,) for pid in ids])
    conn.commit()
    conn.close()
