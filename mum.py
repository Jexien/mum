import os
import sys
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
import sqlite3
import multiprocessing
import io
import warnings
import concurrent.futures
import shutil

def install_dependencies():
    packages = {
        "flask": "flask", 
        "Pillow": "PIL", 
        "imagehash": "imagehash",
        "playwright": "playwright",
    }
    for package, import_name in packages.items():
        try:
            __import__(import_name)
        except ImportError:
            print(f"Installation automatique de {package}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
            except Exception:
                pass

install_dependencies()

from flask import Flask, jsonify, request, send_file
from PIL import Image, ImageFile
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv

# --- Google Drive : contrairement a Google Photos, cette API n'a pas ete restreinte par
# Google et permet toujours de lister/telecharger les fichiers directement (pas de Takeout requis).
load_dotenv()
GOOGLE_DRIVE_SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
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

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
PROFILES_DIR = DATA_DIR / "profiles"
TOKENS_DIR = DATA_DIR / "tokens"
DB_DIR = DATA_DIR / "db"

for _d in (CACHE_DIR, PROFILES_DIR, TOKENS_DIR, DB_DIR):
    _d.mkdir(parents=True, exist_ok=True)

def get_google_credentials(account_id):
    token_file = TOKENS_DIR / f'google_token_{account_id}.json'
    old_token_file = BASE_DIR / f'google_token_{account_id}.json'
    if not token_file.exists() and old_token_file.exists():
        try:
            shutil.move(str(old_token_file), str(token_file))
        except Exception:
            token_file = old_token_file

    token_path_str = str(token_file)
    creds = None
    if os.path.exists(token_path_str):
        creds = Credentials.from_authorized_user_file(token_path_str, GOOGLE_DRIVE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(GOOGLE_CLIENT_CONFIG, GOOGLE_DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path_str, 'w') as token:
            token.write(creds.to_json())
    return creds

def find_chrome_exe():
    """Localise l'executable Chrome installe sur la machine (Windows)."""
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

Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True
warnings.filterwarnings('ignore')

DB_NAME = str(DB_DIR / "memoire_photos.db")
SUPPORTED_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.heic', '.webp')

app = Flask(__name__)
scan_progress = {}
scans_active = 0
TARGET_DRIVE = None
guide_status = {"step": "", "done": True, "error": False}
gdrive_accounts = 0

def init_db():
    if os.path.exists(DB_NAME):
        try:
            os.remove(DB_NAME)
        except Exception:
            pass
    conn = sqlite3.connect(DB_NAME)
    conn.execute('PRAGMA journal_mode=WAL')
    
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT,
            is_phone BOOLEAN,
            file_path TEXT,
            file_name TEXT,
            file_size INTEGER,
            resolution TEXT,
            rating REAL,
            gdrive_account_id INTEGER
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_file ON photos(file_name, file_size)')
    conn.commit()
    conn.close()

def open_browser():
    time.sleep(1.5)
    try:
        webbrowser.open('http://127.0.0.1:5000')
    except Exception:
        pass

def get_windows_drives():
    drives = []
    if os.name == 'nt':
        import string
        for letter in string.ascii_uppercase:
            if letter in ['A', 'B']: continue
            drive_letter = f"{letter}:\\"
            if os.path.exists(drive_letter):
                display_name = f"Disque Principal (C:)" if letter == 'C' else f"Disque ({letter}:)"
                drives.append({"name": display_name, "path": drive_letter, "type": "disk"})
    
    if not drives:
        drives.append({"name": "Disque Principal (C:)", "path": "C:\\", "type": "disk"})
    return drives

# ============================================================
# GUIDE VISUEL INTERACTIF POUR GOOGLE TAKEOUT (Playwright)
# ------------------------------------------------------------
# Le script NE clique JAMAIS a la place de l'utilisateur : il surligne
# l'element concerne et RELIT l'etat reel de la page en continu (cases
# cochees, changement d'ecran) pour savoir quand passer a l'etape
# suivante. Un bouton de secours cote interface permet aussi de forcer
# le passage a l'etape suivante si la detection automatique ne suit pas.
# ============================================================

guide_manual_advance = threading.Event()

def _highlight(page, locator, message):
    """Surligne l'element vise avec un cadre rouge (qui reste colle a l'element
    meme si la page bouge/scrolle, via un setInterval cote navigateur) + une infobulle."""
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
        handle = locator.element_handle()
        if not handle: return False
        js_code = """([el, msg]) => {
            document.querySelectorAll(".__mum_ui__").forEach(e => e.remove());
            if (window.__mum_interval__) { clearInterval(window.__mum_interval__); }
            if (!document.getElementById("__mum_style__")) {
                const st = document.createElement("style");
                st.id = "__mum_style__";
                st.innerHTML = "@keyframes mumpulse{0%,100%{opacity:1}50%{opacity:.35}}";
                document.head.appendChild(st);
            }
            const hl = document.createElement("div");
            hl.className = "__mum_ui__";
            hl.style.cssText = "position:fixed;border:4px solid #ef4444;border-radius:12px;z-index:999999;pointer-events:none;box-shadow:0 0 0 6px rgba(239,68,68,.3);animation:mumpulse 1s infinite;";
            document.body.appendChild(hl);
            const tip = document.createElement("div");
            tip.className = "__mum_ui__";
            tip.innerText = msg;
            tip.style.cssText = "position:fixed;background:#1e293b;color:#fff;padding:10px 16px;border-radius:10px;font-family:sans-serif;font-size:14px;font-weight:bold;z-index:999999;max-width:320px;";
            document.body.appendChild(tip);
            const reposition = () => {
                if (!document.body.contains(el)) return;
                const r = el.getBoundingClientRect();
                hl.style.left = (r.x - 6) + "px";
                hl.style.top = (r.y - 6) + "px";
                hl.style.width = (r.width + 12) + "px";
                hl.style.height = (r.height + 12) + "px";
                tip.style.left = r.x + "px";
                tip.style.top = (r.y + r.height + 14) + "px";
            };
            reposition();
            window.__mum_interval__ = setInterval(reposition, 200);
            // Detection PASSIVE d'un vrai clic utilisateur sur l'element surligne
            // (jamais de clic simule par le script : on ecoute seulement).
            window.__mum_click_detected__ = false;
            el.addEventListener("click", () => { window.__mum_click_detected__ = true; }, {capture: true});
        }"""
        page.evaluate(js_code, [handle, message])
        return True
    except Exception:
        return False

def _click_detected(page):
    """Vrai si l'utilisateur a reellement clique sur l'element actuellement surligne
    (ecoute passive posee par _highlight), sans jamais simuler de clic nous-memes."""
    try:
        return bool(page.evaluate("window.__mum_click_detected__ === true"))
    except Exception:
        return False

def _clear_highlight(page):
    try:
        page.evaluate('document.querySelectorAll(".__mum_ui__").forEach(e => e.remove())')
    except Exception:
        pass

def _wait_until(condition_fn, timeout_s=300, poll_interval=1.0):
    """Attend qu'une condition sur l'etat REEL de la page devienne vraie, ou que
    l'utilisateur force le passage via le bouton de secours de l'interface."""
    guide_manual_advance.clear()
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            if condition_fn():
                return True
        except Exception:
            pass
        if guide_manual_advance.is_set():
            guide_manual_advance.clear()
            return True
        time.sleep(poll_interval)
    return False

def _checkbox_states(page):
    try:
        return page.eval_on_selector_all(
            'input[type="checkbox"]',
            "els => els.map(el => ({name: el.getAttribute('name') || '', checked: el.checked}))"
        )
    except Exception:
        return []

def process_gdrive_task(account_id):
    global scan_progress, scans_active
    path_key = f"Google Drive (Compte {account_id})"
    scans_active += 1
    scan_progress[path_key] = {"count": 0, "status": "Connexion...", "done": False, "error": False}

    account_cache_dir = os.path.join(str(CACHE_DIR), f"compte_{account_id}")
    os.makedirs(account_cache_dir, exist_ok=True)

    try:
        creds = get_google_credentials(account_id)
        service = build('drive', 'v3', credentials=creds)
        page_token = None
        batch = []
        conn = sqlite3.connect(DB_NAME, timeout=30)
        cursor = conn.cursor()

        while True:
            scan_progress[path_key]["status"] = "Lecture du Drive..."
            results = service.files().list(
                q="mimeType contains 'image/' and trashed = false",
                pageSize=1000,
                fields="nextPageToken, files(id, name, size)",
                pageToken=page_token
            ).execute()

            items = results.get('files', [])
            for item in items:
                file_name = item.get('name')
                file_id = item.get('id')
                cache_path = os.path.join(account_cache_dir, f"{file_id}_{file_name}")

                try:
                    scan_progress[path_key]["status"] = f"Téléchargement : {file_name}"
                    if not os.path.exists(cache_path):
                        req = service.files().get_media(fileId=file_id)
                        with io.FileIO(cache_path, 'wb') as fh:
                            downloader = MediaIoBaseDownload(fh, req)
                            done = False
                            while not done:
                                status, done = downloader.next_chunk()

                    file_size = os.path.getsize(cache_path)
                    if file_size < 50 * 1024:
                        os.remove(cache_path)
                        continue

                    try:
                        with Image.open(cache_path) as img:
                            width, height = img.size
                    except Exception:
                        os.remove(cache_path)
                        continue
                    if width < 400 or height < 400:
                        os.remove(cache_path)
                        continue

                    resolution = f"{width}x{height}"
                    rating = round(min(10.0, max(1.0, (file_size / (1024 * 1024)) * 1.5 + ((width * height) / 1000000))), 1)

                    batch.append((f"💾 Google Drive {account_id}", False, cache_path, file_name, file_size, resolution, rating, account_id))
                    scan_progress[path_key]["count"] += 1
                except Exception:
                    continue

            if batch:
                cursor.executemany('INSERT INTO photos (source_name, is_phone, file_path, file_name, file_size, resolution, rating, gdrive_account_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', batch)
                conn.commit()
                batch = []

            page_token = results.get('nextPageToken')
            if not page_token: break

        conn.close()
        scan_progress[path_key]["status"] = "Terminé"
        scan_progress[path_key]["error"] = False
    except Exception as e:
        print(f"\n❌ Erreur Google Drive (compte {account_id}) : {type(e).__name__}: {e}\n")
        scan_progress[path_key]["status"] = f"Erreur : {type(e).__name__}: {str(e)[:120]}"
        scan_progress[path_key]["error"] = True

    scan_progress[path_key]["done"] = True
    scans_active -= 1

def run_takeout_guide():
    global guide_status
    guide_status = {"step": "Recherche de Google Chrome sur votre PC...", "done": False, "error": False}

    chrome_path = find_chrome_exe()
    if not chrome_path:
        guide_status = {"step": "Google Chrome introuvable sur ce PC. Installez Chrome, ou utilisez le tutoriel manuel.", "done": True, "error": True}
        return

    from playwright.sync_api import sync_playwright
    profile_dir = os.path.join(str(PROFILES_DIR), "chrome_takeout_profile")
    os.makedirs(profile_dir, exist_ok=True)
    debug_port = 9333
    chrome_proc = None

    try:
        # On lance un VRAI Chrome, normalement (pas via Playwright), pour eviter le message
        # de Google "Ce navigateur ou cette application ne sont peut-etre pas securises"
        # (declenche quand Google detecte un navigateur pilote directement par un outil
        # d'automatisation). On se contente ensuite de s'y CONNECTER via le protocole de
        # debogage Chrome (CDP), ce que Google ne peut pas detecter depuis une page web.
        guide_status["step"] = "Ouverture de Chrome..."
        chrome_proc = subprocess.Popen([
            chrome_path,
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ])

        # On attend que Chrome ouvre bien le port de debogage (essais successifs, jusqu'a 15s)
        browser = None
        with sync_playwright() as p:
            for _ in range(15):
                try:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
                    break
                except Exception:
                    time.sleep(1)
            if not browser:
                guide_status = {"step": "Impossible de se connecter à Chrome. Fermez toutes les fenêtres Chrome et relancez le guide.", "done": True, "error": True}
                return

            context = browser.contexts[0] if browser.contexts else browser.new_context()
            # On cree explicitement UN NOUVEL onglet et on y navigue nous-memes : cela evite
            # de se tromper d'onglet si le profil garde des onglets d'une session precedente.
            page = context.new_page()
            page.goto("https://takeout.google.com/", timeout=60000)

            guide_status["step"] = "Connectez-vous à votre compte Google si demandé (vous avez jusqu'à 5 minutes)... ou cliquez sur 'Étape suivante' dans l'app si vous êtes déjà sur la page Takeout."
            found = _wait_until(lambda: page.locator('div[data-id="photos"]').count() > 0, timeout_s=300)
            if not found:
                guide_status = {"step": "Page Google Takeout non détectée après 5 minutes. Vérifiez d'être bien connecté sur la page Chrome ouverte, puis relancez le guide.", "done": True, "error": True}
                return
            guide_status["step"] = "Page Takeout détectée, début du guidage..."
            page.wait_for_timeout(500)

            def locate_step(kind, value):
                try:
                    if kind == "role":
                        loc = page.get_by_role("button", name=value)
                        if loc.count() > 0: return loc.first
                    elif kind == "css":
                        loc = page.locator(value)
                        if loc.count() > 0: return loc.first
                    elif kind == "text":
                        loc = page.get_by_text(value, exact=False)
                        if loc.count() > 0: return loc.first
                except Exception:
                    pass
                return None

            def any_checkbox_checked():
                states = _checkbox_states(page)
                return any(c["checked"] for c in states)

            def only_photos_checked():
                states = _checkbox_states(page)
                if not states: return False
                photos_on = any(c["checked"] and "Photos" in c["name"] for c in states)
                others_on = any(c["checked"] and "Photos" not in c["name"] and c["name"] for c in states)
                return photos_on and not others_on

            # --- ETAPE 1 : tout deselectionner D'ABORD (indispensable, sinon la liste des
            # comptes/services deja coches rend la selection de Google Photos illisible) ---
            # On n'avance QUE si un vrai clic est detecte sur le bouton surligne, OU si
            # l'etat reel de la page montre que tout est deja decoche : on ne se contente
            # jamais d'un etat "deja bon par hasard" pour sauter l'etape silencieusement
            # sans que l'utilisateur ait eu le temps de voir/cliquer.
            guide_status["step"] = "1/5 : Cliquez sur 'Tout désélectionner' (surligné en rouge)."
            deselect_btn = (locate_step("css", 'button[aria-label="Tout désélectionner"]')
                             or locate_step("role", "Tout désélectionner")
                             or locate_step("text", "Deselect all"))
            if deselect_btn:
                _highlight(page, deselect_btn, "1/5 : Cliquez ici pour tout désélectionner")
                already_empty = not any_checkbox_checked()
                if already_empty:
                    # Rien n'etait a decocher : on laisse quand meme 2s le temps a
                    # l'utilisateur de voir le cadre rouge avant de passer a la suite.
                    page.wait_for_timeout(2000)
                else:
                    _wait_until(lambda: _click_detected(page) or not any_checkbox_checked(), timeout_s=300, poll_interval=0.5)
            _clear_highlight(page)

            # --- ETAPE 2 : cocher UNIQUEMENT Google Photos (une fois que tout est bien vide) ---
            guide_status["step"] = "2/5 : Cliquez maintenant sur la case 'Google Photos' (surlignée)."
            photos_row = locate_step("css", 'div[data-id="photos"]') or locate_step("text", "Google Photos")
            if photos_row:
                _highlight(page, photos_row, "2/5 : Cliquez ici pour cocher Google Photos")
            ok = _wait_until(lambda: _click_detected(page) or only_photos_checked(), timeout_s=600, poll_interval=0.5)
            _clear_highlight(page)
            if not ok:
                guide_status["step"] = "Sélection non confirmée automatiquement, vérifiez manuellement puis continuez dans la fenêtre Chrome."
                page.wait_for_timeout(3000)

            # --- ETAPE 3 : cliquer sur "Étape suivante" (changement d'ecran attendu) ---
            guide_status["step"] = "3/5 : Cliquez sur 'Étape suivante' (surligné)."
            next_btn = locate_step("role", "Étape suivante") or locate_step("role", "Next step") or locate_step("text", "Étape suivante")
            if next_btn:
                _highlight(page, next_btn, "Cliquez ici pour continuer")

            def export_settings_screen_reached():
                # La page "Choisir la frequence, le type de fichier et la destination"
                # n'a pas de selecteur stable connu : on combine plusieurs indices pour
                # etre robuste, au lieu de dependre d'un seul texte ou attribut.
                if page.locator('div[data-id="photos"]').count() == 0:
                    return True
                for txt in ["Fréquence de l'export", "Fréquence", "Type de fichier", "Taille de l'export", "Créer l'export", "Create export"]:
                    try:
                        if page.get_by_text(txt, exact=False).count() > 0:
                            return True
                    except Exception:
                        pass
                return False

            changed = _wait_until(export_settings_screen_reached, timeout_s=300, poll_interval=1.0)
            _clear_highlight(page)
            if not changed:
                guide_status["step"] = "Changement d'écran non détecté automatiquement. Continuez manuellement dans Chrome si besoin, ou cliquez sur 'Étape suivante' dans l'app pour forcer la suite."
                _wait_until(lambda: False, timeout_s=180)

            # --- ETAPE 4a : Taille de fichier (Google met "2 Go" par defaut, ce qui decoupe
            # l'export en tres nombreux petits fichiers ; on recommande 50 Go pour en avoir
            # beaucoup moins a re-assembler). Cette etape est indicative : si l'utilisateur
            # ne change rien, on continue quand meme apres un court delai. ---
            guide_status["step"] = ("4/5 : Réglez 'Taille de fichier' sur '50 Go' si possible (moins de fichiers "
                "à télécharger ensuite). Cliquez sur le menu surligné pour l'ouvrir, choisissez '50 Go'.")
            size_combo = locate_step("css", '[aria-label="Sélectionner la taille du fichier"]')
            if size_combo:
                _highlight(page, size_combo, "Cliquez ici, puis choisissez '50 Go' dans la liste")
                _wait_until(lambda: _click_detected(page), timeout_s=45, poll_interval=0.5)
            _clear_highlight(page)

            # --- ETAPE 4b : cliquer sur "Créer une exportation" (le vrai libellé du bouton) ---
            guide_status["step"] = "5/5 : Une fois les paramètres choisis, cliquez sur 'Créer une exportation' (surligné)."
            create_btn = (locate_step("role", "Créer une exportation")
                          or locate_step("text", "Créer une exportation")
                          or locate_step("text", "Créer l'export")
                          or locate_step("text", "Create export"))
            if create_btn:
                _highlight(page, create_btn, "Cliquez ici pour lancer l'export")

                def export_created():
                    if _click_detected(page):
                        return True
                    try:
                        return page.get_by_role("heading", name="Créer une exportation").count() == 0
                    except Exception:
                        return False

                _wait_until(export_created, timeout_s=600, poll_interval=1.0)
            else:
                guide_status["step"] = ("Bouton 'Créer une exportation' non trouvé automatiquement : terminez "
                    "cette étape manuellement dans Chrome (Fréquence = 'Exporter une fois', Type = .zip, Taille "
                    "= 50 Go si possible), puis cliquez sur 'Étape suivante' dans l'app une fois fait.")
                _wait_until(lambda: False, timeout_s=180)
            _clear_highlight(page)

            guide_status = {"step": "Export lancé ! Vous pouvez fermer Chrome et attendre l'email de Google (peut prendre plusieurs heures).", "done": True, "error": False}
    except Exception as e:
        guide_status = {"step": f"Erreur pendant le guide : {e}. Utilisez le tutoriel manuel en cas d'échec répété.", "done": True, "error": True}

def process_scan_task(source_name, target_path, is_phone):
    global scan_progress, scans_active
    scans_active += 1
    scan_progress[target_path] = {"count": 0, "status": "Analyse...", "done": False}
    
    conn = sqlite3.connect(DB_NAME, timeout=30)
    cursor = conn.cursor()
    
    try:
        def process_file(file_path):
            try:
                if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS: return None
                file_size = file_path.stat().st_size
                if file_size < 50 * 1024: return None
                file_name = file_path.name
                
                with Image.open(file_path) as img:
                    width, height = img.size
                    if width < 400 or height < 400: return None
                            
                resolution = f"{width}x{height}"
                rating = round(min(10.0, max(1.0, (file_size / (1024 * 1024)) * 1.5 + ((width * height) / 1000000))), 1)
                return (source_name, is_phone, str(file_path), file_name, file_size, resolution, rating, None)
            except Exception:
                return None

        cpu_cores = multiprocessing.cpu_count() or 4
        optimal_threads = min(32, cpu_cores * 2) 
            
        batch = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=optimal_threads) as executor:
            futures = []
            for root, dirs, files in os.walk(target_path):
                dirs[:] = [d for d in dirs if d.upper() not in ['$RECYCLE.BIN', 'RECYCLER', 'RECYCLED', 'SYSTEM VOLUME INFORMATION']]
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        futures.append(executor.submit(process_file, Path(root) / f))
                        
                        if len(futures) >= 150:
                            for f_comp in concurrent.futures.as_completed(futures):
                                res = f_comp.result()
                                if res:
                                    batch.append(res)
                                    scan_progress[target_path]["count"] += 1
                            if batch:
                                cursor.executemany('INSERT INTO photos (source_name, is_phone, file_path, file_name, file_size, resolution, rating, gdrive_account_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', batch)
                                conn.commit()
                                batch = []
                            futures = []

            for f_comp in concurrent.futures.as_completed(futures):
                res = f_comp.result()
                if res:
                    batch.append(res)
                    scan_progress[target_path]["count"] += 1
                    
            if batch:
                cursor.executemany('INSERT INTO photos (source_name, is_phone, file_path, file_name, file_size, resolution, rating, gdrive_account_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', batch)
                conn.commit()
    except Exception:
        pass

    scan_progress[target_path]["done"] = True
    scans_active -= 1
    conn.close()

@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/api/drives', methods=['GET'])
def api_drives():
    return jsonify(get_windows_drives())

@app.route('/api/set_target', methods=['POST'])
def api_set_target():
    global TARGET_DRIVE
    TARGET_DRIVE = request.json.get('path')
    return jsonify({"status": "ok", "target": TARGET_DRIVE})

@app.route('/api/scan', methods=['POST'])
def api_scan():
    data = request.json
    path = data.get('path')
    name = data.get('name')
    is_phone = data.get('is_phone', False)
    
    if not path or not os.path.exists(path): return jsonify({"status": "error"}), 400
    scan_progress[path] = {"count": 0, "status": "Analyse...", "done": False}
    threading.Thread(target=process_scan_task, args=(name, path, is_phone), daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/api/import_phone')
def api_import_phone():
    try:
        subprocess.Popen('wiaacmgr.exe')
        return jsonify({"status": "ok"})
    except:
        return jsonify({"status": "error"})

@app.route('/api/progress', methods=['GET'])
def api_progress():
    path = request.args.get('path')
    if path in scan_progress:
        data = dict(scan_progress[path])
        data.setdefault("error", False)
        return jsonify(data)
    return jsonify({"count": 0, "status": "En attente...", "done": False, "error": False})

@app.route('/api/scan_gdrive', methods=['POST'])
def api_scan_gdrive():
    global gdrive_accounts
    client_id = GOOGLE_CLIENT_CONFIG["installed"].get("client_id")
    client_secret = GOOGLE_CLIENT_CONFIG["installed"].get("client_secret")
    if not client_id or not client_secret:
        return jsonify({"status": "error", "message": "Clés Google manquantes. Vérifiez votre fichier .env (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)."}), 400
    gdrive_accounts += 1
    threading.Thread(target=process_gdrive_task, args=(gdrive_accounts,), daemon=True).start()
    return jsonify({"status": "started", "account_id": gdrive_accounts})

@app.route('/api/takeout_guide/start', methods=['POST'])
def api_takeout_guide_start():
    if not guide_status.get("done", True):
        return jsonify({"status": "already_running"})
    threading.Thread(target=run_takeout_guide, daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/api/takeout_guide/status', methods=['GET'])
def api_takeout_guide_status():
    return jsonify(guide_status)

@app.route('/api/takeout_guide/advance', methods=['POST'])
def api_takeout_guide_advance():
    guide_manual_advance.set()
    return jsonify({"status": "ok"})

@app.route('/api/live_stats', methods=['GET'])
def api_live_stats():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM photos')
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM (SELECT file_name FROM photos GROUP BY file_name, file_size HAVING COUNT(*) > 1)')
        duplicates = cursor.fetchone()[0]
        conn.close()
        return jsonify({"total": total, "duplicates_groups": duplicates, "scans_active": scans_active > 0, "target_drive": TARGET_DRIVE})
    except Exception:
        return jsonify({"total": 0, "duplicates_groups": 0, "scans_active": False, "target_drive": TARGET_DRIVE})

@app.route('/api/duplicates_paginated', methods=['GET'])
def api_duplicates_paginated():
    page = int(request.args.get('page', 1))
    per_page = 15
    offset = (page - 1) * per_page
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_name, file_size FROM photos 
        GROUP BY file_name, file_size 
        HAVING COUNT(*) > 1 ORDER BY file_size DESC LIMIT ? OFFSET ?
    ''', (per_page, offset))
    
    duplicates = cursor.fetchall()
    groups = []
    
    for name, size in duplicates:
        cursor.execute('SELECT id, source_name, file_path, resolution, rating, is_phone, gdrive_account_id FROM photos WHERE file_name = ? AND file_size = ?', (name, size))
        items = cursor.fetchall()
        
        items.sort(key=_duplicate_master_sort_key, reverse=True)
        
        master = items[0]
        master_is_target = TARGET_DRIVE and master[2].startswith(TARGET_DRIVE)
        replace_worse_id = None
        replace_worse_path = None
        
        # Vérification si une version de moins bonne qualité est sur la cible
        if TARGET_DRIVE and not master_is_target:
            for item in items[1:]:
                if item[2].startswith(TARGET_DRIVE):
                    replace_worse_id = item[0]
                    replace_worse_path = item[2]
                    break
        
        photos_in_group = []
        for i, item in enumerate(items):
            pid, source, path, res, rating, is_phone, gdrive_acc = item
            photos_in_group.append({
                "id": pid, "source": source, "path": path, "res": res, "is_phone": is_phone, "is_master": (i == 0)
            })
            
        groups.append({
            "name": name, 
            "size": f"{size // 1024} Ko", 
            "photos": photos_in_group,
            "can_replace": (replace_worse_id is not None),
            "master_id": master[0],
            "worse_id": replace_worse_id,
            "worse_path": replace_worse_path
        })
        
    conn.close()
    return jsonify({"groups": groups})

@app.route('/api/replace_target', methods=['POST'])
def api_replace_target():
    data = request.json
    master_id = data.get('master_id')
    worse_id = data.get('worse_id')
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT file_path, gdrive_account_id FROM photos WHERE id = ?', (master_id,))
    master = cursor.fetchone()
    cursor.execute('SELECT file_path FROM photos WHERE id = ?', (worse_id,))
    worse = cursor.fetchone()
    
    if not master or not worse:
        conn.close()
        return jsonify({"status": "error", "message": "Fichiers introuvables."})
        
    master_path, master_gdrive_id = master
    worse_path = worse[0]
    
    try:
        shutil.copy2(master_path, worse_path)
        os.remove(master_path)
            
        # Mettre à jour la base : le fichier 'worse' est supprimé, le 'master' prend son chemin
        cursor.execute('UPDATE photos SET file_path = ?, source_name = "Lecteur Cible (Mis à jour)" WHERE id = ?', (worse_path, master_id))
        cursor.execute('DELETE FROM photos WHERE id = ?', (worse_id,))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)})

    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/thumb/<int:photo_id>')
def api_thumb(photo_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT file_path, file_name, file_size FROM photos WHERE id = ?', (photo_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return "Introuvable", 404
        
    file_path = row[0]
    conn.close()

    try:
        # IMPORTANT : on utilise un bloc "with" pour etre certain que le fichier
        # image est bien REFERME immediatement apres generation de la miniature.
        # Sans ca, sous Windows, le fichier restait verrouille par ce processus
        # et la suppression ulterieure (/api/delete) echouait silencieusement
        # avec une erreur "fichier utilise par un autre processus".
        with Image.open(file_path) as img:
            img.thumbnail((300, 300))
            if img.mode != 'RGB': img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=60)
        buf.seek(0)
        return send_file(buf, mimetype='image/jpeg')
    except Exception:
        return "Erreur", 500

def _duplicate_master_sort_key(item):
    # item = (id, source, path, res, rating, is_phone, gdrive_acc)
    path = item[2]
    rating = item[4]
    is_target = 1 if TARGET_DRIVE and path.startswith(TARGET_DRIVE) else 0
    is_local = 0 if item[6] else 1  # colonne conservee pour compatibilite, toujours NULL desormais
    return (rating, is_target, is_local)

def _safe_delete_photo(cursor, pid):
    """Supprime UNE photo (fichier + ligne en base) de facon fiable : reessaie en cas
    de fichier momentanement verrouille, et ne retire la ligne de la base QUE si le
    fichier a vraiment disparu (ou n'existait deja plus). Renvoie (ok, info_dict)."""
    cursor.execute('SELECT file_path, file_name FROM photos WHERE id = ?', (pid,))
    row = cursor.fetchone()
    if not row:
        return None, None
    path, file_name = row

    removed_ok = True
    last_error = None
    if os.path.exists(path):
        removed_ok = False
        for attempt in range(3):
            try:
                os.remove(path)
                removed_ok = True
                break
            except Exception as e:
                last_error = str(e)
                time.sleep(0.4)

    if removed_ok:
        cursor.execute('DELETE FROM photos WHERE id = ?', (pid,))
        return True, None
    else:
        return False, {"id": pid, "file_name": file_name, "path": path, "error": last_error or "Erreur inconnue"}

@app.route('/api/delete', methods=['POST'])
def api_delete():
    if scans_active > 0: return jsonify({"status": "error", "message": "Attendez la fin des analyses."})

    ids_to_delete = request.json.get('ids', [])
    if not ids_to_delete: return jsonify({"status": "success", "deleted": 0, "errors": []})

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    deleted_count = 0
    errors = []

    for pid in ids_to_delete:
        ok, info = _safe_delete_photo(cursor, pid)
        if ok is None:
            continue
        elif ok:
            deleted_count += 1
        else:
            errors.append(info)

    conn.commit()
    conn.close()
    return jsonify({"status": "success", "deleted": deleted_count, "errors": errors})

@app.route('/api/delete_all_duplicates', methods=['POST'])
def api_delete_all_duplicates():
    # Supprime EN UNE FOIS tous les doublons de toute la base (pas seulement la page
    # affichee) : pour chaque groupe de doublons, on garde la meilleure copie (meme
    # algorithme que l'affichage : note qualite, puis presence sur le disque cible,
    # puis local vs distant) et on efface tout le reste, avec le meme mecanisme fiable
    # de suppression (reessais + verification reelle) que le bouton de suppression manuel.
    if scans_active > 0: return jsonify({"status": "error", "message": "Attendez la fin des analyses."})

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_name, file_size FROM photos
        GROUP BY file_name, file_size
        HAVING COUNT(*) > 1
    ''')
    duplicate_keys = cursor.fetchall()

    deleted_count = 0
    groups_count = 0
    errors = []

    for name, size in duplicate_keys:
        cursor.execute('SELECT id, source_name, file_path, resolution, rating, is_phone, gdrive_account_id FROM photos WHERE file_name = ? AND file_size = ?', (name, size))
        items = cursor.fetchall()
        if len(items) < 2:
            continue
        items.sort(key=_duplicate_master_sort_key, reverse=True)
        master_id = items[0][0]
        groups_count += 1

        for item in items[1:]:
            pid = item[0]
            ok, info = _safe_delete_photo(cursor, pid)
            if ok:
                deleted_count += 1
            elif ok is False:
                errors.append(info)

    conn.commit()
    conn.close()
    return jsonify({"status": "success", "deleted": deleted_count, "groups": groups_count, "errors": errors})

@app.route('/api/centralize', methods=['POST'])
def api_centralize():
    dest_dir = request.json.get('dest')
    if not dest_dir: return jsonify({"status": "error", "message": "Destination invalide."})
    
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id, file_path, file_name, gdrive_account_id, is_phone, file_size FROM photos')
    photos = cursor.fetchall()
    
    moved = 0
    copied_phone = 0
    errors = 0
    
    for pid, path, name, gdrive_acc, is_phone, expected_size in photos:
        target_final = dest_path / name
        target_temp = dest_path / (name + ".tmp")
        
        # Ignorer si la photo est déjà au bon endroit exact
        if os.path.abspath(path) == os.path.abspath(target_final):
            continue
            
        # Résolution des conflits de noms pour ne rien écraser
        counter = 1
        while target_final.exists():
            name_parts = os.path.splitext(name)
            target_final = dest_path / f"{name_parts[0]}_{counter}{name_parts[1]}"
            target_temp = dest_path / f"{target_final.name}.tmp"
            counter += 1

        success = False
        try:
            # 1. COPIE DE SÉCURITÉ VERS UN FICHIER TEMPORAIRE (.tmp)
            if os.path.exists(path):
                shutil.copy2(path, target_temp)
                # VERIFICATION INDUSTRIELLE : La taille doit être EXACTEMENT identique
                if target_temp.stat().st_size == os.path.getsize(path):
                    success = True

            # 2. VALIDATION ET ACTION FINALE
            if success:
                target_temp.replace(target_final) # Renommage atomique, valide le fichier
                
                if not is_phone:
                    # DÉPLACEMENT NORMAL : la source est supprimée en toute sécurité (copie déjà vérifiée).
                    os.remove(path)
                    moved += 1
                    cursor.execute('UPDATE photos SET file_path = ?, source_name = "Centralisé" WHERE id = ?', (str(target_final), pid))
                else:
                    # EXCEPTION TÉLÉPHONE : On garde l'original sur le téléphone (Copie simple)
                    copied_phone += 1
                    cursor.execute('UPDATE photos SET file_path = ?, source_name = "Centralisé (Téléphone Préservé)" WHERE id = ?', (str(target_final), pid))
            else:
                # Échec (câble retiré, coupure réseau) -> On supprime le fichier .tmp corrompu, et l'original est sauf !
                if target_temp.exists(): target_temp.unlink()
                errors += 1
                
        except Exception:
            # En cas d'erreur fatale durant le traitement d'une image
            if target_temp.exists(): 
                try: target_temp.unlink() 
                except: pass
            errors += 1
            
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "moved": moved, "copied_phone": copied_phone, "errors": errors})

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr" class="h-full bg-[#fdfaf6]">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mon Assistant Photo</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
body { font-family: 'Segoe UI', system-ui, sans-serif; }
.bento-card { background: white; border-radius: 24px; padding: 32px; box-shadow: 0 10px 40px -10px rgba(0,0,0,0.05); border: 1px solid rgba(0,0,0,0.02); }
.btn-modern { transition: all 0.2s; }
.btn-modern:active { transform: scale(0.97); }

.delete-checkbox:checked + div { border-color: #ef4444; background-color: #fef2f2; }
.delete-checkbox:checked + div .status-text { color: #ef4444; }
.delete-checkbox:checked + div .status-text::before { content: "🗑️ À Supprimer"; }

.delete-checkbox:not(:checked) + div { border-color: #10b981; background-color: #f0fdf4; }
.delete-checkbox:not(:checked) + div .status-text { color: #10b981; }
.delete-checkbox:not(:checked) + div .status-text::before { content: "✅ Gardé"; }
</style>
</head>
<body class="h-full text-slate-700 flex flex-col relative pb-24">

<header class="bg-white/90 backdrop-blur-xl border-b border-orange-50/50 px-8 py-4 flex justify-between items-center sticky top-0 z-40">
<div class="flex items-center space-x-4">
<div class="w-4 h-4 rounded-full bg-orange-300"></div>
<div>
<h1 class="text-xl font-bold text-slate-800 tracking-tight">Mon Assistant Photo</h1>
<p class="text-xs text-slate-500 font-medium">Tri intelligent & Centralisation</p>
</div>
</div>
<div id="stats-badge" class="bg-indigo-50 text-indigo-700 px-5 py-2 rounded-full font-bold text-sm border border-indigo-100 flex gap-4">
<span id="stat-total">📸 0 trouvées</span>
<span id="stat-dupes">✨ 0 doublons</span>
</div>
</header>

<main class="flex-1 max-w-5xl mx-auto w-full px-6 pt-10 space-y-8">

<div class="bento-card">
<h2 class="text-2xl font-bold text-slate-800 mb-2">Étape 1 : Dire au logiciel où chercher 🔎</h2>
<p class="text-slate-500 mb-2 font-medium">Cliquez sur vos disques. L'assistant va rechercher et filtrer les vraies photos.</p>
<p class="text-xs text-emerald-600 font-bold mb-6 bg-emerald-50 inline-block px-3 py-1 rounded-lg">💡 Vous pouvez cocher un disque comme "Cible". L'assistant essaiera de regrouper les meilleures qualités dessus.</p>

<div id="drives-container" class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6"></div>

<div class="flex flex-col sm:flex-row gap-4 mt-6 pt-6 border-t border-slate-100">
<button onclick="openPhoneModal()" class="btn-modern flex-1 bg-indigo-50 text-indigo-600 font-bold text-lg rounded-2xl py-4 hover:bg-indigo-100 border border-indigo-100">
📱 Connecter mon Téléphone
</button>
<button onclick="openTakeoutModal()" class="btn-modern flex-1 bg-blue-50 text-blue-600 font-bold text-lg rounded-2xl py-4 hover:bg-blue-100 border border-blue-100">
☁️ Ajouter un export Google Photos
</button>
<button onclick="scanGoogleDrive()" class="btn-modern flex-1 bg-emerald-50 text-emerald-600 font-bold text-lg rounded-2xl py-4 hover:bg-emerald-100 border border-emerald-100">
💾 Ajouter un compte Google Drive
</button>
</div>
</div>

<div class="bento-card bg-[#f8fafc] border-[#e2e8f0]">
<div class="flex justify-between items-center mb-6">
<div>
<h2 class="text-2xl font-bold text-indigo-900 mb-2">Étape 2 : Le Grand Tri 🪄</h2>
<p class="text-indigo-700 font-medium text-sm">Les copies inutiles s'affichent ci-dessous. Le logiciel garde par défaut la copie Locale ou celle du Lecteur Cible.</p>
</div>
<div class="flex flex-col sm:flex-row gap-2">
<button onclick="loadDuplicatesPage(true)" class="bg-white border border-indigo-200 text-indigo-600 px-4 py-2 rounded-xl font-bold text-sm shadow-sm hover:bg-indigo-50 transition">🔄 Rafraîchir</button>
<button id="btn-delete-all-ai" onclick="executeDeleteAllDuplicates()" class="bg-amber-500 hover:bg-amber-600 text-white px-4 py-2 rounded-xl font-bold text-sm shadow-sm transition">🤖 Supprimer TOUS les doublons (confiance IA)</button>
</div>
</div>

<div id="duplicates-container" class="space-y-6">
<div class="text-center py-10 text-slate-400 font-medium">Lancez une analyse au-dessus pour voir apparaître les photos ici...</div>
</div>

<div class="mt-8 text-center hidden" id="btn-load-more-container">
<button onclick="loadNextPage()" class="bg-white border-2 border-indigo-100 text-indigo-600 px-8 py-3 rounded-xl font-bold hover:bg-indigo-50 shadow-sm transition">
⬇️ Afficher la suite
</button>
</div>
</div>

<div class="bento-card bg-[#fdf4ff] border-[#fae8ff]">
<h2 class="text-2xl font-bold text-fuchsia-900 mb-2">Étape 3 : Tout rassembler (Le Grand Rangement) 📦</h2>
<p class="text-fuchsia-700 font-medium text-sm mb-4">Une fois le tri terminé, cette étape va <b>déplacer</b> toutes vos photos vers le dossier final de votre choix.</p>

<div class="bg-white/60 p-4 rounded-xl border border-fuchsia-100 mb-5">
<ul class="list-disc list-inside text-xs text-fuchsia-700 font-bold space-y-2">
<li>✅ <span class="text-slate-700 font-medium"><b>Sécurité industrielle :</b> Le logiciel vérifie que la photo est copiée à 100% avant d'effacer l'ancien original (Résiste aux débranchements et coupures réseau).</span></li>
<li>🧹 <span class="text-slate-700 font-medium"><b>Nettoyage automatique :</b> Les photos sont supprimées de vos anciens disques et du Cloud pour faire de la place.</span></li>
<li>📱 <span class="text-emerald-700 font-bold"><b>Exception Téléphone :</b> Les photos du téléphone sont copiées mais JAMAIS effacées (par précaution). Vous gérerez la place sur votre téléphone plus tard.</span></li>
</ul>
</div>

<div class="flex flex-col sm:flex-row gap-4">
<input type="text" id="centralize-path" placeholder="Ex: D:\\Mes_Photos_Triees" class="flex-1 px-4 py-3 rounded-xl border-2 border-fuchsia-200 focus:outline-none focus:border-fuchsia-400 font-medium text-slate-700">
<button onclick="executeCentralization()" class="bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-6 py-3 rounded-xl font-bold transition shadow-md">
Rapatrier & Nettoyer
</button>
</div>
</div>
</main>

<div id="delete-bar" class="fixed bottom-6 left-1/2 -translate-x-1/2 bg-slate-900 text-white p-4 rounded-2xl shadow-2xl flex items-center space-x-6 z-50">
<div class="font-bold text-lg"><span id="delete-count">0</span> photos seront effacées</div>
<button id="btn-execute-delete" onclick="executeDeletion()" class="bg-red-500 hover:bg-red-600 px-6 py-3 rounded-xl font-bold transition shadow-lg disabled:opacity-50 disabled:cursor-not-allowed">
🗑️ Supprimer les photos revues
</button>
</div>

<!-- Modals (Phone & Alerts) -->
<div id="phone-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm hidden flex items-center justify-center z-50 p-4">
<div class="bg-white rounded-[32px] p-8 max-w-md w-full relative">
<button onclick="closePhoneModal()" class="absolute top-6 right-6 text-slate-400 hover:text-slate-600 text-xl font-bold">❌</button>
<h2 class="text-2xl font-bold text-slate-800 mb-4">📱 Mon Téléphone</h2>
<div class="space-y-4 text-slate-600 text-sm font-medium">
<p>Windows bloque parfois la lecture directe du téléphone. Nous allons utiliser l'aspirateur magique de Windows !</p>
<div class="bg-indigo-50 p-4 rounded-xl border border-indigo-100 space-y-2">
<p class="font-bold text-indigo-800">1. Branchez votre téléphone en USB.</p>
<p class="font-bold text-indigo-800">2. Déverrouillez l'écran du téléphone.</p>
<p class="font-bold text-indigo-800">3. Cliquez sur le bouton ci-dessous.</p>
</div>
</div>
<button onclick="launchWindowsImport()" class="mt-6 w-full py-4 bg-indigo-600 text-white text-lg font-bold rounded-xl transition hover:bg-indigo-700">Lancer l'aspiration des photos 🪄</button>
</div>
</div>

<div id="takeout-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm hidden flex items-center justify-center z-50 p-4">
<div class="bg-white rounded-[32px] p-8 max-w-lg w-full relative max-h-[85vh] overflow-y-auto">
<button onclick="closeTakeoutModal()" class="absolute top-6 right-6 text-slate-400 hover:text-slate-600 text-xl font-bold">❌</button>
<h2 class="text-2xl font-bold text-slate-800 mb-4">☁️ Google Photos (via Takeout)</h2>
<div class="space-y-3 text-slate-600 text-sm font-medium">
<p>Depuis avril 2025, Google interdit aux logiciels de scanner automatiquement votre bibliothèque (changement définitif de leur part). Il faut exporter une fois via Google Takeout, l'outil officiel de Google :</p>
<div class="bg-blue-50 p-4 rounded-xl border border-blue-100 space-y-2">
<p class="font-bold text-blue-800">1. Allez sur takeout.google.com et connectez-vous</p>
<p class="font-bold text-blue-800">2. Cliquez sur "Tout désélectionner", puis cochez uniquement "Google Photos"</p>
<p class="font-bold text-blue-800">3. Format d'export : choisissez .zip et une taille de "50 Go" par fichier (le maximum, pour limiter le nombre de fichiers à télécharger)</p>
<p class="font-bold text-blue-800">4. Cliquez sur "Créer l'export"</p>
<p class="font-bold text-blue-800">5. Attendez l'email de Google (de quelques minutes à plusieurs heures selon la taille de votre bibliothèque)</p>
<p class="font-bold text-blue-800">6. Téléchargez chaque ZIP reçu, puis décompressez-les tous dans un même dossier parent</p>
<p class="font-bold text-blue-800">7. Collez ci-dessous le chemin de ce dossier</p>
</div>
<div class="bg-amber-50 p-3 rounded-xl border border-amber-100 text-xs text-amber-800">
⚠️ Vous n'avez que 5 tentatives de téléchargement par ZIP, et le lien expire après quelques jours : téléchargez-les rapidement une fois reçus. Si votre bibliothèque génère plusieurs ZIP, décompressez-les tous au même endroit avant de lancer le scan (un seul scan couvrira alors tout).
</div>
</div>
<button onclick="startTakeoutGuide()" class="mt-2 w-full py-3 bg-indigo-600 text-white text-sm font-bold rounded-xl transition hover:bg-indigo-700">🖱️ Ouvrir le guide interactif (surligne les boutons à cliquer)</button>
<p id="takeout-guide-status" class="text-xs text-indigo-600 font-bold mt-2 min-h-[16px]"></p>
<button id="takeout-guide-advance-btn" onclick="advanceTakeoutGuide()" class="hidden mt-2 w-full py-2 bg-indigo-100 text-indigo-700 text-xs font-bold rounded-lg transition hover:bg-indigo-200">✅ Étape suivante (si le guide ne progresse pas tout seul)</button>
<hr class="my-4 border-slate-100">
<input id="takeout-path-input" type="text" placeholder="Ex: C:\\Users\\vous\\Downloads\\Takeout\\Google Photos" class="mt-1 w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-sm font-mono focus:border-blue-400 outline-none">
<button onclick="scanTakeoutFolder()" class="mt-4 w-full py-4 bg-blue-600 text-white text-lg font-bold rounded-xl transition hover:bg-blue-700">Scanner ce dossier 🪄</button>
</div>
</div>

<script>
let currentPage = 1;
let checkedCount = 0;
let isScanningActive = false;

async function loadDrives() {
try {
const res = await fetch('/api/drives');
const drives = await res.json();
const container = document.getElementById('drives-container');
container.innerHTML = '';

drives.forEach(drive => {
const btn = document.createElement('div');
btn.className = "btn-modern relative bg-white p-6 rounded-[24px] border-2 border-slate-100 hover:border-slate-300 transition flex flex-col items-start cursor-pointer w-full";
btn.innerHTML = `
<div class="w-full flex justify-between items-start mb-4" onclick="scanPath('${drive.name.replace(/'/g, "\\'")}', '${drive.path.replace(/\\\\/g, '\\\\\\\\')}', false, this.parentElement)">
<div class="text-3xl">💾</div>
<span class="scan-status text-xs font-bold text-slate-500 bg-slate-50 px-3 py-1.5 rounded-full border border-slate-100">Cliquez pour scanner</span>
</div>
<h4 class="font-bold text-slate-800 text-lg leading-tight mb-2 pointer-events-none">${drive.name}</h4>
<label class="flex items-center space-x-2 text-xs font-bold text-indigo-600 bg-indigo-50 px-3 py-2 rounded-lg cursor-pointer w-full mt-auto" onclick="event.stopPropagation()">
<input type="radio" name="target_drive" value="${drive.path.replace(/\\\\/g, '\\\\\\\\')}" onchange="setTargetDrive(this.value)">
<span>🎯 Définir comme Lecteur Cible</span>
</label>
`;
container.appendChild(btn);
});
} catch (err) {}
}

async function setTargetDrive(path) {
await fetch('/api/set_target', {
method: 'POST',
headers: { 'Content-Type': 'application/json' },
body: JSON.stringify({ path: path })
});
loadDuplicatesPage(true); // Refresh pour appliquer les règles sur la cible
}

function openPhoneModal() { document.getElementById('phone-modal').classList.remove('hidden'); }
function closePhoneModal() { document.getElementById('phone-modal').classList.add('hidden'); }

async function launchWindowsImport() {
closePhoneModal();
try {
await fetch('/api/import_phone');
alert("Outil Windows ouvert ! Suivez ses instructions, puis scannez le dossier 'Images' de votre PC.");
} catch(e) {}
}

async function scanPath(name, path, isPhone, containerElement) {
const statusSpan = containerElement.querySelector('.scan-status');
statusSpan.innerHTML = '⏳ Démarrage...';
statusSpan.className = "scan-status text-xs font-bold text-orange-600 bg-orange-100 px-3 py-1.5 rounded-full";

try {
await fetch('/api/scan', {
method: 'POST',
headers: { 'Content-Type': 'application/json' },
body: JSON.stringify({ name: name, path: path, is_phone: isPhone })
});
startLiveStatsPolling();
pollProgress(path, statusSpan);
} catch (e) {
statusSpan.innerHTML = '❌ Erreur';
}
}

async function startTakeoutGuide() {
const statusEl = document.getElementById('takeout-guide-status');
const advanceBtn = document.getElementById('takeout-guide-advance-btn');
statusEl.innerText = "Lancement du navigateur...";
advanceBtn.classList.remove('hidden');
try {
await fetch('/api/takeout_guide/start', { method: 'POST' });
} catch (e) {
statusEl.innerText = "Impossible de démarrer le guide.";
advanceBtn.classList.add('hidden');
return;
}
const poll = setInterval(async () => {
const res = await fetch('/api/takeout_guide/status');
const data = await res.json();
statusEl.innerText = data.step;
statusEl.className = data.error ? "text-xs text-red-600 font-bold mt-2 min-h-[16px]" : "text-xs text-indigo-600 font-bold mt-2 min-h-[16px]";
if (data.done) {
clearInterval(poll);
advanceBtn.classList.add('hidden');
}
}, 1500);
}

async function advanceTakeoutGuide() {
await fetch('/api/takeout_guide/advance', { method: 'POST' });
}

async function scanGoogleDrive() {
const container = document.getElementById('drives-container');
const btn = document.createElement('div');
btn.className = "btn-modern bg-emerald-50 p-6 rounded-[24px] border-2 border-emerald-100 w-full";
btn.innerHTML = `
<div class="flex justify-between items-center mb-4">
<div class="text-3xl">💾</div>
<span class="scan-status text-xs font-bold text-emerald-600 bg-emerald-100 px-3 py-1.5 rounded-full">Autorisation...</span>
</div>
<h4 class="font-bold text-emerald-900 text-lg leading-tight account-name">Google Drive</h4>
`;
container.appendChild(btn);
const statusSpan = btn.querySelector('.scan-status');

try {
const res = await fetch('/api/scan_gdrive', { method: 'POST' });
let data;
try { data = await res.json(); }
catch (parseErr) {
statusSpan.innerHTML = "❌ Erreur serveur (code " + res.status + ")";
statusSpan.className = "scan-status text-xs font-bold text-red-600 bg-red-100 px-3 py-1.5 rounded-full";
return;
}
if (!res.ok || data.status === 'error') {
alert(data.message || "Erreur inconnue lors de la connexion à Google Drive.");
btn.remove();
return;
}
btn.querySelector('.account-name').innerText = `Google Drive (Compte ${data.account_id})`;
startLiveStatsPolling();
pollProgress(`Google Drive (Compte ${data.account_id})`, statusSpan);
} catch (e) {
statusSpan.innerHTML = "❌ Erreur";
}
}

function openTakeoutModal() { document.getElementById('takeout-modal').classList.remove('hidden'); }
function closeTakeoutModal() { document.getElementById('takeout-modal').classList.add('hidden'); }

async function scanTakeoutFolder() {
const path = document.getElementById('takeout-path-input').value.trim();
if (!path) return alert("Veuillez indiquer le chemin du dossier Google Takeout décompressé.");
closeTakeoutModal();

const container = document.getElementById('drives-container');
const btn = document.createElement('div');
btn.className = "btn-modern bg-blue-50 p-6 rounded-[24px] border-2 border-blue-100 w-full";
btn.innerHTML = `
<div class="flex justify-between items-center mb-4">
<div class="text-3xl">☁️</div>
<span class="scan-status text-xs font-bold text-blue-600 bg-blue-100 px-3 py-1.5 rounded-full">Démarrage...</span>
</div>
<h4 class="font-bold text-blue-900 text-lg leading-tight">Google Photos (Takeout)</h4>
<p class="text-xs text-blue-700 font-mono break-all mt-1">${path}</p>
`;
container.appendChild(btn);
const statusSpan = btn.querySelector('.scan-status');

try {
const res = await fetch('/api/scan', {
method: 'POST',
headers: { 'Content-Type': 'application/json' },
body: JSON.stringify({ name: 'Google Photos (Takeout)', path: path, is_phone: false })
});
const data = await res.json();
if (data.status === 'error') {
statusSpan.innerHTML = '❌ Dossier introuvable';
statusSpan.className = "scan-status text-xs font-bold text-red-600 bg-red-100 px-3 py-1.5 rounded-full";
return;
}
startLiveStatsPolling();
pollProgress(path, statusSpan);
} catch (e) {
statusSpan.innerHTML = '❌ Erreur';
}
}

function pollProgress(path, statusSpan) {
const poll = setInterval(async () => {
const res = await fetch(`/api/progress?path=${encodeURIComponent(path)}`);
const data = await res.json();
if (data.done) {
clearInterval(poll);
if (data.error) {
statusSpan.innerHTML = `❌ ${data.status}`;
statusSpan.className = "scan-status text-xs font-bold text-red-600 bg-red-100 px-3 py-1.5 rounded-full";
} else if (data.count === 0) {
statusSpan.innerHTML = `⚠️ 0 photo trouvée`;
statusSpan.className = "scan-status text-xs font-bold text-amber-600 bg-amber-100 px-3 py-1.5 rounded-full";
} else {
statusSpan.innerHTML = `✅ ${data.count} photos téléchargées`;
statusSpan.className = "scan-status text-xs font-bold text-emerald-600 bg-emerald-100 px-3 py-1.5 rounded-full";
}
} else {
statusSpan.innerHTML = `⏳ ${data.status} (${data.count} téléchargées)`;
}
}, 1000);
}

let statsInterval = null;
function startLiveStatsPolling() {
if (statsInterval) return;
statsInterval = setInterval(async () => {
try {
const res = await fetch('/api/live_stats');
const data = await res.json();

document.getElementById('stat-total').innerText = `📸 ${data.total} photos`;
document.getElementById('stat-dupes').innerText = `✨ ${data.duplicates_groups} doublons`;

isScanningActive = data.scans_active;
const btnDelete = document.getElementById('btn-execute-delete');

if (isScanningActive) {
btnDelete.disabled = true;
btnDelete.innerHTML = "⏳ Scan en cours...";
btnDelete.classList.replace('bg-red-500', 'bg-slate-600');
} else {
btnDelete.disabled = false;
btnDelete.innerHTML = "🗑️ Supprimer les photos revues";
btnDelete.classList.replace('bg-slate-600', 'bg-red-500');
clearInterval(statsInterval);
statsInterval = null;
if(currentPage === 1) loadDuplicatesPage(true);
}
} catch(e) {}
}, 2000);
}

async function replaceTarget(masterId, worseId, btnElem) {
btnElem.innerText = "⏳ Remplacement en cours...";
btnElem.disabled = true;
try {
await fetch('/api/replace_target', {
method: 'POST',
headers: { 'Content-Type': 'application/json' },
body: JSON.stringify({ master_id: masterId, worse_id: worseId })
});
loadDuplicatesPage(true);
} catch(e) {
alert("Erreur lors du remplacement.");
}
}

async function loadDuplicatesPage(reset = false) {
if(reset) {
currentPage = 1;
document.getElementById('duplicates-container').innerHTML = '';
checkedCount = 0;
document.getElementById('delete-count').innerText = checkedCount;
}

try {
const res = await fetch(`/api/duplicates_paginated?page=${currentPage}`);
const data = await res.json();
const container = document.getElementById('duplicates-container');

if(data.groups.length === 0 && currentPage === 1) {
container.innerHTML = '<div class="text-center py-10 text-slate-500 font-bold text-lg">Aucun doublon trouvé pour l\'instant.</div>';
document.getElementById('btn-load-more-container').classList.add('hidden');
return;
}

data.groups.forEach((group) => {
let photosHtml = '';
group.photos.forEach(photo => {
const shouldBeChecked = !photo.is_master;
if(shouldBeChecked) checkedCount++;

photosHtml += `
<label class="relative block cursor-pointer group">
<input type="checkbox" value="${photo.id}" class="delete-checkbox sr-only" onchange="updateCounter(this)" ${shouldBeChecked ? 'checked' : ''}>
<div class="border-4 rounded-xl overflow-hidden transition-all duration-200 h-full flex flex-col bg-white">
<div class="h-40 w-full bg-slate-100 relative">
<img src="/api/thumb/${photo.id}" class="w-full h-full object-cover" loading="lazy">
</div>
<div class="p-3 bg-white flex-1 border-t border-slate-100">
<p class="font-bold text-sm text-slate-800 break-all mb-1">${photo.source}</p>
<p class="text-xs text-slate-400 font-mono break-all truncate" title="${photo.path}">${photo.path}</p>
<div class="mt-2 font-bold text-xs status-text text-center py-1 rounded-lg transition-colors"></div>
</div>
</div>
</label>
`;
});

let replaceBtn = '';
if (group.can_replace) {
replaceBtn = `
<div class="bg-amber-50 border border-amber-200 rounded-xl p-4 mt-4 flex justify-between items-center">
<div>
<p class="font-bold text-amber-800 text-sm">💡 La photo sur votre Lecteur Cible est de moins bonne qualité.</p>
<p class="text-xs text-amber-700">Chemin cible : ${group.worse_path}</p>
</div>
<button onclick="replaceTarget(${group.master_id}, ${group.worse_id}, this)" class="bg-amber-500 hover:bg-amber-600 text-white px-4 py-2 rounded-lg font-bold text-sm shadow">
Mettre à jour la Cible
</button>
</div>
`;
}

container.insertAdjacentHTML('beforeend', `
<div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
<div class="mb-4">
<span class="bg-indigo-100 text-indigo-800 text-xs font-bold px-3 py-1 rounded-full">Doublon repéré</span>
<span class="ml-2 font-bold text-slate-700">${group.name}</span>
</div>
<div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
${photosHtml}
</div>
${replaceBtn}
</div>
`);
});

document.getElementById('delete-count').innerText = checkedCount;

if(data.groups.length === 15) {
document.getElementById('btn-load-more-container').classList.remove('hidden');
} else {
document.getElementById('btn-load-more-container').classList.add('hidden');
}
} catch(e) {}
}

function loadNextPage() {
currentPage++;
loadDuplicatesPage(false);
}

function updateCounter(checkbox) {
checkedCount += checkbox.checked ? 1 : -1;
document.getElementById('delete-count').innerText = checkedCount;
}

async function executeDeletion() {
if (isScanningActive) return;
if (checkedCount === 0) return alert("Veuillez cocher des photos.");
if(!confirm(`Confirmez-vous la suppression de ${checkedCount} copies en double ? (Cela ne supprime que les copies locales/cache ; vos photos originales dans Google Photos restent intactes en ligne)`)) return;

const checkboxes = document.querySelectorAll('.delete-checkbox:checked');
const idsToDelete = Array.from(checkboxes).map(cb => parseInt(cb.value));

document.getElementById('btn-execute-delete').innerHTML = '⏳ Suppression en cours...';
document.getElementById('btn-execute-delete').disabled = true;

try {
const res = await fetch('/api/delete', {
method: 'POST',
headers: { 'Content-Type': 'application/json' },
body: JSON.stringify({ ids: idsToDelete })
});
const data = await res.json();

if (data.status === 'error') {
alert(`❌ Erreur : ${data.message}`);
} else {
const deleted = data.deleted || 0;
const errors = data.errors || [];
if (errors.length === 0) {
alert(`✅ Succès ! ${deleted} copie(s) en double effacée(s) pour de vrai (fichier + base de données).`);
} else {
const details = errors.map(e => `- ${e.file_name} : ${e.error}`).join('\n');
alert(`⚠️ ${deleted} copie(s) effacée(s), mais ${errors.length} ont ÉCHOUÉ (fichier probablement ouvert dans un autre programme, ou verrouillé) :\n\n${details}\n\nFermez les programmes qui utilisent ces fichiers (visionneuse photo, etc.) puis réessayez.`);
}
}
loadDuplicatesPage(true);
} catch(e) {
alert("❌ Erreur réseau pendant la suppression, réessayez.");
} finally {
document.getElementById('btn-execute-delete').innerHTML = '🗑️ Supprimer les photos revues';
document.getElementById('btn-execute-delete').disabled = false;
}
}

async function executeDeleteAllDuplicates() {
if (isScanningActive) return;
if (!confirm("⚠️ ATTENTION : Cette action va faire confiance à l'IA pour TOUS les doublons de toute votre photothèque (pas seulement ceux affichés à l'écran).\n\nPour chaque groupe de doublons, la MEILLEURE copie sera gardée automatiquement (qualité, résolution, emplacement) et TOUTES les autres copies seront effacées définitivement.\n\nVoulez-vous vraiment continuer sans les revoir une par une ?")) return;

const btn = document.getElementById('btn-delete-all-ai');
const original = btn.innerHTML;
btn.innerHTML = '⏳ Suppression en cours (peut prendre du temps)...';
btn.disabled = true;

try {
const res = await fetch('/api/delete_all_duplicates', { method: 'POST' });
const data = await res.json();

if (data.status === 'error') {
alert(`❌ Erreur : ${data.message}`);
} else {
const deleted = data.deleted || 0;
const groups = data.groups || 0;
const errors = data.errors || [];
if (errors.length === 0) {
alert(`✅ Succès ! ${deleted} copie(s) en double effacée(s) sur ${groups} groupe(s) de doublons traités.`);
} else {
const details = errors.slice(0, 15).map(e => `- ${e.file_name} : ${e.error}`).join('\n');
const more = errors.length > 15 ? `\n... et ${errors.length - 15} de plus.` : '';
alert(`⚠️ ${deleted} copie(s) effacée(s) sur ${groups} groupe(s), mais ${errors.length} ont ÉCHOUÉ (fichier probablement ouvert ailleurs) :\n\n${details}${more}\n\nFermez les programmes concernés puis relancez cette action.`);
}
}
loadDuplicatesPage(true);
} catch(e) {
alert("❌ Erreur réseau pendant la suppression, réessayez.");
} finally {
btn.innerHTML = original;
btn.disabled = false;
}
}

async function executeCentralization() {
const dest = document.getElementById('centralize-path').value;
if (!dest) return alert("Veuillez indiquer un chemin de destination.");

if(!confirm(`ATTENTION :\n\nToutes les photos vont être DÉPLACÉES vers ${dest}.\nElles seront supprimées de leurs anciens dossiers.\n(SAUF pour le téléphone qui servira de sauvegarde de sécurité).\n\nCette opération est ultra-sécurisée. Voulez-vous continuer ?`)) return;

alert("Le rapatriement démarre. Ne fermez PAS la fenêtre et ne débranchez PAS vos disques ! L'opération peut être longue.");

const btn = document.querySelector('button[onclick="executeCentralization()"]');
btn.innerHTML = '⏳ Rapatriement ultra-sécurisé en cours...';
btn.disabled = true;
btn.classList.add('opacity-50', 'cursor-not-allowed');

try {
const res = await fetch('/api/centralize', {
method: 'POST',
headers: { 'Content-Type': 'application/json' },
body: JSON.stringify({ dest: dest })
});
const data = await res.json();

if (data.status === 'error') {
alert(`Erreur : ${data.message}`);
} else {
let msg = `✅ Opération terminée avec succès !\n\n`;
msg += `📦 ${data.moved} photos déplacées (anciens originaux effacés du cache/disque).\n`;
msg += `📱 ${data.copied_phone} photos copiées depuis le téléphone (originaux conservés).\n`;
if(data.errors > 0) msg += `⚠️ ${data.errors} fichiers ont rencontré une erreur (câble arraché ou coupure). Leurs originaux n'ont PAS été effacés par sécurité !\n`;
if(data.from_gphotos > 0) msg += `\n☁️ ${data.from_gphotos} photos venaient de Google Photos et sont maintenant en sécurité sur votre disque. Vous pouvez désormais les supprimer manuellement dans l'application Google Photos pour libérer de la place (l'API Google ne permet pas de le faire automatiquement).`;

alert(msg);
loadDuplicatesPage(true); // Rafraîchir l'affichage
}
} catch(e) {
alert("Erreur critique réseau lors de la centralisation. Aucune donnée n'a été perdue.");
} finally {
btn.innerHTML = 'Rapatrier & Nettoyer';
btn.disabled = false;
btn.classList.remove('opacity-50', 'cursor-not-allowed');
}
}

window.onload = () => {
loadDrives();
};
</script>
</body>
</html>
"""

if __name__ == '__main__':
    multiprocessing.freeze_support()
    init_db()
    threading.Thread(target=open_browser, daemon=True).start()
    
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR) 
    
    print("\n" + "🌸"*25)
    print(" L'Assistant Photo est en cours d'exécution...")
    print(" Ne fermez pas cette fenêtre noire avant d'avoir fini.")
    print("🌸"*25 + "\n")
    
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
