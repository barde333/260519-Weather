# 260519-Weather — Daily Weather Bulletin via Telegram

> An automated message every morning at **6:00, 6:30 or 7:00 AM** Paris time (3 attempts 30 min apart) with everything needed to choose what to wear and whether the day carries a risk of thunderstorm or hail in Saint-Ismier (38330, Isère, France).

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
┌─────────────────┐ cron 4h/4h30/5h UTC ┌──────────────────────┐
│ GitHub Actions  │────────────────────▶│ main.py (runner)     │
│ (daily.yml)     │                     │                      │
└─────────────────┘                     │  1. fetch Open-Meteo │
                                        │  2. extract 7        │
                ┌──────────────────────┐│     slots + aggreg. │
                │   Open-Meteo API     │◀┤  3. compute hail,   │
                │ (free, no key)       │ │     jacket          │
                └──────────────────────┘ │  4. load yesterday  │
                                         │     (data/*.json)   │
                ┌──────────────────────┐ │  5. format HTML     │
                │  Telegram Bot API    │◀┤  6. send message    │
                └──────────────────────┘ │  7. save today      │
                         │               └──────────────────────┘
                         ▼                          │
                   📱 Message received              ▼
                                          git commit + push
                                          (data/YYYY-MM-DD.json)
```

### Execution flow

1. GitHub Actions triggers the workflow at 4h00, 4h30 **and** 5h00 UTC (triple cron 30 min apart → 6h00 / 6h30 / 7h00 Paris in summer, 5h00 / 5h30 / 6h00 in winter).
2. The script checks that the Paris hour is **6 or 7** — otherwise it exits silently (prevents out-of-window runs). A dedup file (`data/<today>.json`) ensures only the first of the three attempts actually sends. A manual run (`workflow_dispatch`) bypasses both via `FORCE_SEND=1`.
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

GitHub Actions cron runs **in UTC**. The target delivery window is **6h00 / 6h30 / 7h00 Paris** (3 attempts 30 min apart, because GitHub Actions sometimes delays or skips scheduled runs):

| Paris time | UTC summer | UTC winter |
|---|---|---|
| 6h00 | 4h00 UTC | 5h00 UTC |
| 6h30 | 4h30 UTC | 5h30 UTC |
| 7h00 | 5h00 UTC | 6h00 UTC |

Solution: **triple cron** (4h00, 4h30, 5h00 UTC) + a guard that checks `datetime.now(Europe/Paris).hour in (6, 7)` (else silent exit), plus a dedup on `data/<today>.json` so only the first successful attempt sends. A manual `workflow_dispatch` run sets `FORCE_SEND=1` and bypasses both. Simple, robust, no third-party library.

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
