# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

datas = [('src/mum', 'src/mum'), ('src/mum', 'mum')]
binaries = []
hiddenimports = [
    'sqlite3', '_sqlite3',
    'hashlib', '_hashlib',
    'ssl', '_ssl',
    'ctypes', '_ctypes',
    'zlib', '_bz2', '_lzma',
    'multiprocessing', 'concurrent.futures',
    'webbrowser', 'shutil', 'dotenv', 'logging'
]

# Ajout des DLLs critiques de Python Windows
dll_dir = Path(sys.base_prefix) / "DLLs"
for dll_name in ('_sqlite3.pyd', '_ssl.pyd', '_hashlib.pyd', '_bz2.pyd', '_lzma.pyd', '_ctypes.pyd'):
    dll_path = dll_dir / dll_name
    if dll_path.exists():
        binaries.append((str(dll_path), "."))

# Collecte des dépendances tierces
for pkg in ('googleapiclient', 'google_auth_oauthlib', 'google.auth', 'PIL', 'imagehash', 'cv2', 'flask', 'dotenv'):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

a = Analysis(
    ['mum.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MUM',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
