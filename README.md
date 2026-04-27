# 260519-Weather — Daily Weather Bulletin via Telegram

> An automated message every morning at **6:00 AM** Paris time with everything needed to choose what to wear and whether the day carries a risk of thunderstorm or hail in Saint-Ismier (38330, Isère, France).

## Problem solved

Opening a weather app every morning is friction: launch the app, navigate multiple screens, synthesize the information yourself. This project **pushes** the relevant data, pre-digested, at the right moment (on waking). The criteria that matter for this specific user:

- Min/max temperature and hourly slots to pick clothing
- Total sunshine duration
- Cumulative rainfall
- Hail risk (graduated, no jargon)
- Comparison with yesterday (to know whether to dress differently)

## Sample message

```
🌤️ Météo Saint-Ismier — dimanche 19 avril
🦺 Gilet / veste blanche aujourd'hui (13–22°C)
☀️ Ensoleillement : 11h52
🌧️ Pluie totale : 0.3 mm
🧊 Risque de grêle : XS

⏰ Créneaux :
08h — 14°C | ⛅ 99% | 💧 0mm
10h — 17°C | 🌤️ 63% | 💧 0mm
12h — 20°C | 🌤️ 33% | 💧 0mm
14h — 22°C | 🌤️ 45% | 💧 0mm
16h — 22°C | 🌤️ 96% | 💧 0mm
18h — 22°C | 🌤️ 24% | 💧 0mm
20h — 20°C | ⛅ 38% | 💧 0mm

📊 vs hier : Max +2.1°C | Min -0.5°C
```

## Architecture

```
┌─────────────────┐  gh workflow run   ┌──────────────────────────┐
│ Proxmox CT103   │───────────────────▶│ GitHub Actions           │
│ cron 6h Paris   │  (primary trigger) │ daily.yml                │
└─────────────────┘                    └────────────┬─────────────┘
                                                    │
┌─────────────────┐  5h/6h Paris       ┌────────────▼─────────────┐
│ GH Actions cron │───────────────────▶│ main.py (runner)         │
│ (safety net)    │                    │                           │
└─────────────────┘                    │  1. fetch Open-Meteo      │
                                       │  2. extract 7 slots +     │
                ┌──────────────────┐   │     aggregates            │
                │  Open-Meteo API  │◀──┤  3. compute hail, jacket  │
                │  (free, no key)  │   │  4. load yesterday        │
                └──────────────────┘   │     (data/*.json)         │
                                       │  5. format HTML           │
                ┌──────────────────┐   │  6. send message          │
                │ Telegram Bot API │◀──┤  7. save today            │
                └──────────────────┘   └────────────┬─────────────┘
                        │                           │
                        ▼                           ▼
                  📱 Message received      git commit + push
                                          (data/YYYY-MM-DD.json)
```

### Execution flow

1. A system cron on **Proxmox CT103** fires `gh workflow run daily.yml` at **6h00 Paris** (primary trigger). Three GitHub Actions `schedule` crons (`0 3`, `0 4`, `0 5` UTC) act as a **safety net** that always provides at least one valid firing window per season between 5h and 6h Paris.
2. The script checks that the Paris hour is **5 or 6** — otherwise it exits silently (prevents out-of-window runs and absorbs GH Actions queue delays up to ~1h while keeping arrival ≤ 7h Paris). A dedup file (`data/<today>.json`) ensures only one run actually sends. A manual run (`workflow_dispatch`) bypasses both via `FORCE_SEND=1`.
3. Call Open-Meteo (hourly: temp, precipitation, cloud cover, weathercode, sunshine) for the day.
4. Extract 7 slots: **8h, 10h, 12h, 14h, 16h, 18h, 20h**.
5. Compute daily aggregates + hail heuristic + jacket recommendation.
6. Read `data/<yesterday>.json` if present → compute Δmin/Δmax.
7. Send Telegram message (HTML, `sendMessage`).
8. Write `data/<today>.json` + auto-commit to the repo.

## Stack

| Component | Choice | Why |
|---|---|---|
| Weather data | [Open-Meteo](https://open-meteo.com) | Free, no API key, reliable European coverage |
| Language | Python 3.12 (runner) / 3.9 (local) | Simplicity, `requests` ecosystem |
| Dependencies | `requests` only | Avoid bloat (`python-telegram-bot` replaced by direct POST) |
| Scheduling | GitHub Actions cron | Free, zero infrastructure, no 24/7 server |
| Notification | Telegram Bot API | Existing bot reused from project `260418-Telegram` |
| Persistence | JSON committed to the repo (`data/`) | Ephemeral runner → auto-commit; bonus: public history |
| Secrets | GitHub Secrets (prod) · macOS Keychain (local) | No secret in code, repo is safely public |

## Architecture decisions

### Why GitHub Actions and not Docker/server?

This project is a 10-second daily cron with no web service. A Docker container on a 24/7 server would be **overkill**. GitHub Actions provides:
- An on-demand free runner
- A built-in cron scheduler
- Native secret management
- Zero infrastructure to maintain

Docker would make sense if there were an HTTP API, a dashboard, or a long-running process.

### Why a public repo?

No sensitive content in the code. Secrets (bot token, chat_id) are in **GitHub Secrets**, never committed. *Secret scanning* + *push protection* are enabled. Benefits: visible weather history, transparency, reusable by others.

### Hail heuristic (XS/S/L/XL, no M)

Open-Meteo does not provide a direct "hail forecast". It is **derived from WMO codes**:

| Size | Condition |
|---|---|
| **XL** | Code 99 present (thunderstorm with heavy hail) |
| **L** | Code 96 (slight hail) **or** code 95 + precip > 5 mm/h on any slot |
| **S** | Code 95 (thunderstorm) **or** precip > 2 mm/h on any slot |
| **XS** | None of the above |

An honest proxy — not a professional forecast, but sufficient to decide whether to cancel a barbecue.

### Jacket recommendation

| Average temp (min+max)/2 | Jacket |
|---|---|
| < 10°C | 🧥 Purple coat |
| 10–20°C | 🦺 White vest / jacket |
| > 20°C | None |

Personal logic tailored to the recipient's wardrobe — not a generic rule.

### DST handling

The primary trigger is a **system cron on Proxmox CT103** (`0 6 * * *` with `CRON_TZ=Europe/Paris`), which always fires at exactly 6h00 Paris regardless of DST — this eliminates the UTC/DST problem entirely.

The GitHub Actions `schedule` is a **safety net only**. Because GitHub Actions ignores DST, three UTC cron lines (`0 3`, `0 4`, `0 5`) run year-round; depending on the season, two of them fall in the valid Paris window (5h–6h) and one is filtered out by the script's guard (`datetime.now(Europe/Paris).hour in (5, 6)`). The dedup file (`data/<today>.json`) ensures only one message is sent even if multiple triggers fire. The window is intentionally set to 5h–6h Paris (not 6h–7h) so that even with GH Actions queue delays of up to ~1h, the alert arrives **before 7h Paris year-round**.

### "Yesterday's data" persistence

The GitHub Actions runner is ephemeral — impossible to keep a file between two runs without an artifact. Solution: **auto-commit** the daily JSON to `data/` via `GITHUB_TOKEN` (permission `contents: write`). Benefits:
- Simple, native, zero dependency
- Weather history browsable on GitHub
- No external storage to manage

## Setup

### GitHub Secrets

In **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token (via [@BotFather](https://t.me/BotFather)) |
| `TELEGRAM_CHAT_ID` | Target chat/group ID |

### Local testing (macOS)

```bash
pip install requests

# Option A — environment variables
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python3 main.py

# Option B — macOS Keychain (automatic fallback)
security add-generic-password -a "$USER" -s telegram-bot-token -w "THE_TOKEN"
security add-generic-password -a "$USER" -s telegram-chat-id   -w "THE_CHAT_ID"
python3 main.py
```

### Trigger a manual run

Via the GitHub UI: *Actions* tab → *Bulletin météo quotidien* → *Run workflow*.

## Security

- No hardcoded secret in the code or git history
- *Secret scanning* + *push protection* enabled on the repo
- The Telegram bot only sends to the configured `chat_id` (no inbound message listening)

## License

Personal use.
