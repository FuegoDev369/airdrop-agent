# 🤖 AirdropAgent

> Autonomous multi-project agent to maximize your Web3 airdrop chances.
> Monitors Twitter, Telegram and Discord. Generates concrete actions. Notifies you on Discord and Telegram.

**By FuegoDev** — Open Source, Python, GitHub Actions.

---

## Why AirdropAgent?

The multi-wallet bot era is over. Web3 projects now reward **consistent, quality engagement** — relevant tweets, active Discord participation, regular community presence.

Tracking 3 to 5 projects simultaneously with this level of discipline is **impossible without a dedicated tool**.

AirdropAgent solves exactly that problem:

- 📡 **Continuous monitoring** of Twitter, Telegram and Discord for each tracked project
- 🧠 **AI analysis** of signals (quests, snapshots, major announcements)
- 🐦 **Generated tweets** ready to post, contextualized around each project's latest news
- 🔔 **Smart notifications** on Discord and/or Telegram
- 🤖 **Fully autonomous** via GitHub Actions — runs on its own, no server required

---

## Quick Architecture Overview

```
GitHub Actions (cron every 2h)
        │
        ▼
    agent.py (orchestrator)
        │
        ├── TwitterTracker   → tweets via Nitter (no API needed)
        ├── TelegramTracker  → channel messages via Telethon
        │
        ├── LLMEngine        → Groq API (free Llama 70B)
        │     ├── Signal classification (urgency 1-10)
        │     ├── Authentic tweet generation
        │     └── Daily briefing
        │
        ├── ContentEngine    → Action plan per project
        │
        └── Notifier         → Discord Webhook + Telegram Bot
                │
                ▼
        You (on your phone)
```

**DB Persistence**: SQLite uploaded/downloaded via **GitHub Artifacts** on every run.

---

## Installation & Deployment

### Prerequisites

- GitHub account
- Groq account (free) → https://console.groq.com
- Telegram bot (free) → see dedicated section
- Discord webhook (free) → see dedicated section

---

### Step 1 — Fork the repo

```
https://github.com/FuegoDev/airdrop-agent
```

Click **Fork** in the top right → you get your own copy of the repo.

---

### Step 2 — Configure the projects to track

Edit `config/settings.yaml` in your fork:

```yaml
projects:
  - name: "MONAD"
    twitter_handle: "monad_xyz"
    discord_invite: "monad"        # Part after discord.gg/
    telegram_handle: "monadxyz"
    chain: "monad-testnet"
    priority: 9                    # 1 (low) to 10 (critical)
    tags: ["L1", "testnet"]

  - name: "YOUR_PROJECT"
    twitter_handle: "twitter_handle"
    telegram_handle: "telegram_handle"
    priority: 8
```

Enable/disable notifications according to your preferences:

```yaml
notifications:
  discord:
    enabled: true          # ← false to disable Discord
    daily_brief: true
    action_suggestions: true

  telegram:
    enabled: true          # ← false to disable Telegram
    snapshot_alerts: true
```

---

### Step 3 — Get your Groq API key (free LLM)

1. Go to https://console.groq.com
2. Create a free account
3. Go to **API Keys** → **Create API Key**
4. Copy the key (starts with `gsk_...`)

> The free plan offers 14,400 requests/day — more than enough.

---

### Step 4 — Create the Telegram bot (to receive notifications)

1. Open Telegram → search for **@BotFather**
2. Send `/newbot`
3. Follow the instructions → you get a **token** (format `123456:ABCdef...`)
4. To get your **chat_id**:
   - Send a message to your bot
   - Open: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Look for `"chat":{"id": XXXXXXXXX}` — that's your chat_id

---

### Step 5 — Create the Discord Webhook

1. Open your Discord server
2. Go to **Channel Settings** → **Integrations** → **Webhooks**
3. Click **New Webhook**
4. Copy the **Webhook URL** (format `https://discord.com/api/webhooks/...`)

> You can create a dedicated Discord channel `#airdrop-agent` to receive notifications.

---

### Step 6 — Configure GitHub Secrets

This is the **critical step**. All your credentials are stored here — never in the code.

In your GitHub repo:
**Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these secrets one by one:

| Secret name | Value | Required |
|---|---|---|
| `GROQ_API_KEY` | Your Groq key `gsk_...` | ✅ Yes |
| `DISCORD_WEBHOOK` | Discord webhook URL | If Discord enabled |
| `TELEGRAM_BOT_TOKEN` | Bot token `123456:ABCdef...` | If Telegram enabled |
| `TELEGRAM_CHAT_ID` | Your numeric chat_id | If Telegram enabled |
| `TELEGRAM_API_ID` | Telegram API ID (Phase 3) | No (optional) |
| `TELEGRAM_API_HASH` | Telegram API Hash (Phase 3) | No (optional) |

> **Security**: GitHub Secrets are encrypted and never visible after creation. Never put them in your code or in settings.yaml.

---

### Step 7 — Enable GitHub Actions

1. In your repo → **Actions** tab
2. If a message asks you to enable workflows → click **I understand my workflows, go ahead and enable them**
3. The `AirdropAgent — Autonomous Run` workflow will appear in the list

**Immediate test**: Click the workflow → **Run workflow** → **Run workflow** (green button)
→ The agent launches manually for the first time.

---

### Step 8 — Verify everything is working

After the first run (2–3 minutes):

1. **Actions tab** → Click the run → Check the logs
2. **Your Discord** → You should receive notifications
3. **Your Telegram** → Same

If errors appear, see the **Troubleshooting** section below.

---

## Database Persistence (GitHub Artifacts)

### How it works

AirdropAgent uses a SQLite database (`data/agent.db`) to store:
- History of collected signals
- Generated actions
- Past runs and their statistics

On every GitHub Actions run:

```
Start of run
    │
    ▼
Download agent.db from Artifacts  ← Restore previous state
    │
    ▼
Run the agent (read + write DB)
    │
    ▼
Upload agent.db to Artifacts      ← Save new state
    │
    ▼
End of run
```

### Retrieving the DB locally (git pull equivalent)

To access the current state of the DB from Termux or your local machine:

**Method 1 — GitHub interface:**
1. **Actions** tab → Click the latest successful run
2. **Artifacts** section at the bottom of the page
3. Download `agent-db.zip` → unzip → you get `agent.db`

**Method 2 — GitHub CLI (gh) from Termux:**

```bash
# Install GitHub CLI
pkg install gh

# Authenticate
gh auth login

# Download the latest artifact
gh run download --name agent-db --dir data/
```

**Method 3 — Automated script:**
```bash
# scripts/sync_db.sh
#!/bin/bash
REPO="your-username/airdrop-agent"
RUN_ID=$(gh run list --repo $REPO --limit 1 --json databaseId -q '.[0].databaseId')
gh run download $RUN_ID --repo $REPO --name agent-db --dir data/
echo "DB synced from run #$RUN_ID"
```

### Retention period

Artifacts are kept for **90 days** by default (configurable in `agent.yml`).
After 90 days, the artifact is deleted, but the next run picks up from the last available one.

### GitHub free plan limits

| Resource | Free limit | AirdropAgent usage |
|---|---|---|
| Actions minutes/month | 2,000 min | ~10 min/run × 360 runs/month = ~600 min ✅ |
| Artifact storage | 500 MB | agent.db < 10 MB ✅ |

---

## Local Usage (Termux)

To test or run manually from Termux:

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/airdrop-agent.git
cd airdrop-agent

# Install dependencies
pip install -r requirements.txt

# Set environment variables locally
export GROQ_API_KEY="gsk_..."
export DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
export TELEGRAM_BOT_TOKEN="123456:ABCdef..."
export TELEGRAM_CHAT_ID="123456789"

# Run the agent
python -m core.agent
```

**For local usage with Ollama** (no internet connection required for the LLM):

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Download the Mistral model
ollama pull mistral

# Edit settings.yaml
# llm:
#   mode: "ollama"
```

---

## Adding / Editing Projects

**No code changes needed** — edit only `config/settings.yaml`:

```yaml
projects:
  - name: "NEW_PROJECT"
    twitter_handle: "handle"
    telegram_handle: "handle_tg"
    discord_invite: "xxx"     # What follows discord.gg/
    chain: "ethereum"
    priority: 7
    tags: ["DeFi", "L2"]
```

Commit and push → the next GitHub Actions run picks up the change automatically.

---

## Run Frequency

Modify the cron schedule in `.github/workflows/agent.yml`:

```yaml
schedule:
  - cron: '0 */2 * * *'    # Every 2 hours (default)
  - cron: '0 */4 * * *'    # Every 4 hours (lighter)
  - cron: '0 * * * *'      # Every hour (intensive)
  - cron: '0 8,14,20 * * *' # 3 times a day (8am, 2pm, 8pm UTC)
```

---

## Troubleshooting

### The agent runs but I receive nothing on Discord/Telegram

1. Verify that GitHub Secrets are properly configured (Settings → Secrets)
2. In `settings.yaml`, confirm `enabled: true` for the desired channel
3. Check that `urgency_threshold` isn't set too high (try `5` for testing)

### Error "GROQ_API_KEY missing"

The `GROQ_API_KEY` secret is not configured in GitHub Secrets.
See Step 6 of the installation guide.

### Tweets are not being retrieved (Nitter instances)

Public Nitter instances can be unstable. Solutions:
1. Check the instances listed in `settings.yaml` → `twitter.nitter_instances`
2. Find active instances at: https://status.d420.de
3. Replace offline instances in your config

### The DB does not persist between runs

Check that the `Save agent database` step in the workflow executed (even on failure, `if: always()` is configured). If the first run fails before writing the DB, the artifact won't exist — this is expected. The second run will create a fresh DB.

### Git push permission error

Verify that `permissions: contents: write` is present in `agent.yml`.

---

## Roadmap

- [x] **Phase 1** — Twitter tracker + LLM + Discord/Telegram notifications
- [x] **Phase 1** — GitHub Actions + Artifact persistence
- [ ] **Phase 2** — Full Telegram tracker (Telethon)
- [ ] **Phase 3** — Discord bot (channel reading)
- [ ] **Phase 3** — On-chain tracker (public RPCs)
- [ ] **Phase 4** — TGE Radar + Snapshot Engine
- [ ] **Phase 4** — Wallet scoring simulator
- [ ] **Phase 5** — Lightweight web interface (FastAPI)

---

## Contributing

PRs are welcome. This is a personal project first and foremost — test it, fork it, adapt it.

---

## License

MIT — Free to use, modify and distribute.

---

*AirdropAgent — FuegoDev*