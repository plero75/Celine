# Céline Ticket Watch

Outil de surveillance pour les pages billets Céline Dion :

- Ticketmaster : séance fournie
- Fnac Spectacles : Paris 2026, Plenitude Arena

## Ce qui marche vraiment

Les sites de billetterie bloquent souvent les serveurs GitHub Actions. Quand GitHub Actions renvoie `403`, `bloqué / anti-bot` ou des timeouts Fnac, ce n'est pas forcément un bug du script : c'est le site qui refuse ou ralentit les accès automatiques depuis les datacenters GitHub.

La méthode la plus fiable est donc le **watcher local Windows**, qui ouvre les pages avec un vrai navigateur Playwright et un profil persistant.

## Installation locale Windows recommandée

Dans PowerShell, depuis le dossier du repo :

```powershell
.\install-local-watch.ps1
```

Puis lance la surveillance toutes les 10 minutes :

```powershell
.\run-local-watch.ps1
```

Au premier lancement, une fenêtre Chromium peut s'ouvrir. Si Ticketmaster ou Fnac demande une vérification manuelle, fais-la dans cette fenêtre. Le profil est conservé dans `state/browser-profile`, donc les sessions peuvent être réutilisées aux passages suivants.

En cas d'alerte utile, le script affiche une fenêtre Windows et ouvre la page si `--open-on-alert` est activé.

## Lancement local ponctuel

```powershell
python .\local_watch.py
```

## Lancement local en boucle

```powershell
python .\local_watch.py --loop --interval 600 --open-on-alert
```

`600` = 600 secondes = 10 minutes.

## GitHub Actions, en mode best effort

Le workflow `.github/workflows/watch-celine.yml` continue de tourner toutes les 10 minutes et peut créer une issue GitHub si un changement utile est détecté.

Mais pour Ticketmaster et parfois Fnac, GitHub Actions peut être bloqué :

- `403` = blocage / anti-bot
- `429` = trop de requêtes / limitation
- timeout = site trop lent ou filtrage réseau

Donc GitHub Actions est utile en appoint, mais pas assez fiable comme unique surveillance.

## Alertes GitHub depuis le watcher local optionnel

Le watcher local peut aussi créer une issue GitHub si tu définis un token :

```powershell
$env:GH_TOKEN="ton_token_github"
$env:GITHUB_REPOSITORY="plero75/Celine"
python .\local_watch.py --loop --interval 600 --open-on-alert
```

Sans token, il fait simplement une alerte locale Windows.

## Fichiers importants

- `local_watch.py` : watcher local recommandé
- `install-local-watch.ps1` : installation Windows
- `run-local-watch.ps1` : lancement toutes les 10 minutes
- `watch.py` : watcher GitHub Actions best effort
- `.github/workflows/watch-celine.yml` : exécution automatique GitHub
- `state/local_state.json` : état du watcher local
- `state/state.json` : état du watcher GitHub Actions
