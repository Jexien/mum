#!/usr/bin/env python3
"""MUM - Gestionnaire & Nettoyeur Intelligent de Photos & Vidéos Multi-Sources.

Point d'entrée principal unique.
Lancement : python mum.py
"""

import sys
import threading
import time
import webbrowser
import multiprocessing
import logging
from pathlib import Path

# Configuration du PYTHONPATH vers le dossier src
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mum.database import init_db
from mum.app import app

def open_browser():
    """Ouvre l'interface web dans le navigateur par défaut après démarrage du serveur."""
    time.sleep(1.5)
    try:
        webbrowser.open('http://127.0.0.1:5000')
    except Exception:
        pass

if __name__ == '__main__':
    multiprocessing.freeze_support()
    init_db()

    # Thread d'ouverture automatique du navigateur
    threading.Thread(target=open_browser, daemon=True).start()

    # Réduction des logs HTTP verbeux de Werkzeug
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    print("\n" + "🌸" * 30)
    print(" 🌸 MUM - Assistant Photos & Vidéos est en cours d'exécution !")
    print(" 🌐 Interface disponible sur : http://127.0.0.1:5000")
    print(" 💡 Ne fermez pas cette fenêtre avant d'avoir terminé.")
    print("🌸" * 30 + "\n")

    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
