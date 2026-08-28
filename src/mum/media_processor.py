"""Analyse et traitement multimédia : calcul des métadonnées, hachages et vignettes."""

import os
import io
import hashlib
import time
import warnings
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageFile, ExifTags
import imagehash
import cv2
import numpy as np

# Suppression globale des avertissements Pillow (EXIF corrompu, palettes, fichiers tronqués)
warnings.filterwarnings("ignore")
Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True

from .config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

def calculate_sha256(file_path, block_size=65536, max_blocks=None):
    """Calcule le hash SHA-256 d'un fichier.
    Si max_blocks est spécifié, effectue un hachage rapide sur les premiers blocs.
    """
    hasher = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            blocks_read = 0
            while True:
                data = f.read(block_size)
                if not data:
                    break
                hasher.update(data)
                blocks_read += 1
                if max_blocks and blocks_read >= max_blocks:
                    break
        return hasher.hexdigest()
    except Exception:
        return None

def extract_exif_date(img):
    """Extrait la date de capture depuis les métadonnées EXIF de l'image de façon sécurisée."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            exif = img._getexif()
            if not exif:
                return None
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                if tag in ('DateTimeOriginal', 'DateTimeDigitized', 'DateTime'):
                    if isinstance(value, str):
                        # Format standard EXIF : 'YYYY:MM:DD HH:MM:SS'
                        dt = datetime.strptime(value[:19], '%Y:%m:%d %H:%M:%S')
                        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        pass
    return None

def convert_image_to_clean_rgb(img):
    """Convertit proprement une image PIL (y compris palettes et transparences) en RGB."""
    if img.mode in ('P', 'PA'):
        img = img.convert('RGBA')
    if img.mode in ('RGBA', 'LA'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    elif img.mode != 'RGB':
        return img.convert('RGB')
    return img

def analyze_image(file_path):
    """Analyse un fichier image et retourne ses métadonnées, résolutions et hashes."""
    try:
        file_size = os.path.getsize(file_path)
        if file_size < 1024:  # Moins de 1 Ko -> Ignorer
            return None

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(file_path) as raw_img:
                width, height = raw_img.size
                if width < 150 or height < 150:
                    return None

                date_taken = extract_exif_date(raw_img)
                # Conversion propre pour calcul du pHash
                clean_img = convert_image_to_clean_rgb(raw_img)
                try:
                    p_hash = str(imagehash.phash(clean_img))
                except Exception:
                    p_hash = None

        if not date_taken:
            mtime = os.path.getmtime(file_path)
            date_taken = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

        resolution = f"{width}x{height}"
        megapixels = (width * height) / 1_000_000
        size_mb = file_size / (1024 * 1024)
        rating = round(min(10.0, max(1.0, (size_mb * 1.2) + (megapixels * 0.8))), 1)
        sha256_hash = calculate_sha256(file_path)

        return {
            "media_type": "image",
            "resolution": resolution,
            "duration": 0.0,
            "date_taken": date_taken,
            "sha256": sha256_hash,
            "phash": p_hash,
            "rating": rating,
            "file_size": file_size,
        }
    except Exception:
        return None

def analyze_video(file_path):
    """Analyse un fichier vidéo et extrait durée, résolution, vignette et hash perceptuel."""
    try:
        file_size = os.path.getsize(file_path)
        if file_size < 10 * 1024:
            return None

        cap = cv2.VideoCapture(str(file_path))
        if not cap.isOpened():
            return None

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = round(frame_count / fps, 1) if fps > 0 else 0.0

        p_hash = None
        if frame_count > 10:
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(frame_count // 10, 50))
            ret, frame = cap.read()
            if ret and frame is not None:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_frame)
                try:
                    p_hash = str(imagehash.phash(pil_img))
                except Exception:
                    pass

        cap.release()

        mtime = os.path.getmtime(file_path)
        date_taken = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

        resolution = f"{width}x{height}" if width and height else "Inconnue"
        size_mb = file_size / (1024 * 1024)
        rating = round(min(10.0, max(1.0, (size_mb / max(1.0, duration * 0.5)) + ((width * height) / 2_000_000))), 1)
        sha256_hash = calculate_sha256(file_path)

        return {
            "media_type": "video",
            "resolution": resolution,
            "duration": duration,
            "date_taken": date_taken,
            "sha256": sha256_hash,
            "phash": p_hash,
            "rating": rating,
            "file_size": file_size,
        }
    except Exception:
        return None

def analyze_file(file_path):
    """Analyse un fichier quelconque (image ou vidéo) selon son extension."""
    ext = Path(file_path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return analyze_image(file_path)
    elif ext in VIDEO_EXTENSIONS:
        return analyze_video(file_path)
    return None

def generate_thumbnail_bytes(file_path, media_type="image", max_size=(320, 320)):
    """Génère un flux d'octets JPEG pour la prévisualisation dans l'interface web."""
    buf = io.BytesIO()
    try:
        raw_bytes = None
        if isinstance(file_path, str) and file_path.startswith("zip://"):
            import zipfile
            content_part = file_path[6:]
            zip_path_str, internal_file = content_part.split("#", 1)
            with zipfile.ZipFile(zip_path_str, 'r') as zf:
                raw_bytes = zf.read(internal_file)

        if raw_bytes is not None:
            if media_type == "video" or any(file_path.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
                img = Image.new('RGB', max_size, color='#4f46e5')
                img.save(buf, format='JPEG', quality=75)
                buf.seek(0)
                return buf
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    with Image.open(io.BytesIO(raw_bytes)) as raw_img:
                        clean_img = convert_image_to_clean_rgb(raw_img)
                        clean_img.thumbnail(max_size)
                        clean_img.save(buf, format='JPEG', quality=75)
                buf.seek(0)
                return buf

        # Cas Fichier physique vidéo
        if media_type == "video" or Path(file_path).suffix.lower() in VIDEO_EXTENSIONS:
            cap = cv2.VideoCapture(str(file_path))
            if cap.isOpened():
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cap.set(cv2.CAP_PROP_POS_FRAMES, min(frame_count // 10, 30))
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb_frame)
                    img.thumbnail(max_size)
                    img.save(buf, format='JPEG', quality=75)
                    buf.seek(0)
                    return buf
        
        # Cas Image physique
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(file_path) as raw_img:
                clean_img = convert_image_to_clean_rgb(raw_img)
                clean_img.thumbnail(max_size)
                clean_img.save(buf, format='JPEG', quality=75)
        buf.seek(0)
        return buf
    except Exception:
        return None
