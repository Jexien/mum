"""Serveur Flask principal et API REST pour MUM."""

import os
import io
import time
import threading
from pathlib import Path
from flask import Flask, jsonify, request, send_file, render_template_string

from .config import (
    BASE_DIR, DATA_DIR, DB_PATH, GOOGLE_CLIENT_CONFIG
)
from .database import init_db, get_db_connection
from .scanner import get_system_drives, scan_directory
from .gdrive import scan_gdrive_account
from .takeout import run_takeout_guide, guide_status, guide_manual_advance
from .takeout_scanner import detect_takeout_archives, scan_takeout_zip
from .deduplicator import get_exact_duplicate_groups, get_similar_media_groups
from .transfer import safe_centralize_and_clean, transfer_progress
from .media_processor import generate_thumbnail_bytes

app = Flask(__name__)

# État global
scan_progress = {}
scans_active = 0
TARGET_DRIVE = None
gdrive_accounts = 0

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr" class="h-full bg-slate-50">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MUM - Gestionnaire & Nettoyeur Photos / Vidéos</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
  body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
  .card-shadow { box-shadow: 0 10px 30px -5px rgba(0,0,0,0.06), 0 4px 6px -2px rgba(0,0,0,0.03); }
  .custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
  .custom-scrollbar::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
</style>
</head>
<body class="h-full text-slate-800 flex flex-col">

<!-- HEADER -->
<header class="bg-white border-b border-slate-200 sticky top-0 z-50">
  <div class="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
    <div class="flex items-center space-x-3">
      <div class="w-10 h-10 bg-indigo-600 rounded-xl flex items-center justify-center text-white text-xl font-bold shadow-md shadow-indigo-200">
        <i class="fa-solid fa-photo-film"></i>
      </div>
      <div>
        <h1 class="text-xl font-bold text-slate-900 tracking-tight">MUM <span class="text-xs font-semibold px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded-full border border-indigo-200">Photos & Vidéos</span></h1>
        <p class="text-xs text-slate-500">Centralisation, Déduplication Intelligente & Nettoyage Multi-Sources</p>
      </div>
    </div>

    <!-- STATS BANNER -->
    <div class="flex items-center space-x-6">
      <div class="text-right">
        <div class="text-xs text-slate-500 font-medium">Médias Indexés</div>
        <div id="statTotal" class="text-lg font-bold text-slate-800 leading-tight">0</div>
      </div>
      <div class="text-right">
        <div class="text-xs text-slate-500 font-medium">Doublons Détectés</div>
        <div id="statDuplicates" class="text-lg font-bold text-amber-600 leading-tight">0</div>
      </div>
      <div class="border-l border-slate-200 pl-6 text-right">
        <div class="text-xs text-slate-500 font-medium">Disque Cible</div>
        <div id="statTarget" class="text-sm font-semibold text-indigo-600 truncate max-w-[200px]">Non défini</div>
      </div>
    </div>
  </div>

  <!-- NAVIGATION TABS -->
  <div class="max-w-7xl mx-auto px-6 flex space-x-8 border-t border-slate-100">
    <button onclick="switchTab('sources')" id="tabBtn-sources" class="tab-btn py-3 text-sm font-semibold border-b-2 border-indigo-600 text-indigo-600 flex items-center space-x-2">
      <i class="fa-solid fa-hard-drive"></i>
      <span>1. Sources & Disques</span>
    </button>
    <button onclick="switchTab('exact')" id="tabBtn-exact" class="tab-btn py-3 text-sm font-semibold border-b-2 border-transparent text-slate-500 hover:text-slate-800 flex items-center space-x-2">
      <i class="fa-solid fa-clone"></i>
      <span>2. Doublons Exacts</span>
    </button>
    <button onclick="switchTab('similar')" id="tabBtn-similar" class="tab-btn py-3 text-sm font-semibold border-b-2 border-transparent text-slate-500 hover:text-slate-800 flex items-center space-x-2">
      <i class="fa-solid fa-images"></i>
      <span>3. Photos & Vidéos Similaires</span>
    </button>
    <button onclick="switchTab('centralize')" id="tabBtn-centralize" class="tab-btn py-3 text-sm font-semibold border-b-2 border-transparent text-slate-500 hover:text-slate-800 flex items-center space-x-2">
      <i class="fa-solid fa-shield-halved"></i>
      <span>4. Sauvegarder & Nettoyer</span>
    </button>
  </div>
</header>

<!-- MAIN CONTENT CONTAINER -->
<main class="flex-1 max-w-7xl mx-auto w-full p-6 overflow-y-auto custom-scrollbar">

  <!-- ==================== TAB 1 : SOURCES ==================== -->
  <section id="tab-sources" class="space-y-6">
    <!-- AUTO DETECTED TAKEOUT BANNER -->
    <div id="takeoutBanner" class="hidden bg-amber-500 text-white rounded-2xl p-5 shadow-lg flex flex-col md:flex-row items-center justify-between gap-4">
      <div class="flex items-center space-x-4">
        <div class="w-12 h-12 bg-white/20 rounded-xl flex items-center justify-center text-2xl">
          <i class="fa-solid fa-file-zipper"></i>
        </div>
        <div>
          <h3 class="font-bold text-base">Archives Google Takeout détectées dans Téléchargements !</h3>
          <p id="takeoutBannerText" class="text-xs text-amber-100">Des archives ZIP ont été trouvées. MUM peut les analyser directement sans décompression.</p>
        </div>
      </div>
      <div id="takeoutBannerActions" class="flex items-center space-x-3"></div>
    </div>

    <!-- TARGET DRIVE SELECTOR BANNER -->
    <div class="bg-gradient-to-r from-indigo-900 to-slate-900 rounded-2xl p-6 text-white shadow-xl flex flex-col md:flex-row items-center justify-between gap-4">
      <div class="space-y-1">
        <span class="text-xs font-semibold uppercase tracking-wider text-indigo-300">Étape clé</span>
        <h2 class="text-xl font-bold">Sélectionnez le disque dur de destination</h2>
        <p class="text-xs text-slate-300">Toutes les photos et vidéos y seront regroupées sans doublons. Les autres disques seront vidés pour libérer de l'espace (le téléphone est protégé à 100%).</p>
      </div>
      <div class="flex items-center space-x-3 w-full md:w-auto">
        <select id="targetDriveSelect" class="bg-slate-800/90 text-white text-sm font-medium border border-indigo-500/50 rounded-xl px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-400">
          <option value="">-- Choisir un disque cible --</option>
        </select>
        <button onclick="saveTargetDrive()" class="bg-indigo-500 hover:bg-indigo-600 text-white text-sm font-semibold px-5 py-2.5 rounded-xl transition shadow-lg shadow-indigo-500/30 whitespace-nowrap">
          Définir Cible
        </button>
      </div>
    </div>

    <!-- SOURCES GRID -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      
      <!-- GOOGLE DRIVE CARD -->
      <div class="bg-white rounded-2xl p-6 border border-slate-200 card-shadow flex flex-col justify-between">
        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <div class="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center text-2xl font-bold">
              <i class="fa-brands fa-google-drive"></i>
            </div>
            <span class="text-xs font-semibold px-2.5 py-1 bg-blue-100/60 text-blue-700 rounded-full">Cloud</span>
          </div>
          <div>
            <h3 class="font-bold text-slate-900 text-base">Google Drive</h3>
            <p class="text-xs text-slate-500 mt-1">Récupère directement toutes vos photos et vidéos stockées sur votre Drive.</p>
          </div>
        </div>
        <div class="mt-6 pt-4 border-t border-slate-100 space-y-3">
          <div id="gdriveProgressBox" class="hidden space-y-1.5">
            <div class="flex justify-between text-xs font-semibold text-blue-700">
              <span id="gdriveProgressText">Scan en cours...</span>
              <span id="gdriveProgressPct">0%</span>
            </div>
            <div class="w-full bg-blue-100 rounded-full h-2 overflow-hidden">
              <div id="gdriveProgressBar" class="bg-blue-600 h-full rounded-full transition-all duration-300" style="width: 0%"></div>
            </div>
          </div>
          <button onclick="scanGDrive()" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm py-2.5 rounded-xl transition flex items-center justify-center space-x-2">
            <i class="fa-solid fa-cloud-arrow-down"></i>
            <span>Scanner Google Drive</span>
          </button>
        </div>
      </div>

      <!-- GOOGLE PHOTOS / TAKEOUT CARD -->
      <div class="bg-white rounded-2xl p-6 border border-slate-200 card-shadow flex flex-col justify-between">
        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <div class="w-12 h-12 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center text-2xl font-bold">
              <i class="fa-brands fa-google"></i>
            </div>
            <span class="text-xs font-semibold px-2.5 py-1 bg-amber-100/60 text-amber-700 rounded-full">Google Photos</span>
          </div>
          <div>
            <h3 class="font-bold text-slate-900 text-base">Google Photos (Takeout)</h3>
            <p class="text-xs text-slate-500 mt-1">Assistant d'export ou lecture directe de vos fichiers .ZIP sans décompression.</p>
          </div>
        </div>
        <div class="mt-6 pt-4 border-t border-slate-100 space-y-3">
          <div id="takeoutProgressBox" class="hidden space-y-1.5">
            <div class="flex justify-between text-xs font-semibold text-amber-800">
              <span id="takeoutProgressText" class="truncate pr-2">Analyse du ZIP...</span>
              <span id="takeoutProgressPct" class="flex-shrink-0">0%</span>
            </div>
            <div class="w-full bg-amber-100 rounded-full h-2 overflow-hidden">
              <div id="takeoutProgressBar" class="bg-amber-600 h-full rounded-full transition-all duration-300" style="width: 0%"></div>
            </div>
          </div>
          <div id="takeoutStatus" class="text-xs text-slate-500 truncate">Prêt</div>
          <button onclick="promptScanTakeoutZip()" class="w-full bg-amber-600 hover:bg-amber-700 text-white font-medium text-xs py-2.5 rounded-xl transition flex items-center justify-center space-x-2">
            <i class="fa-solid fa-file-zipper"></i>
            <span>Scanner un fichier .ZIP Takeout</span>
          </button>
          <button onclick="startTakeoutGuide()" class="w-full bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium text-xs py-2 rounded-xl transition flex items-center justify-center space-x-2">
            <i class="fa-solid fa-wand-magic-sparkles text-amber-500"></i>
            <span>Lancer l'Assistant Export Google</span>
          </button>
        </div>
      </div>

      <!-- DYNAMIC DISKS & PHONES CONTAINER -->
      <div id="drivesContainer" class="contents"></div>
    </div>
  </section>

  <!-- ==================== TAB 2 : DOUBLONS EXACTS ==================== -->
  <section id="tab-exact" class="hidden space-y-6">
    <div class="bg-white rounded-2xl p-6 border border-slate-200 card-shadow flex flex-col sm:flex-row items-center justify-between gap-4">
      <div>
        <h2 class="text-lg font-bold text-slate-900">Doublons 100% Identiques</h2>
        <p class="text-xs text-slate-500">Même contenu (SHA-256) présent sur plusieurs disques ou sous des noms différents.</p>
      </div>
      <button onclick="deleteAllExactDuplicates()" class="bg-red-600 hover:bg-red-700 text-white text-sm font-semibold px-5 py-2.5 rounded-xl transition shadow-lg shadow-red-600/20 flex items-center space-x-2">
        <i class="fa-solid fa-trash-can"></i>
        <span>Supprimer tous les doublons exacts (1 clic)</span>
      </button>
    </div>

    <div id="exactDuplicatesList" class="space-y-4">
      <div class="text-center py-12 text-slate-400 text-sm">Lancez un scan de vos disques pour afficher les doublons exacts.</div>
    </div>
  </section>

  <!-- ==================== TAB 3 : SIMILAIRES ==================== -->
  <section id="tab-similar" class="hidden space-y-6">
    <div class="bg-white rounded-2xl p-6 border border-slate-200 card-shadow flex flex-col sm:flex-row items-center justify-between gap-4">
      <div>
        <h2 class="text-lg font-bold text-slate-900">Photos & Vidéos Similaires (Rafales, Recadrages, Qualités)</h2>
        <p class="text-xs text-slate-500">Comparez visuellement et choisissez quelle prise conserver.</p>
      </div>
      <button onclick="loadSimilarMedia()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-semibold px-4 py-2 rounded-xl transition flex items-center space-x-2">
        <i class="fa-solid fa-arrows-rotate"></i>
        <span>Rafraîchir les similaires</span>
      </button>
    </div>

    <div id="similarMediaList" class="space-y-6">
      <div class="text-center py-12 text-slate-400 text-sm">Aucun groupe de photos/vidéos similaires analysé pour le moment.</div>
    </div>
  </section>

  <!-- ==================== TAB 4 : SAUVEGARDER & NETTOYER ==================== -->
  <section id="tab-centralize" class="hidden space-y-6">
    <div class="bg-white rounded-2xl p-8 border border-slate-200 card-shadow space-y-6 max-w-3xl mx-auto">
      <div class="text-center space-y-2">
        <div class="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-2xl flex items-center justify-center text-3xl mx-auto shadow-inner">
          <i class="fa-solid fa-box-archive"></i>
        </div>
        <h2 class="text-2xl font-bold text-slate-900">Centralisation & Nettoyage Ultime</h2>
        <p class="text-sm text-slate-500 max-w-lg mx-auto">Rassemblez tous vos souvenirs sur le disque cible, éliminez les doublons lors de la copie et libérez l'espace sur les autres disques.</p>
      </div>

      <!-- SAFETY CARD -->
      <div class="bg-amber-50 border border-amber-200 rounded-xl p-4 text-xs text-amber-900 space-y-2">
        <div class="font-bold flex items-center space-x-2">
          <i class="fa-solid fa-shield-halved text-amber-600 text-sm"></i>
          <span>Garantie de Sécurité Maximale :</span>
        </div>
        <ul class="list-disc list-inside space-y-1 text-amber-800">
          <li><strong>Smartphone préservé :</strong> Vos photos sur téléphone sont copiées mais <strong>JAMAIS supprimées</strong> du téléphone.</li>
          <li><strong>Copie atomique vérifiée :</strong> Un fichier source n'est effacé que si sa copie sur le disque cible a été vérifiée octet par octet.</li>
          <li><strong>Zéro doublon résiduel :</strong> Si un fichier existe déjà sur la cible, la copie superflue est fusionnée.</li>
          <li><strong>Support direct ZIP :</strong> Les médias dans les archives Takeout .ZIP sont extraits directement sur la cible.</li>
        </ul>
      </div>

      <!-- PROGRESS BOX -->
      <div id="transferProgressBox" class="hidden space-y-3 pt-4 border-t border-slate-100">
        <div class="flex justify-between text-xs font-semibold text-slate-700">
          <span id="transferStatusText">Transfert en cours...</span>
          <span id="transferPercentText">0%</span>
        </div>
        <div class="w-full bg-slate-100 rounded-full h-3 overflow-hidden">
          <div id="transferProgressBar" class="bg-emerald-500 h-full rounded-full transition-all duration-300" style="width: 0%"></div>
        </div>
      </div>

      <!-- ACTION BUTTON -->
      <div class="pt-4 flex justify-center">
        <button id="btnStartTransfer" onclick="startCentralization()" class="bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-base px-8 py-3.5 rounded-2xl shadow-xl shadow-emerald-600/30 transition flex items-center space-x-3">
          <i class="fa-solid fa-circle-check text-lg"></i>
          <span>Sauvegarder Tout sur la Cible & Nettoyer les Sources</span>
        </button>
      </div>
    </div>
  </section>

</main>

<!-- JAVASCRIPT LOGIC -->
<script>
let currentTargetDrive = "";

function switchTab(tabId) {
  ['sources', 'exact', 'similar', 'centralize'].forEach(id => {
    const section = document.getElementById('tab-' + id);
    const btn = document.getElementById('tabBtn-' + id);
    if (id === tabId) {
      section.classList.remove('hidden');
      btn.className = "tab-btn py-3 text-sm font-semibold border-b-2 border-indigo-600 text-indigo-600 flex items-center space-x-2";
    } else {
      section.classList.add('hidden');
      btn.className = "tab-btn py-3 text-sm font-semibold border-b-2 border-transparent text-slate-500 hover:text-slate-800 flex items-center space-x-2";
    }
  });

  if (tabId === 'exact') loadExactDuplicates();
  if (tabId === 'similar') loadSimilarMedia();
}

async function loadDrives() {
  const res = await fetch('/api/drives');
  const drives = await res.json();
  const container = document.getElementById('drivesContainer');
  const select = document.getElementById('targetDriveSelect');
  
  select.innerHTML = '<option value="">-- Choisir un disque cible --</option>';
  container.innerHTML = '';

  drives.forEach(drive => {
    // Select option
    if (!drive.is_phone) {
      const opt = document.createElement('option');
      opt.value = drive.path;
      opt.innerText = `${drive.name} (${drive.free_gb} Go libres)`;
      if (drive.path === currentTargetDrive) opt.selected = true;
      select.appendChild(opt);
    }

    // Drive Card
    const card = document.createElement('div');
    card.className = "bg-white rounded-2xl p-6 border border-slate-200 card-shadow flex flex-col justify-between";
    const iconClass = drive.is_phone ? "fa-mobile-screen-button text-purple-600" : "fa-hard-drive text-slate-700";
    const badgeText = drive.is_phone ? "Telephone (Copie seule)" : (drive.path === currentTargetDrive ? "Disque Cible" : "Disque Local");
    const badgeColor = drive.is_phone ? "bg-purple-100 text-purple-700" : (drive.path === currentTargetDrive ? "bg-indigo-100 text-indigo-700 font-bold" : "bg-slate-100 text-slate-600");

    card.innerHTML = `
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <div class="w-12 h-12 rounded-xl bg-slate-50 flex items-center justify-center text-2xl">
            <i class="fa-solid ${iconClass}"></i>
          </div>
          <span class="text-xs px-2.5 py-1 rounded-full ${badgeColor}">${badgeText}</span>
        </div>
        <div>
          <h3 class="font-bold text-slate-900 text-base truncate">${drive.name}</h3>
          <p class="text-xs text-slate-400 font-mono mt-0.5">${drive.path}</p>
          ${!drive.is_phone ? `
          <div class="mt-3 space-y-1">
            <div class="flex justify-between text-xs text-slate-500">
              <span>${drive.used_gb} Go utilisés</span>
              <span>${drive.free_gb} Go libres</span>
            </div>
            <div class="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
              <div class="bg-indigo-500 h-full rounded-full" style="width: ${drive.percent}%"></div>
            </div>
          </div>` : ''}
        </div>
      </div>
      <div class="mt-6 pt-4 border-t border-slate-100 space-y-3">
        <div id="prog-box-${drive.id}" class="hidden space-y-1.5">
          <div class="flex justify-between text-xs font-semibold text-indigo-700">
            <span id="prog-txt-${drive.id}" class="truncate pr-2">Démarrage...</span>
            <span id="prog-pct-${drive.id}" class="flex-shrink-0">0%</span>
          </div>
          <div class="w-full bg-indigo-100 rounded-full h-2 overflow-hidden">
            <div id="prog-bar-${drive.id}" class="bg-indigo-600 h-full rounded-full transition-all duration-300" style="width: 0%"></div>
          </div>
        </div>
        <button id="btn-scan-${drive.id}" onclick="scanDrive('${drive.name.replace(/'/g, "\\'")}', '${drive.path.replace(/\\\\/g, '\\\\\\\\')}', ${drive.is_phone}, '${drive.id}')" class="w-full bg-slate-800 hover:bg-slate-900 text-white font-medium text-sm py-2.5 rounded-xl transition flex items-center justify-center space-x-2">
          <i class="fa-solid fa-magnifying-glass"></i>
          <span>Scanner Photos & Vidéos</span>
        </button>
      </div>
    `;
    container.appendChild(card);
  });
}

async function checkDetectedTakeouts() {
  try {
    const res = await fetch('/api/detect_takeout');
    const archives = await res.json();
    const banner = document.getElementById('takeoutBanner');
    const actions = document.getElementById('takeoutBannerActions');

    if (archives && archives.length > 0) {
      banner.classList.remove('hidden');
      actions.innerHTML = '';
      archives.forEach(arc => {
        const btn = document.createElement('button');
        btn.className = "bg-white text-amber-800 hover:bg-amber-50 font-bold text-xs px-4 py-2 rounded-xl transition shadow whitespace-nowrap";
        btn.innerText = `Scanner ${arc.name} (${arc.size_gb} Go)`;
        btn.onclick = () => scanTakeoutZipPath(arc.path);
        actions.appendChild(btn);
      });
    }
  } catch (e) {}
}

async function promptScanTakeoutZip() {
  const p = prompt("Entrez le chemin complet du fichier .zip Google Takeout sur votre ordinateur (ex: C:\\Users\\...\\Downloads\\takeout-2026.zip) :");
  if (p) scanTakeoutZipPath(p);
}

async function scanTakeoutZipPath(pathStr) {
  const box = document.getElementById('takeoutProgressBox');
  const txt = document.getElementById('takeoutProgressText');
  const pct = document.getElementById('takeoutProgressPct');
  const bar = document.getElementById('takeoutProgressBar');
  const statusElem = document.getElementById('takeoutStatus');

  if (box) box.classList.remove('hidden');
  if (txt) txt.innerText = "Ouverture du fichier ZIP...";

  const res = await fetch('/api/scan_takeout_zip', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: pathStr})
  });
  const data = await res.json();
  if (data.status === 'error') {
    alert(data.message);
    if (box) box.classList.add('hidden');
    return;
  }

  const timer = setInterval(async () => {
    const pRes = await fetch(`/api/progress?path=${encodeURIComponent(pathStr)}`);
    const p = await pRes.json();
    
    if (txt) txt.innerText = p.status;
    const percent = p.percent || (p.done ? 100 : 0);
    if (pct) pct.innerText = `${percent}%`;
    if (bar) bar.style.width = `${percent}%`;
    if (statusElem) statusElem.innerText = `${p.count} médias indexés`;

    if (p.done) {
      clearInterval(timer);
      updateLiveStats();
    }
  }, 600);
}

async function saveTargetDrive() {
  const select = document.getElementById('targetDriveSelect');
  const path = select.value;
  if (!path) return alert("Veuillez sélectionner un disque cible.");

  const res = await fetch('/api/set_target', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: path})
  });
  const data = await res.json();
  if (data.status === 'ok') {
    currentTargetDrive = path;
    document.getElementById('statTarget').innerText = path;
    loadDrives();
  }
}

async function scanDrive(name, path, isPhone, driveId) {
  const box = document.getElementById(`prog-box-${driveId}`);
  const txt = document.getElementById(`prog-txt-${driveId}`);
  const pct = document.getElementById(`prog-pct-${driveId}`);
  const bar = document.getElementById(`prog-bar-${driveId}`);
  const btn = document.getElementById(`btn-scan-${driveId}`);

  if (box) box.classList.remove('hidden');
  if (btn) {
    btn.disabled = true;
    btn.classList.add('opacity-50', 'cursor-not-allowed');
  }

  await fetch('/api/scan', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name, path: path, is_phone: isPhone})
  });

  const timer = setInterval(async () => {
    const res = await fetch(`/api/progress?path=${encodeURIComponent(path)}`);
    const p = await res.json();
    
    if (txt) txt.innerText = p.status;
    const percent = p.percent || (p.done ? 100 : 0);
    if (pct) pct.innerText = `${percent}%`;
    if (bar) bar.style.width = `${percent}%`;

    if (p.done) {
      clearInterval(timer);
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('opacity-50', 'cursor-not-allowed');
      }
      updateLiveStats();
    }
  }, 600);
}

async function scanGDrive() {
  const box = document.getElementById('gdriveProgressBox');
  const txt = document.getElementById('gdriveProgressText');
  const pct = document.getElementById('gdriveProgressPct');
  const bar = document.getElementById('gdriveProgressBar');

  if (box) box.classList.remove('hidden');
  if (txt) txt.innerText = "Connexion Google Drive...";

  const res = await fetch('/api/scan_gdrive', {method: 'POST'});
  const data = await res.json();
  if (data.status === 'error') {
    alert(data.message);
    if (box) box.classList.add('hidden');
    return;
  }

  const key = data.key;
  const timer = setInterval(async () => {
    const pRes = await fetch(`/api/progress?path=${encodeURIComponent(key)}`);
    const p = await pRes.json();
    if (txt) txt.innerText = p.status;
    if (bar) bar.style.width = p.done ? '100%' : '60%';
    if (pct) pct.innerText = p.done ? '100%' : `${p.count} trouvés`;

    if (p.done) {
      clearInterval(timer);
      updateLiveStats();
    }
  }, 1000);
}

async function startTakeoutGuide() {
  await fetch('/api/takeout_guide/start', {method: 'POST'});
  const statusElem = document.getElementById('takeoutStatus');
  const timer = setInterval(async () => {
    const res = await fetch('/api/takeout_guide/status');
    const st = await res.json();
    statusElem.innerText = st.step;
    if (st.done) clearInterval(timer);
  }, 1000);
}

async function updateLiveStats() {
  try {
    const res = await fetch('/api/live_stats');
    const stats = await res.json();
    document.getElementById('statTotal').innerText = stats.total;
    document.getElementById('statDuplicates').innerText = stats.duplicates_groups;
    if (stats.target_drive) {
      currentTargetDrive = stats.target_drive;
      document.getElementById('statTarget').innerText = stats.target_drive;
    }
  } catch (e) {}
}

async function loadExactDuplicates() {
  const list = document.getElementById('exactDuplicatesList');
  list.innerHTML = '<div class="text-center py-8 text-slate-400 text-sm">Chargement des doublons exacts...</div>';

  try {
    const res = await fetch('/api/exact_duplicates');
    const groups = await res.json();

    if (!groups || groups.length === 0) {
      list.innerHTML = '<div class="bg-white rounded-2xl p-12 text-center text-slate-500 font-medium card-shadow">Aucun doublon exact detecte dans votre phototheque.</div>';
      return;
    }

    list.innerHTML = '';
    groups.forEach(g => {
      const card = document.createElement('div');
      card.className = "bg-white rounded-2xl p-5 border border-slate-200 card-shadow space-y-4";
      
      let itemsHtml = '';
      g.items.forEach(it => {
        const isMasterBadge = it.is_master 
          ? '<span class="text-xs px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded-md font-bold">Garde</span>'
          : '<span class="text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded-md font-bold">Doublon</span>';
        
        const mediaBadge = it.media_type === 'video'
          ? `<span class="text-xs px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded font-semibold"><i class="fa-solid fa-video"></i> ${it.duration}s</span>`
          : `<span class="text-xs px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded font-semibold"><i class="fa-solid fa-image"></i> ${it.resolution}</span>`;

        itemsHtml += `
          <div class="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-slate-100 text-xs">
            <div class="flex items-center space-x-3 overflow-hidden">
              <img src="/api/thumb/${it.id}" class="w-12 h-12 object-cover rounded-lg bg-slate-200 flex-shrink-0" onerror="this.src=''">
              <div class="truncate">
                <div class="font-bold text-slate-800 truncate">${it.name}</div>
                <div class="text-slate-400 truncate">${it.source} &bull; ${it.size_kb} Ko &bull; ${it.date}</div>
              </div>
            </div>
            <div class="flex items-center space-x-3 flex-shrink-0">
              ${mediaBadge}
              ${isMasterBadge}
            </div>
          </div>
        `;
      });

      card.innerHTML = `
        <div class="flex items-center justify-between border-b border-slate-100 pb-3">
          <div class="flex items-center space-x-2 font-bold text-sm text-slate-800">
            <i class="fa-solid fa-copy text-amber-500"></i>
            <span>${g.file_name}</span>
            <span class="text-xs text-slate-400 font-normal">(${g.count} copies &bull; ${g.size_str})</span>
          </div>
        </div>
        <div class="space-y-2">${itemsHtml}</div>
      `;
      list.appendChild(card);
    });
  } catch (e) {
    list.innerHTML = '<div class="text-center py-8 text-red-500 text-sm">Erreur de chargement. Verifiez que des scans ont ete lances.</div>';
  }
}

async function deleteAllExactDuplicates() {
  if (!confirm("Voulez-vous supprimer toutes les copies redondantes des doublons exacts ? La meilleure version de chaque groupe sera preservee.")) return;
  const res = await fetch('/api/delete_all_exact_duplicates', {method: 'POST'});
  const data = await res.json();
  alert(`${data.deleted} doublons supprimes avec succes.`);
  loadExactDuplicates();
  updateLiveStats();
}

async function loadSimilarMedia() {
  const list = document.getElementById('similarMediaList');
  list.innerHTML = '<div class="text-center py-8 text-slate-400 text-sm">Analyse des similarites perceptuelles (pHash)...</div>';

  try {
    const res = await fetch('/api/similar_media');
    const clusters = await res.json();

    if (!clusters || clusters.length === 0) {
      list.innerHTML = '<div class="bg-white rounded-2xl p-12 text-center text-slate-500 font-medium card-shadow">Aucune photo ou video similaire en rafale detectee.</div>';
      return;
    }

    list.innerHTML = '';
    clusters.forEach(c => {
      const card = document.createElement('div');
      card.className = "bg-white rounded-2xl p-6 border border-slate-200 card-shadow space-y-4";

      let gridHtml = '';
      c.items.forEach(it => {
        const recBorder = it.is_recommended ? 'border-2 border-emerald-500' : 'border border-slate-200';
        const recBadge = it.is_recommended ? '<div class="absolute top-2 left-2 bg-emerald-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full shadow">Recommande</div>' : '';

        gridHtml += `
          <div class="relative bg-slate-50 rounded-xl overflow-hidden ${recBorder} flex flex-col justify-between">
            ${recBadge}
            <div class="aspect-square bg-slate-200 overflow-hidden flex items-center justify-center">
              <img src="/api/thumb/${it.id}" class="w-full h-full object-cover">
            </div>
            <div class="p-3 text-xs space-y-1">
              <div class="font-bold text-slate-800 truncate">${it.name}</div>
              <div class="text-slate-500">${it.resolution} &bull; ${it.size_kb} Ko</div>
              <div class="text-[11px] text-slate-400 truncate">${it.source}</div>
            </div>
          </div>
        `;
      });

      card.innerHTML = `
        <div class="flex items-center justify-between border-b border-slate-100 pb-3">
          <span class="text-xs font-bold uppercase text-indigo-600 tracking-wider">Groupe de similarite (${c.count} prises)</span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">${gridHtml}</div>
      `;
      list.appendChild(card);
    });
  } catch (e) {
    list.innerHTML = '<div class="text-center py-8 text-red-500 text-sm">Erreur de chargement des similaires.</div>';
  }
}

async function startCentralization() {
  if (!currentTargetDrive) return alert("Veuillez d'abord definir un disque cible dans l'onglet 1.");
  if (!confirm(`Confirmez-vous le rassemblement de tous vos fichiers sur ${currentTargetDrive} ? Les copies sources sur les disques durs seront nettoyees (le telephone est protege et ne sera JAMAIS efface).`)) return;

  const btn = document.getElementById('btnStartTransfer');
  const box = document.getElementById('transferProgressBox');
  btn.disabled = true;
  box.classList.remove('hidden');

  await fetch('/api/centralize', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({dest: currentTargetDrive})
  });

  const timer = setInterval(async () => {
    const res = await fetch('/api/centralize/progress');
    const p = await res.json();
    
    document.getElementById('transferStatusText').innerText = p.status;
    const percent = p.total > 0 ? Math.round((p.current / p.total) * 100) : 0;
    document.getElementById('transferPercentText').innerText = `${percent}% (${p.current}/${p.total})`;
    document.getElementById('transferProgressBar').style.width = `${percent}%`;

    if (!p.running && p.current >= p.total) {
      clearInterval(timer);
      btn.disabled = false;
      alert(`Centralisation terminee !\n- Fichiers deplaces : ${p.moved}\n- Originaux telephone preserves : ${p.copied_phone}\n- Doublons fusionnes : ${p.duplicates_merged}`);
      updateLiveStats();
    }
  }, 1000);
}

window.onload = () => {
  loadDrives();
  checkDetectedTakeouts();
  updateLiveStats();
};
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/drives', methods=['GET'])
def api_drives():
    return jsonify(get_system_drives())

@app.route('/api/detect_takeout', methods=['GET'])
def api_detect_takeout():
    return jsonify(detect_takeout_archives())

@app.route('/api/set_target', methods=['POST'])
def api_set_target():
    global TARGET_DRIVE
    TARGET_DRIVE = request.json.get('path')
    return jsonify({"status": "ok", "target": TARGET_DRIVE})

@app.route('/api/scan', methods=['POST'])
def api_scan():
    global scans_active
    data = request.json
    path = data.get('path')
    name = data.get('name')
    is_phone = data.get('is_phone', False)

    if not path or not os.path.exists(path):
        return jsonify({"status": "error", "message": "Chemin invalide"}), 400

    scans_active += 1
    threading.Thread(
        target=scan_directory,
        args=(name, path, is_phone, scan_progress, path),
        daemon=True
    ).start()
    return jsonify({"status": "started"})

@app.route('/api/scan_takeout_zip', methods=['POST'])
def api_scan_takeout_zip():
    global scans_active
    data = request.json
    zip_path = data.get('path')
    if not zip_path or not os.path.exists(zip_path):
        return jsonify({"status": "error", "message": "Fichier ZIP Takeout introuvable."}), 400
    
    scans_active += 1
    threading.Thread(
        target=scan_takeout_zip,
        args=(zip_path, scan_progress, zip_path),
        daemon=True
    ).start()
    return jsonify({"status": "started", "path": zip_path})

@app.route('/api/progress', methods=['GET'])
def api_progress():
    path = request.args.get('path')
    if path in scan_progress:
        return jsonify(scan_progress[path])
    return jsonify({"count": 0, "status": "En attente...", "done": False, "error": False})

@app.route('/api/scan_gdrive', methods=['POST'])
def api_scan_gdrive():
    global gdrive_accounts, scans_active
    client_id = GOOGLE_CLIENT_CONFIG["installed"].get("client_id")
    client_secret = GOOGLE_CLIENT_CONFIG["installed"].get("client_secret")
    if not client_id or not client_secret:
        return jsonify({"status": "error", "message": "Clés Google manquantes dans config/.env (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)."}), 400
    
    gdrive_accounts += 1
    path_key = f"gdrive_{gdrive_accounts}"
    scans_active += 1
    threading.Thread(
        target=scan_gdrive_account,
        args=(gdrive_accounts, scan_progress, path_key),
        daemon=True
    ).start()
    return jsonify({"status": "started", "account_id": gdrive_accounts, "key": path_key})

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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM photos')
    total = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM (SELECT sha256 FROM photos WHERE sha256 IS NOT NULL GROUP BY sha256 HAVING COUNT(*) > 1)')
    dup_count = cursor.fetchone()[0]
    conn.close()
    return jsonify({
        "total": total,
        "duplicates_groups": dup_count,
        "scans_active": scans_active > 0,
        "target_drive": TARGET_DRIVE
    })

@app.route('/api/exact_duplicates', methods=['GET'])
def api_exact_duplicates():
    page = int(request.args.get('page', 1))
    groups = get_exact_duplicate_groups(page=page, per_page=30, target_drive=TARGET_DRIVE)
    return jsonify(groups)

@app.route('/api/similar_media', methods=['GET'])
def api_similar_media():
    clusters = get_similar_media_groups(max_groups=30, target_drive=TARGET_DRIVE)
    return jsonify(clusters)

@app.route('/api/delete_all_exact_duplicates', methods=['POST'])
def api_delete_all_exact_duplicates():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT sha256 FROM photos WHERE sha256 IS NOT NULL GROUP BY sha256 HAVING COUNT(*) > 1')
    hashes = [row[0] for row in cursor.fetchall()]

    deleted_count = 0
    for sha in hashes:
        cursor.execute('SELECT id, file_path, is_phone, rating FROM photos WHERE sha256 = ?', (sha,))
        items = list(cursor.fetchall())
        if len(items) < 2:
            continue
        items.sort(key=lambda it: (it['rating'] or 0, 1 if TARGET_DRIVE and it['file_path'].startswith(TARGET_DRIVE) else 0), reverse=True)
        
        # Conserver le master (index 0) et supprimer les copies secondaires (hors téléphone et zip)
        for it in items[1:]:
            pid = it['id']
            p_path = it['file_path']
            is_phone = bool(it['is_phone'])
            is_zip = p_path.startswith("zip://")
            if not is_phone and not is_zip and os.path.exists(p_path):
                try:
                    os.remove(p_path)
                except Exception:
                    pass
            cursor.execute('DELETE FROM photos WHERE id = ?', (pid,))
            deleted_count += 1

    conn.commit()
    conn.close()
    return jsonify({"status": "success", "deleted": deleted_count})

@app.route('/api/centralize', methods=['POST'])
def api_centralize():
    dest = request.json.get('dest') or TARGET_DRIVE
    if not dest:
        return jsonify({"status": "error", "message": "Disque cible non spécifié."}), 400
    threading.Thread(target=safe_centralize_and_clean, args=(dest,), daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/api/centralize/progress', methods=['GET'])
def api_centralize_progress():
    return jsonify(transfer_progress)

@app.route('/api/thumb/<int:media_id>')
def api_thumb(media_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT file_path, media_type FROM photos WHERE id = ?', (media_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "Média introuvable", 404

    f_path = row['file_path']
    if not f_path.startswith("zip://") and not os.path.exists(f_path):
        return "Fichier introuvable sur disque", 404

    buf = generate_thumbnail_bytes(f_path, media_type=row['media_type'])
    if buf:
        return send_file(buf, mimetype='image/jpeg')
    return "Erreur vignette", 500
