import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


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

STATE_PATH = Path("state/state.json")
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

ERROR_STATUSES = {
    "erreur",
    "erreur temporaire",
    "bloqué / anti-bot",
    "erreur serveur",
    "erreur HTTP",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clean_text(html):
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text("\n")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_prices(text):
    prices = re.findall(r"\b\d{1,4}(?:[,.]\d{2})?\s*€", text)
    return sorted(set(prices))


def extract_interesting_lines(text):
    keywords = [
        "disponible",
        "indisponible",
        "places",
        "billets",
        "tarif",
        "catégorie",
        "categorie",
        "panier",
        "réserver",
        "reserver",
        "forte demande",
        "file d'attente",
        "session suspendue",
        "robot",
        "accès refusé",
        "access denied",
        "forbidden",
    ]

    chunks = re.split(r"(?<=[.!?])\s+|\s{2,}", text or "")
    lines = []

    for chunk in chunks:
        low = chunk.lower()
        if any(k in low for k in keywords):
            chunk = chunk.strip()
            if 15 <= len(chunk) <= 300:
                lines.append(chunk)

    return list(dict.fromkeys(lines))[:12]


def classify_status(text, http_status=None):
    low = (text or "").lower()

    if http_status in (401, 403, 429):
        return "bloqué / anti-bot"

    if http_status and http_status >= 500:
        return "erreur serveur"

    if http_status and http_status >= 400:
        return "erreur HTTP"

    if "votre session a été suspendue" in low or "robot" in low:
        return "bloqué / anti-bot"

    if "access denied" in low or "forbidden" in low or "accès refusé" in low:
        return "bloqué / anti-bot"

    if "indisponible" in low:
        return "indisponible"

    available_words = [
        "ajouter au panier",
        "choisir vos places",
        "réserver",
        "reserver",
        "places disponibles",
        "billets disponibles",
        "à partir de",
        "a partir de",
    ]

    if any(word in low for word in available_words):
        return "possiblement disponible"

    return "état inconnu"


def make_signature(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def request_with_retries(url):
    last_error = None

    with requests.Session() as session:
        session.headers.update(HEADERS)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                last_error = exc
                print(f"Tentative {attempt}/{MAX_RETRIES} échouée : {exc}")
                if attempt < MAX_RETRIES:
                    time.sleep(5 * attempt)

    raise last_error


def fetch_target(target):
    response = request_with_retries(target["url"])

    text = clean_text(response.text)
    prices = extract_prices(text)
    interesting_lines = extract_interesting_lines(text)
    status = classify_status(text, response.status_code)

    signature_payload = {
        "status": status,
        "prices": prices,
        "interesting_lines": interesting_lines,
        "final_url": response.url,
        "http_status": response.status_code,
    }

    return {
        "name": target["name"],
        "url": target["url"],
        "final_url": response.url,
        "http_status": response.status_code,
        "checked_at": now_iso(),
        "status": status,
        "prices": prices,
        "interesting_lines": interesting_lines,
        "signature": make_signature(signature_payload),
        "full_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def make_transient_error(target, exc):
    error_text = str(exc)
    payload = {
        "status": "erreur temporaire",
        "error_type": exc.__class__.__name__,
        "target": target["name"],
    }
    return {
        "name": target["name"],
        "url": target["url"],
        "checked_at": now_iso(),
        "status": "erreur temporaire",
        "error": error_text,
        "signature": make_signature(payload),
        "transient_error": True,
    }


def post_github_issue(repo, token, payload):
    url = f"https://api.github.com/repos/{repo}/issues"
    return requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json=payload,
        timeout=25,
    )


def create_github_issue(target_name, previous, current):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        print("GITHUB_TOKEN ou GITHUB_REPOSITORY manquant : issue non créée.")
        return

    title = f"🎟️ Changement détecté — {target_name}"

    previous_status = previous.get("status", "inconnu") if previous else "première vérification"
    previous_prices = previous.get("prices", []) if previous else []

    lines = current.get("interesting_lines", [])
    useful_extracts = "\n".join(f"- {line}" for line in lines) or "- Aucun extrait utile"

    body = f"""
Changement détecté sur **{target_name}**.

URL surveillée :
{current["url"]}

URL finale :
{current.get("final_url", "inconnue")}

Ancien statut :
`{previous_status}`

Nouveau statut :
`{current.get("status", "inconnu")}`

Anciens prix détectés :
`{previous_prices}`

Nouveaux prix détectés :
`{current.get("prices", [])}`

Extraits utiles détectés :

{useful_extracts}

HTTP status : `{current.get("http_status", "inconnu")}`  
Vérifié le : `{current.get("checked_at", now_iso())}`

Note : Ticketmaster peut déclencher une protection anti-bot. Une alerte “bloqué / anti-bot” ne veut pas forcément dire que des places sont disponibles.
""".strip()

    payload = {
        "title": title,
        "body": body,
        "labels": ["ticket-watch", "celine-dion"],
    }

    res = post_github_issue(repo, token, payload)

    if res.status_code == 422:
        print("Création avec labels impossible, nouvelle tentative sans labels.")
        payload.pop("labels", None)
        res = post_github_issue(repo, token, payload)

    if res.status_code >= 300:
        print(f"Erreur création issue GitHub : {res.status_code} {res.text}")
    else:
        print(f"Issue créée pour {target_name}")


def should_alert(previous, current):
    if not previous:
        return False

    current_status = current.get("status")
    previous_status = previous.get("status")

    if current.get("transient_error"):
        return False

    if current_status in {"bloqué / anti-bot", "erreur serveur", "erreur HTTP", "erreur temporaire", "erreur"}:
        return False

    if previous_status in ERROR_STATUSES and current_status in {"indisponible", "état inconnu"}:
        return False

    if current_status == "possiblement disponible":
        return True

    if current.get("prices"):
        return True

    if previous_status == "possiblement disponible" and current_status != previous_status:
        return True

    return False


def should_update_state(previous, current):
    if previous is None:
        return not current.get("transient_error")

    if current.get("transient_error"):
        return False

    return previous.get("signature") != current.get("signature")


def main():
    state = load_state()
    changed = False

    for target in TARGETS:
        key = target["name"]
        previous = state.get(key)

        print(f"Vérification : {key}")

        try:
            current = fetch_target(target)
        except Exception as exc:
            print(f"Erreur temporaire sur {key} : {exc}")
            current = make_transient_error(target, exc)

        if previous is None:
            if should_update_state(previous, current):
                print(f"Première vérification pour {key}, état enregistré sans alerte.")
                state[key] = current
                changed = True
            else:
                print(f"Première vérification impossible pour {key}, état non modifié.")
            continue

        if previous.get("signature") == current.get("signature"):
            print(f"Aucun changement utile pour {key}")
            continue

        if should_alert(previous, current):
            print(f"Changement utile détecté pour {key}")
            create_github_issue(key, previous, current)
        else:
            print(f"Changement technique/non actionnable pour {key}, pas d'issue.")

        if should_update_state(previous, current):
            state[key] = current
            changed = True

    if changed:
        save_state(state)
        print("state/state.json mis à jour.")
    else:
        print("Aucun changement d'état à enregistrer.")


if __name__ == "__main__":
    main()
