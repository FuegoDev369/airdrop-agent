# 🤖 AirdropAgent

> Autonomous multi-project agent to maximize your Web3 airdrop chances.
> Monitors Twitter, Telegram, and Discord. Generates actionable insights. Notifies via Discord and Telegram.

**By FuegoDev** — Open Source · Python · GitHub Actions

---

## Why AirdropAgent?

The era of multi-wallet bots is over. Web3 projects now reward **consistent, qualitative engagement** — relevant tweets, active Discord participation, regular community presence.

Tracking 3 to 5 projects simultaneously with this level of rigor is **impossible without a dedicated tool**.

AirdropAgent solves exactly this problem:

- 📡 **Continuous monitoring** of Twitter, Telegram, and Discord for each tracked project
- 🧠 **AI-powered signal analysis** — quests, snapshots, major announcements
- 🐦 **Generated tweets** ready to post, contextualized on the project's latest activity
- 🔔 **Smart notifications** delivered to Discord and/or Telegram
- 📊 **TGE Radar** — detects pre-launch signals before the crowd reacts
- 📅 **Snapshot Engine** — eligibility alerts with actionable checklists
- 💼 **Wallet Scorer** — estimates your on-chain position in the airdrop distribution
- 🤖 **Fully autonomous** via GitHub Actions — runs every 2 hours, no server required

---

## Architecture

```
GitHub Actions (cron every 2h)
        │
        ▼
    agent.py (orchestrator)
        │
        ├── TwitterTracker   → tweets via public Nitter instances (no API key)
        ├── TelegramTracker  → project channel messages via Telethon official API
        ├── DiscordTracker   → channel messages via HTTP REST API (optional)
        │
        ├── LLMEngine        → Groq API (Llama 3.3 70B — free tier)
        │     ├── Batch signal classification (1 call per project)
        │     ├── Authentic EN tweet generation
        │     ├── Wallet eligibility scoring
        │     └── Daily briefing
        │
        ├── TGERadar         → TGE probability score (0-100) from signal patterns
        ├── SnapshotEngine   → eligibility checklist + timing estimation
        ├── WalletScorer     → on-chain activity analysis via public RPCs
        ├── ContentEngine    → action plans per project
        │
        └── Notifier         → Discord Webhook + Telegram Bot
                │
                ▼
        You (on your phone)
```

**DB Persistence**: SQLite uploaded/downloaded via **GitHub Artifacts** on every run.

---

## Security Model

```
settings.yaml  (PUBLIC on GitHub)
  → Project names, Twitter/Telegram handles, Discord channels,
    priorities, tags, thresholds, frequencies
  → NEVER put secrets, API keys, or wallet addresses here

.env  (LOCAL on Termux — never pushed to GitHub)
  → All API keys + WALLET_ADDRESSES
  → Copied from .env.example

GitHub Secrets  (PRIVATE — encrypted by GitHub)
  → Same values as .env but for GitHub Actions runs
```

---

## Full Installation & Deployment

### Prerequisites

- GitHub account
- Free Groq account → https://console.groq.com
- Telegram account
- Discord account (optional — for Discord tracking)

---

### Step 1 — Fork the Repository

```
https://github.com/FuegoDev/airdrop-agent
```

Click **Fork** → you get your own copy of the repo.

---

### Step 2 — Configure Your Projects

Edit `config/settings.yaml`:

```yaml
projects:
  - name: "PROJECT_NAME"
    twitter_handle: "twitter_handle"      # Without @
    telegram_handle: "telegram_handle"    # Without @, leave "" if none
    discord_guild_id: 1234567890123456789 # Numeric server ID (0 if not configured)
    discord_channels:
      - "announcements"
      - "general"
    website_url: "https://project.xyz"
    chain: "ethereum"
    tge_date: null                         # Format: "2026-12-01" or null
    priority: 9                            # 1 (low) to 10 (critical)
    tags: ["L1", "testnet"]
```

> ⚠️ **Never put wallet addresses or API keys in this file.** It is public on GitHub.

---

### Step 3 — Groq API Key (Free LLM)

1. Go to https://console.groq.com → create a free account
2. **API Keys** → **Create API Key**
3. Copy the key (starts with `gsk_...`)

> Free tier: 14,400 requests/day — more than enough.

---

### Step 4 — Telegram Bot (Notifications)

**Create the bot to receive notifications:**

1. Open Telegram → search **@BotFather**
2. Send `/newbot` → follow the instructions
3. Copy the **token** (format: `123456:ABCdef...`)

**Get your chat_id:**

1. Send any message to your bot
2. Open: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Find `"chat":{"id": XXXXXXXXX}` → that's your chat_id

---

### Step 5 — Telegram API (Track Project Channels)

To let the agent **read Telegram channels of tracked projects**:

**5.1 — Create an app on my.telegram.org:**

1. Go to **https://my.telegram.org**
2. Log in with your Telegram phone number
3. Click **API development tools**
4. Fill in the form:
   - **App title**: `AirdropAgent`
   - **Short name**: `airdropagent`
   - **Platform**: Other
5. Click **Create application**
6. Copy **App api_id** and **App api_hash**

**5.2 — Generate SESSION_STRING (one-time only):**

```bash
pip install telethon
python scripts/generate_session.py
```

The script will:
- Ask for your `API_ID` and `API_HASH`
- Send a verification code to your Telegram account
- Display the `SESSION_STRING` to copy

> The SESSION_STRING never expires unless you manually log out.

---

### Step 6 — Wallet Scorer Setup

The Wallet Scorer analyzes your on-chain activity to estimate your airdrop position.

**Security rule**: wallet addresses are **never stored in `settings.yaml`** (public file).
They are only read from environment variables.

**For GitHub Actions** → add to GitHub Secrets:
```
WALLET_ADDRESSES = 0xYourAddress1,0xYourAddress2
```

**For local Termux usage** → add to your `.env` file:
```bash
cp .env.example .env
# Edit .env and fill in WALLET_ADDRESSES
```

> Addresses are always masked in logs: `0x1234...5678` — never displayed in full.

---

### Step 7 — GitHub Secrets Configuration

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Description | Required |
|---|---|---|
| `GROQ_API_KEY` | Groq API key (`gsk_...`) | ✅ Yes |
| `DISCORD_WEBHOOK` | Discord Webhook URL (notifications) | If Discord notifications |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token (notifications) | If Telegram notifications |
| `TELEGRAM_CHAT_ID` | Your Telegram chat_id | If Telegram notifications |
| `TELEGRAM_API_ID` | Telegram app ID (my.telegram.org) | For Telegram tracking |
| `TELEGRAM_API_HASH` | Telegram app hash | For Telegram tracking |
| `TELEGRAM_SESSION_STRING` | Generated by generate_session.py | For Telegram tracking |
| `WALLET_ADDRESSES` | Comma-separated wallet addresses | For Wallet Scorer |

> **Security**: GitHub Secrets are encrypted at rest. Never put these values in code files.

---

### Step 8 — Enable GitHub Actions

1. Go to the **Actions** tab of your repo
2. If prompted → click **I understand my workflows, enable them**
3. The `AirdropAgent — Autonomous Run` workflow appears in the list

**Immediate test**: click **Run workflow** → **Run workflow** (green button)

---

### Step 9 — Verify the First Run

After 2-3 minutes:

1. **Actions tab** → running job → check logs
2. **Telegram** → you should receive the run summary
3. **Discord** → same if webhook is configured

Expected logs on a clean first run:
```
TelegramTracker : ✅ enabled
DiscordTracker  : ⏸  disabled (DISCORD_USER_TOKEN missing)
WalletScorer    : ✅ 1 wallet(s) loaded : ['0x1234...5678']
Run #1 started
--- MY_PROJECT ---
  Sources → Twitter: @handle | Telegram: @handle | Discord: N/A
MY_PROJECT Twitter  : 15 new, 0 duplicates
MY_PROJECT Telegram : 12 new, 0 duplicates
Batch classified: 27 signals in 1 LLM call
TGE Radar — MY_PROJECT : score 35/100 [medium]
Run completed — new: 27 | duplicates: 0 | actions: 2 | notifs: 5 | status: success
```

---

## DB Persistence (GitHub Artifacts)

On every GitHub Actions run:

```
Run starts
    │
    ▼
Search for latest agent-db artifact via GitHub API
    │
    ▼
Download agent.db → restore previous state
    │
    ▼
Agent runs (reads + writes DB)
    │
    ▼
Upload updated agent.db to Artifacts (overwrite)
    │
    ▼
Run ends
```

**Download DB locally from Termux:**

```bash
# Install GitHub CLI
pkg install gh

# Authenticate
gh auth login

# Download latest artifact
gh run download --name agent-db --dir data/
```

**Retention**: artifacts are kept for **90 days** (configurable in `agent.yml`).

**GitHub Free tier limits**:
| Resource | Free limit | AirdropAgent usage |
|---|---|---|
| Actions minutes/month | 2,000 min | ~10 min/run × 360 runs = ~600 min ✅ |
| Artifact storage | 500 MB | agent.db < 10 MB ✅ |

---

## Adding / Modifying Projects

Edit only `config/settings.yaml` — no code changes needed.

```yaml
projects:
  - name: "NEW_PROJECT"
    twitter_handle: "handle"
    telegram_handle: "tg_handle"
    discord_guild_id: 1234567890
    discord_channels:
      - "announcements"
      - "alpha"
    chain: "ethereum"
    priority: 8
    tags: ["DeFi", "L2"]
```

Commit + push → the next run picks up the changes automatically.

**Remove a project**: delete it from the file. The agent will automatically deactivate it in DB on the next run (bidirectional sync).

---

## Notification Configuration

In `settings.yaml`:

```yaml
notifications:
  discord:
    enabled: true           # false to disable
    mention_on_urgent: true # @everyone if urgency >= 9

  telegram:
    enabled: true
    snapshot_alerts: true   # Snapshot/TGE imminent alerts

  urgency_threshold: 7      # Min score (1-10) to trigger notification

language:
  tweet_language: "en"              # Always English — do not change
  notification_language: "fr"       # "en" | "fr" | "es"
```

---

## TGE Radar

The TGE Radar scans all signals from the last 48 hours and computes a 0-100 probability score for an imminent TGE or snapshot.

**Detected patterns and weights:**

| Pattern | Weight | Keywords |
|---|---|---|
| Launch date mentioned | +30 | "launch date", "goes live", "this month"... |
| CEX listing detected | +25 | "listing", "binance", "coinbase", "bybit"... |
| Tokenomics published | +25 | "tokenomics", "token distribution", "vesting"... |
| Snapshot mentioned | +30 | "snapshot", "eligible", "criteria", "claim"... |
| Smart contract audit | +20 | "audit", "certik", "hacken", "audited"... |
| Urgency signals | +20 | "last chance", "deadline", "ends soon"... |

**Alert levels:**
- Score ≥ 70 → 🔴 **CRITICAL** — immediate action required
- Score ≥ 50 → 🟠 **HIGH** — prioritize engagement
- Score ≥ 30 → 🟡 **MEDIUM** — stay alert
- Score < 30 → 🟢 **LOW** — normal monitoring

---

## Wallet Scorer

Analyzes your wallet's on-chain activity via free public RPCs:

**Supported chains**: Ethereum, Arbitrum, Optimism, Base, Polygon, BNB Chain, Avalanche

**Scoring factors**: transaction count, native balance, and LLM-based contextual analysis.

**Scoring runs**: automatically every morning between 6:00–9:00 UTC with the daily briefing.

**Setup** (never in settings.yaml):
```bash
# GitHub Secrets (production)
WALLET_ADDRESSES=0xAddress1,0xAddress2

# .env (local Termux development)
WALLET_ADDRESSES=0xAddress1,0xAddress2
```

---

## Run Frequency

Modify the cron in `.github/workflows/agent.yml`:

```yaml
schedule:
  - cron: '0 */2 * * *'      # Every 2 hours (default)
  - cron: '0 */4 * * *'      # Every 4 hours (conservative)
  - cron: '0 8,14,20 * * *'  # 3x/day: 8am, 2pm, 8pm UTC
```

---

## Local Usage (Termux)

```bash
git clone https://github.com/YOUR_USERNAME/airdrop-agent.git
cd airdrop-agent

pip install -r requirements.txt

# Copy and fill the environment file
cp .env.example .env
# Edit .env with your values

# Load environment variables
source .env

# Run the agent
python -m core.agent
```

**Using Ollama locally (no internet required for LLM):**

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull the model
ollama pull mistral

# Switch in settings.yaml
# llm:
#   mode: "ollama"
```

---

## Troubleshooting

### No notifications received

1. Verify GitHub Secrets are correctly set (Settings → Secrets)
2. Check `enabled: true` for the desired channel in `settings.yaml`
3. Lower `urgency_threshold` to `5` to test
4. Verify your projects have `twitter_handle` and/or `telegram_handle` filled in

### Telegram: "Session not authorized"

The `TELEGRAM_SESSION_STRING` has expired or is invalid. Regenerate it:
```bash
python scripts/generate_session.py
```

### Nitter instances down (Twitter)

Find active instances at: https://status.d420.de
Update `twitter.nitter_instances` in `settings.yaml`.

### 429 Too Many Requests (Groq)

Increase `request_delay_seconds` in `settings.yaml`:
```yaml
llm:
  groq:
    request_delay_seconds: 2.0
```

### Artifact not found on first run

Normal behavior — the artifact doesn't exist yet on the very first run. The DB will be created fresh and uploaded at the end. From run #2 onward, the DB is restored correctly.

### Project still tracked after removal from settings.yaml

The agent performs bidirectional sync on every run. If a project disappears from `settings.yaml`, it is automatically deactivated in DB on the next run. You will see in the logs:
```
Sync projects: 2 active | deactivated: ['OLD_PROJECT']
```

---

## Roadmap

- [x] Phase 1 — Twitter + LLM + Notifications + DB Persistence + GitHub Actions
- [x] Phase 2 — Signal Deduplication + Batch LLM + Telegram Tracker
- [x] Phase 3 — Discord Tracker (HTTP API)
- [x] Phase 4 — TGE Radar + Snapshot Engine + Wallet Scorer
- [ ] Phase 5 — Lightweight web UI (non-technical users)
- [ ] Phase 6 — On-chain transaction tracker (bridge activity, protocol interactions)
- [ ] Phase 7 — Multi-wallet portfolio view

---

## Contributing

PRs are welcome. This is a personal project first — test it, fork it, adapt it.

If you find a bug or have a feature idea, open an issue on GitHub.

---

## License

MIT — Free to use, modify, and distribute.

---

*AirdropAgent — FuegoDev*
