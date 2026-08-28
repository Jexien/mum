"""Module d'assistance interactif pour Google Takeout et import d'archives Photos."""

import os
import time
import subprocess
import threading
from pathlib import Path

from .config import PROFILES_DIR, find_chrome_exe

guide_manual_advance = threading.Event()
guide_status = {"step": "", "done": True, "error": False}

def _highlight(page, locator, message):
    """Surligne un élément dans la page Chrome pour guider l'utilisateur."""
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
        handle = locator.element_handle()
        if not handle:
            return False
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
            window.__mum_click_detected__ = false;
            el.addEventListener("click", () => { window.__mum_click_detected__ = true; }, {capture: true});
        }"""
        page.evaluate(js_code, [handle, message])
        return True
    except Exception:
        return False

def _click_detected(page):
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

def run_takeout_guide():
    """Lance l'assistant pas-à-pas interactif Google Takeout."""
    global guide_status
    guide_status = {"step": "Recherche de Google Chrome sur votre PC...", "done": False, "error": False}

    chrome_path = find_chrome_exe()
    if not chrome_path:
        guide_status = {"step": "Google Chrome introuvable. Installez Chrome pour utiliser l'assistant automatique.", "done": True, "error": True}
        return

    from playwright.sync_api import sync_playwright
    profile_dir = str(PROFILES_DIR / "chrome_takeout_profile")
    os.makedirs(profile_dir, exist_ok=True)
    debug_port = 9333

    try:
        chrome_proc = subprocess.Popen([
            chrome_path,
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://takeout.google.com/settings/takeout/custom/photos"
        ])
    except Exception as e:
        guide_status = {"step": f"Erreur de lancement de Chrome : {e}", "done": True, "error": True}
        return

    try:
        with sync_playwright() as p:
            browser = None
            for _ in range(30):
                try:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
                    break
                except Exception:
                    time.sleep(0.5)

            if not browser:
                guide_status = {"step": "Impossible de se connecter à Chrome.", "done": True, "error": True}
                return

            contexts = browser.contexts
            context = contexts[0] if contexts else browser.new_context()
            pages = context.pages
            page = pages[0] if pages else context.new_page()

            guide_status["step"] = "1/4 : Connectez-vous à votre compte Google dans Chrome si demandé."
            
            # Étape 1 : Attendre la page Takeout
            def is_takeout_ready():
                return "takeout.google.com" in page.url and "signin" not in page.url.lower()

            _wait_until(is_takeout_ready, timeout_s=300)

            # Étape 2 : Étape suivante
            guide_status["step"] = "2/4 : Cliquez sur 'Étape suivante' en bas de la page Takeout."
            btn_next = page.locator("text=Étape suivante").or_(page.locator("text=Next step"))
            if btn_next.count() > 0:
                _highlight(page, btn_next.first, "Cliquez sur 'Étape suivante'")
                _wait_until(lambda: _click_detected(page) or "custom" not in page.url, timeout_s=120)
            _clear_highlight(page)

            # Étape 3 : Création de l'export
            guide_status["step"] = "3/4 : Choisissez la taille de fichier (50 Go recommandé) et cliquez sur 'Créer une exportation'."
            btn_create = page.locator("text=Créer une exportation").or_(page.locator("text=Create export"))
            if btn_create.count() > 0:
                _highlight(page, btn_create.first, "Cliquez ici pour démarrer l'export Google Photos")
                _wait_until(lambda: _click_detected(page), timeout_s=300)
            _clear_highlight(page)

            guide_status = {"step": "Export lancé avec succès ! Google vous notifiera par email une fois prêt.", "done": True, "error": False}

    except Exception as e:
        guide_status = {"step": f"Erreur pendant l'assistant : {e}", "done": True, "error": True}
