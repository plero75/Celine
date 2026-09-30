# Céline Ticket Watch

Petit outil GitHub Actions pour surveiller automatiquement :

- Ticketmaster : Céline Dion, séance fournie
- Fnac Spectacles : Céline Dion Paris 2026, Plenitude Arena

Le workflow tourne toutes les 10 minutes et crée une issue GitHub quand un changement utile est détecté : disponibilité, indisponibilité, prix, texte important, blocage anti-bot, etc.

## Installation rapide

1. Créer un nouveau repo GitHub, par exemple `celine-ticket-watch`.
2. Importer tous les fichiers de ce ZIP à la racine du repo.
3. Aller dans l'onglet **Actions**.
4. Activer les workflows si GitHub le demande.
5. Ouvrir le workflow **Watch Celine tickets**.
6. Cliquer sur **Run workflow** une première fois.
7. Le fichier `state/state.json` sera créé automatiquement après la première exécution.
8. Les exécutions suivantes créeront une issue si un changement est détecté.

## Important

GitHub Actions exécute les tâches planifiées environ toutes les 10 minutes via :

```yaml
cron: "*/10 * * * *"
```

Sur les comptes gratuits, GitHub peut parfois décaler les exécutions de quelques minutes.

## Alertes

Par défaut, l'alerte est une **issue GitHub**.

Pour bien recevoir les alertes :

- vérifier que les notifications GitHub sont activées ;
- surveiller le repo ;
- laisser les permissions du workflow avec `issues: write`.

## Ticketmaster

Ticketmaster peut bloquer les requêtes automatiques avec une protection anti-bot. Dans ce cas, le script peut détecter un statut `bloqué / anti-bot`, mais cela ne veut pas dire que des places sont disponibles.

Fnac Spectacles devrait être plus stable à surveiller.
