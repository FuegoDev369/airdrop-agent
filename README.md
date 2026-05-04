# 🤖 AirdropAgent

> Agent autonome multi-projets pour maximiser tes chances d'airdrop Web3.
> Surveille Twitter, Telegram et Discord. Génère des actions concrètes. Notifie sur Discord et Telegram.

**Par FuegoDev** — Open Source, Python, GitHub Actions.

---

## Pourquoi AirdropAgent ?

L'ère des bots multi-wallets est révolue. Les projets Web3 récompensent désormais **l'engagement qualitatif et constant** — tweets pertinents, participation Discord active, présence communautaire régulière.

Suivre 3 à 5 projets simultanément avec cette rigueur est **impossible sans outil dédié**.

AirdropAgent résout exactement ce problème :

- 📡 **Surveillance continue** de Twitter, Telegram et Discord de chaque projet suivi
- 🧠 **Analyse IA** des signaux (quêtes, snapshots, annonces importantes)
- 🐦 **Tweets générés** prêts à poster, contextualisés sur l'actualité du projet
- 🔔 **Notifications intelligentes** sur Discord et/ou Telegram
- 🤖 **100% autonome** via GitHub Actions — tourne seul, sans serveur

---

## Architecture rapide

```
GitHub Actions (cron toutes les 2h)
        │
        ▼
    agent.py (orchestrateur)
        │
        ├── TwitterTracker   → tweets via Nitter (sans API)
        ├── TelegramTracker  → messages canaux via Telethon
        │
        ├── LLMEngine        → Groq API (Llama 70B gratuit)
        │     ├── Classifier les signaux (urgence 1-10)
        │     ├── Générer des tweets authentiques
        │     └── Briefing quotidien
        │
        ├── ContentEngine    → Plan d'actions par projet
        │
        └── Notifier         → Discord Webhook + Telegram Bot
                │
                ▼
        Toi (sur ton téléphone)
```

**Persistance DB** : SQLite uploadée/téléchargée via **GitHub Artifacts** à chaque run.

---

## Installation & Déploiement

### Prérequis

- Compte GitHub
- Compte Groq (gratuit) → https://console.groq.com
- Bot Telegram (gratuit) → voir section dédiée
- Webhook Discord (gratuit) → voir section dédiée

---

### Étape 1 — Fork le repo

```
https://github.com/FuegoDev/airdrop-agent
```

Clique sur **Fork** en haut à droite → tu obtiens ton propre repo.

---

### Étape 2 — Configurer les projets à suivre

Édite `config/settings.yaml` dans ton fork :

```yaml
projects:
  - name: "MONAD"
    twitter_handle: "monad_xyz"
    discord_invite: "monad"        # Partie après discord.gg/
    telegram_handle: "monadxyz"
    chain: "monad-testnet"
    priority: 9                    # 1 (bas) à 10 (critique)
    tags: ["L1", "testnet"]

  - name: "TON_PROJET"
    twitter_handle: "handle_twitter"
    telegram_handle: "handle_telegram"
    priority: 8
```

Active/désactive les notifications selon tes préférences :

```yaml
notifications:
  discord:
    enabled: true          # ← false pour désactiver Discord
    daily_brief: true
    action_suggestions: true

  telegram:
    enabled: true          # ← false pour désactiver Telegram
    snapshot_alerts: true
```

---

### Étape 3 — Obtenir la clé Groq (LLM gratuit)

1. Va sur https://console.groq.com
2. Crée un compte gratuit
3. Va dans **API Keys** → **Create API Key**
4. Copie la clé (commence par `gsk_...`)

> Le plan gratuit offre 14 400 requêtes/jour — largement suffisant.

---

### Étape 4 — Créer le bot Telegram (pour recevoir les notifications)

1. Ouvre Telegram → recherche **@BotFather**
2. Envoie `/newbot`
3. Suis les instructions → tu obtiens un **token** (format `123456:ABCdef...`)
4. Pour obtenir ton **chat_id** :
   - Envoie un message à ton bot
   - Ouvre : `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Cherche `"chat":{"id": XXXXXXXXX}` — c'est ton chat_id

---

### Étape 5 — Créer le Webhook Discord

1. Ouvre ton serveur Discord
2. Va dans **Paramètres du salon** → **Intégrations** → **Webhooks**
3. Clique **Nouveau Webhook**
4. Copie l'**URL du Webhook** (format `https://discord.com/api/webhooks/...`)

> Tu peux créer un salon Discord dédié `#airdrop-agent` pour recevoir les notifications.

---

### Étape 6 — Configurer les GitHub Secrets

C'est l'étape **critique**. Tous tes credentials sont stockés ici, jamais dans le code.

Dans ton repo GitHub :
**Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Ajoute ces secrets un par un :

| Nom du secret | Valeur | Obligatoire |
|---|---|---|
| `GROQ_API_KEY` | Ta clé Groq `gsk_...` | ✅ Oui |
| `DISCORD_WEBHOOK` | URL webhook Discord | Si Discord activé |
| `TELEGRAM_BOT_TOKEN` | Token du bot `123456:ABCdef...` | Si Telegram activé |
| `TELEGRAM_CHAT_ID` | Ton chat_id numérique | Si Telegram activé |
| `TELEGRAM_API_ID` | ID API Telegram (Phase 3) | Non (optionnel) |
| `TELEGRAM_API_HASH` | Hash API Telegram (Phase 3) | Non (optionnel) |

> **Sécurité** : Les secrets GitHub sont chiffrés et jamais visibles après création. Ne les mets jamais dans le code ou dans settings.yaml.

---

### Étape 7 — Activer GitHub Actions

1. Dans ton repo → onglet **Actions**
2. Si un message demande d'activer les workflows → clique **I understand my workflows, go ahead and enable them**
3. Le workflow `AirdropAgent — Run Autonome` apparaît dans la liste

**Test immédiat** : Clique sur le workflow → **Run workflow** → **Run workflow** (bouton vert)
→ L'agent se lance manuellement pour la première fois.

---

### Étape 8 — Vérifier que tout fonctionne

Après le premier run (2-3 minutes) :

1. **Onglet Actions** → Clique sur le run → Vérifie les logs
2. **Ton Discord** → Tu dois recevoir des notifications
3. **Ton Telegram** → Idem

Si des erreurs apparaissent, voir la section **Dépannage** ci-dessous.

---

## Persistance de la base de données (GitHub Artifacts)

### Comment ça fonctionne

AirdropAgent utilise une base SQLite (`data/agent.db`) pour stocker :
- L'historique des signaux collectés
- Les actions générées
- Les runs passés et leurs statistiques

À chaque run GitHub Actions :

```
Début du run
    │
    ▼
Download agent.db depuis Artifacts  ← Restauration de l'état précédent
    │
    ▼
Exécution de l'agent (lecture + écriture DB)
    │
    ▼
Upload agent.db vers Artifacts      ← Sauvegarde du nouvel état
    │
    ▼
Fin du run
```

### Récupérer la DB en local (git pull équivalent)

Pour accéder à l'état actuel de la DB depuis Termux ou ta machine locale :

**Méthode 1 — Interface GitHub :**
1. Onglet **Actions** → Clique sur le dernier run réussi
2. Section **Artifacts** en bas de page
3. Télécharge `agent-db.zip` → décompresse → tu obtiens `agent.db`

**Méthode 2 — GitHub CLI (gh) depuis Termux :**
```bash
# Installer GitHub CLI
pkg install gh

# Authentification
gh auth login

# Télécharger le dernier artifact
gh run download --name agent-db --dir data/
```

**Méthode 3 — Script automatique :**
```bash
# scripts/sync_db.sh
#!/bin/bash
REPO="ton-username/airdrop-agent"
RUN_ID=$(gh run list --repo $REPO --limit 1 --json databaseId -q '.[0].databaseId')
gh run download $RUN_ID --repo $REPO --name agent-db --dir data/
echo "DB synchronisée depuis le run #$RUN_ID"
```

### Durée de rétention

Les artifacts sont conservés **90 jours** par défaut (configurable dans `agent.yml`).
Après 90 jours, l'artifact est supprimé mais la DB du prochain run repart de la dernière disponible.

### Limites du plan gratuit GitHub

| Ressource | Limite gratuite | Consommation AirdropAgent |
|---|---|---|
| Minutes Actions/mois | 2 000 min | ~10 min/run × 360 runs/mois = ~600 min ✅ |
| Stockage Artifacts | 500 MB | agent.db < 10 MB ✅ |

---

## Usage local (Termux)

Pour tester ou lancer manuellement depuis Termux :

```bash
# Cloner ton fork
git clone https://github.com/TON_USERNAME/airdrop-agent.git
cd airdrop-agent

# Installer les dépendances
pip install -r requirements.txt

# Configurer les variables d'environnement localement
export GROQ_API_KEY="gsk_..."
export DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
export TELEGRAM_BOT_TOKEN="123456:ABCdef..."
export TELEGRAM_CHAT_ID="123456789"

# Lancer l'agent
python -m core.agent
```

**Pour usage local avec Ollama** (sans connexion internet pour le LLM) :

```bash
# Installer Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Télécharger le modèle Mistral
ollama pull mistral

# Modifier settings.yaml
# llm:
#   mode: "ollama"
```

---

## Ajouter / Modifier des projets

**Sans toucher au code** — édite uniquement `config/settings.yaml` :

```yaml
projects:
  - name: "NOUVEAU_PROJET"
    twitter_handle: "handle"
    telegram_handle: "handle_tg"
    discord_invite: "xxx"     # Ce qui suit discord.gg/
    chain: "ethereum"
    priority: 7
    tags: ["DeFi", "L2"]
```

Commit et push → le prochain run GitHub Actions prend en compte le changement.

---

## Fréquence des runs

Modifie le cron dans `.github/workflows/agent.yml` :

```yaml
schedule:
  - cron: '0 */2 * * *'    # Toutes les 2 heures (défaut)
  - cron: '0 */4 * * *'    # Toutes les 4 heures (économe)
  - cron: '0 * * * *'      # Toutes les heures (intensif)
  - cron: '0 8,14,20 * * *' # 3 fois par jour (8h, 14h, 20h UTC)
```

---

## Dépannage

### L'agent tourne mais je ne reçois rien sur Discord/Telegram

1. Vérifie que les secrets GitHub sont bien configurés (Settings → Secrets)
2. Dans `settings.yaml`, vérifie que `enabled: true` pour le canal voulu
3. Vérifie que `urgency_threshold` n'est pas trop élevé (essaie `5` pour tester)

### Erreur "GROQ_API_KEY manquant"

Le secret `GROQ_API_KEY` n'est pas configuré dans GitHub Secrets.
Voir Étape 6 du guide d'installation.

### Les tweets ne sont pas récupérés (instances Nitter)

Les instances Nitter publiques peuvent être instables. Solutions :
1. Vérifie les instances dans `settings.yaml` → `twitter.nitter_instances`
2. Cherche des instances actives sur : https://status.d420.de
3. Remplace les instances hors-ligne dans ta config

### La DB ne persiste pas entre les runs

Vérifie que le step `Save agent database` dans le workflow s'est exécuté (même en cas d'erreur, `if: always()` est configuré). Si le premier run échoue avant d'écrire la DB, l'artifact n'existe pas — c'est normal, le second run crée une DB fraîche.

### Erreur de permission sur git push

Vérifie que `permissions: contents: write` est bien présent dans `agent.yml`.

---

## Roadmap

- [x] **Phase 1** — Twitter tracker + LLM + Notifications Discord/Telegram
- [x] **Phase 1** — GitHub Actions + Persistance Artifacts
- [ ] **Phase 2** — Telegram tracker (Telethon) complet
- [ ] **Phase 3** — Discord bot (lecture channels)
- [ ] **Phase 3** — On-chain tracker (RPC publics)
- [ ] **Phase 4** — TGE Radar + Snapshot Engine
- [ ] **Phase 4** — Wallet scoring simulator
- [ ] **Phase 5** — Interface web légère (FastAPI)

---

## Contribution

Les PRs sont les bienvenues. Ce projet est personnel avant tout — teste, fork, adapte.

---

## Licence

MIT — Libre d'utilisation, modification et distribution.

---

*AirdropAgent — FuegoDev*
