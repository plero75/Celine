import argparse
import ctypes
import hashlib
import json
import os
import re
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

TARGETS = [
    {
        "name": "Ticketmaster Celine Dion",
        "url": "https://www.ticketmaster.fr/fr/manifestation/celine-dion-billet/idmanif/655223/idseance/4309061/attribauto",
    },
    {
        "name": "Fnac Spectacles Celine Dion",
        "url": "https://www.fnacspectacles.com/event/celine-dion-paris-2026-plenitude-arena-21511314/",
    },
]

STATE_PATH = Path("state/local_state.json")
PROFILE_DIR = Path("state/browser-profile")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def extract_prices(text):
    return sorted(set(re.findall(r"\b\d{1,4}(?:[,.]\d{2})?\s*€", text)))


def extract_interesting_lines(text):
    keywords = [
        "disponible", "indisponible", "places", "billets", "tarif", "catégorie",
        "categorie", "panier", "réserver", "reserver", "forte demande", "session",
        "robot", "file d'attente", "choisir vos places", "ajouter au panier",
    ]
    chunks = re.split(r"(?<=[.!?])\s+|\s{2,}", text)
    lines = []
    for chunk in chunks:
        chunk = normalize_text(chunk)
        low = chunk.lower()
        if 15 <= len(chunk) <= 300 and any(k in low for k in keywords):
            lines.append(chunk)
    return list(dict.fromkeys(lines))[:15]


def classify_status(text, http_status=None):
    low = text.lower()
    if http_status in (401, 403, 429):
        return "bloqué / anti-bot"
    if "votre session a été suspendue" in low or "robot" in low or "access denied" in low:
        return "bloqué / anti-bot"
    if "indisponible" in low and "des places peuvent se libérer" in low:
        return "indisponible - attente remise en vente"
    if "indisponible" in low:
        return "indisponible"
    available_words = [
        "ajouter au panier", "choisir vos places", "réserver", "reserver",
        "places disponibles", "billets disponibles", "sélectionner", "selectionner",
        "à partir de", "a partir de",
    ]
    if any(word in low for word in available_words):
        return "possiblement disponible"
    return "état inconnu"


def signature_for(snapshot):
    payload = {
        "status": snapshot.get("status"),
        "prices": snapshot.get("prices", []),
        "interesting_lines": snapshot.get("interesting_lines", []),
        "final_url": snapshot.get("final_url"),
        "http_status": snapshot.get("http_status"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def should_alert(previous, current):
    if previous is None:
        return False

    prev_status = previous.get("status")
    new_status = current.get("status")
    prices = current.get("prices", [])

    if new_status == "possiblement disponible":
        return True
    if prices and prices != previous.get("prices", []):
        return True
    if prev_status and new_status and prev_status != new_status:
        ignored = {"bloqué / anti-bot", "erreur", "état inconnu"}
        if new_status not in ignored:
            return True
    return False


def notify(title, message):
    print("\a")
    print("\n" + "=" * 80)
    print(title)
    print(message)
    print("=" * 80 + "\n")

    if sys.platform.startswith("win"):
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)
        except Exception:
            pass


def create_github_issue_if_configured(target_name, previous, current):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "plero75/Celine")
    if not token:
        return

    title = f"🎟️ Alerte places Céline — {target_name}"
    body = f"""
Alerte détectée depuis le watcher local.

Page : {current.get('url')}
URL finale : {current.get('final_url')}

Ancien statut : `{previous.get('status') if previous else 'aucun'}`
Nouveau statut : `{current.get('status')}`
Prix détectés : `{current.get('prices', [])}`

Extraits utiles :
{chr(10).join('- ' + x for x in current.get('interesting_lines', [])) or '- Aucun'}

Vérifié le : `{current.get('checked_at')}`
""".strip()

    res = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"title": title, "body": body},
        timeout=30,
    )
    if res.status_code >= 300:
        print(f"Issue GitHub non créée : {res.status_code} {res.text[:300]}")
    else:
        print("Issue GitHub créée.")


def fetch_with_browser(context, target, wait_seconds):
    page = context.new_page()
    response = None
    try:
        response = page.goto(target["url"], wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(wait_seconds * 1000)
        try:
            text = page.locator("body").inner_text(timeout=30000)
        except Exception:
            text = page.content()
        text = normalize_text(text)
        http_status = response.status if response else None
        current = {
            "name": target["name"],
            "url": target["url"],
            "final_url": page.url,
            "http_status": http_status,
            "checked_at": now_iso(),
            "status": classify_status(text, http_status),
            "prices": extract_prices(text),
            "interesting_lines": extract_interesting_lines(text),
            "text_sample": text[:1000],
        }
        current["signature"] = signature_for(current)
        current["full_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return current
    except PlaywrightTimeoutError as exc:
        return {
            "name": target["name"],
            "url": target["url"],
            "checked_at": now_iso(),
            "status": "erreur",
            "error": f"Timeout navigateur: {exc}",
            "signature": hashlib.sha256(f"timeout:{target['url']}".encode("utf-8")).hexdigest(),
        }
    except Exception as exc:
        return {
            "name": target["name"],
            "url": target["url"],
            "checked_at": now_iso(),
            "status": "erreur",
            "error": str(exc),
            "signature": hashlib.sha256(f"error:{target['url']}:{exc}".encode("utf-8")).hexdigest(),
        }
    finally:
        try:
            page.close()
        except Exception:
            pass


def run_once(args):
    state = load_state()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=args.headless,
            locale="fr-FR",
            viewport={"width": 1400, "height": 1000},
        )
        try:
            for target in TARGETS:
                print(f"Vérification locale : {target['name']}")
                current = fetch_with_browser(context, target, args.wait)
                previous = state.get(target["name"])

                print(f"  Statut : {current.get('status')} | HTTP : {current.get('http_status')} | Prix : {current.get('prices', [])}")

                if previous is None:
                    print("  Première vérification : état local enregistré sans alerte.")
                elif current.get("signature") != previous.get("signature"):
                    print("  Changement détecté.")
                    if should_alert(previous, current):
                        message = (
                            f"{target['name']}\n"
                            f"Statut : {current.get('status')}\n"
                            f"Prix : {current.get('prices', [])}\n"
                            f"URL : {current.get('url')}"
                        )
                        notify("Alerte billets Céline Dion", message)
                        if args.open_on_alert:
                            webbrowser.open(current.get("url"))
                        create_github_issue_if_configured(target["name"], previous, current)
                    else:
                        print("  Changement non critique : pas d'alerte.")
                else:
                    print("  Aucun changement utile.")

                if current.get("status") == "erreur" and previous:
                    print("  Erreur temporaire : on garde aussi l'ancien état en mémoire, mais on note l'erreur.")

                state[target["name"]] = current
                save_state(state)
        finally:
            context.close()


def main():
    parser = argparse.ArgumentParser(description="Watcher local Céline Dion Ticketmaster/Fnac")
    parser.add_argument("--loop", action="store_true", help="relance en boucle")
    parser.add_argument("--interval", type=int, default=600, help="secondes entre deux vérifications")
    parser.add_argument("--headless", action="store_true", help="mode invisible, moins conseillé pour les billetteries")
    parser.add_argument("--wait", type=int, default=8, help="secondes d'attente après chargement de page")
    parser.add_argument("--open-on-alert", action="store_true", help="ouvre la page dans le navigateur par défaut en cas d'alerte")
    args = parser.parse_args()

    while True:
        run_once(args)
        if not args.loop:
            break
        print(f"Prochaine vérification dans {args.interval} secondes. Ctrl+C pour arrêter.")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
