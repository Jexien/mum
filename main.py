#!/usr/bin/env python3
"""Point d'entrée principal standardisé pour l'application MUM.

Usage:
    python main.py
"""

import sys
from pathlib import Path

# Ajouter le répertoire racine au PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if __name__ == '__main__':
    # Exécution directe du module MUM
    import runpy
    runpy.run_path(str(BASE_DIR / "mum.py"), run_name="__main__")
