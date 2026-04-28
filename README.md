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
┌──────────────────────┐                ┌──────────────────────────┐
│ Proxmox CT103        │                │ GitHub Actions safety net│
│ cron 6h00 Paris      │                │ daily.yml — 3h/4h/5h UTC │
│ → /opt/.../run.sh    │ (PRIMARY)      │ (fallback if CT103 down) │
└──────────┬───────────┘                └────────────┬─────────────┘
           │                                         │
           │           ┌──────────────────┐          │
           └──────────▶│  main.py runner  │◀─────────┘
                       │                  │
   ┌──────────────┐    │  1. fetch        │    ┌──────────────────┐
   │ Open-Meteo   │◀───┤     Open-Meteo   │    │ Telegram Bot API │
   │ (free, free) │    │  2. extract      │    │  sendMessage     │
   └──────────────┘    │     7 slots      │    └────────▲─────────┘
                       │  3. hail/jacket  │             │
                       │  4. load yest.   │             │
                       │  5. format HTML  │─────────────┘
                       │  6. send         │
                       │  7. save today   │       📱 Message received
                       └──────────┬───────┘
                                  │
                                  ▼
                       git commit + push data/YYYY-MM-DD.json
                       (acts as dedup signal for the safety net)
```

### Execution flow

1. **Primary path** — A system cron on **Proxmox CT103** (`0 6 * * *` with `CRON_TZ=Europe/Paris`) runs `/opt/260519-Weather/run.sh`, which loads `.env` and executes `main.py` directly. No queue, no orchestration: the message lands on Telegram within seconds of 6h00 Paris.
2. **Safety net** — Three GitHub Actions `schedule` crons (`0 3`, `0 4`, `0 5` UTC) fire `main.py` on a fresh runner. They only matter if CT103 is unreachable; on a normal day, the dedup file (`data/<today>.json`) committed by CT103 is already present in the checkout → the script exits silently.
3. **Guard** — `main.py` requires `datetime.now(Europe/Paris).hour ∈ {5, 6}` (filters off-window safety-net firings and absorbs GH Actions queue delays up to ~1h while keeping arrival ≤ 7h Paris). `FORCE_SEND=1` bypasses guard + dedup for manual runs.
4. Call Open-Meteo (hourly: temp, precipitation, cloud cover, weathercode, sunshine).
5. Extract 7 slots: **8h, 10h, 12h, 14h, 16h, 18h, 20h**.
6. Compute daily aggregates + hail heuristic + jacket recommendation.
7. Read `data/<yesterday>.json` if present → compute Δmin/Δmax.
8. Send Telegram message (HTML, `sendMessage`).
9. Write `data/<today>.json` and push (CT103: via `run.sh`; GH Actions: via the workflow's commit step).

## Stack

| Component | Choice | Why |
|---|---|---|
| Weather data | [Open-Meteo](https://open-meteo.com) | Free, no API key, reliable European coverage |
| Language | Python 3.11 (CT103) / 3.12 (GH Actions) / 3.9 (local) | Simplicity, `requests` ecosystem |
| Dependencies | `requests` only | Avoid bloat (`python-telegram-bot` replaced by direct POST) |
| Primary scheduler | Proxmox CT103 system cron | No queue → guarantees delivery within seconds of 6h00 |
| Safety-net scheduler | GitHub Actions cron | Free fallback if CT103 is down |
| Notification | Telegram Bot API | Existing bot reused from project `260418-Telegram` |
| Persistence | JSON committed to the repo (`data/`) | Survives the ephemeral GH runner; doubles as dedup signal |
| Secrets | `.env` on CT103 (chmod 600) · GitHub Secrets (safety net) · macOS Keychain (local) | No secret in code or git history |

## Architecture decisions

### Why CT103 as primary, GH Actions as fallback?

GitHub Actions queues `schedule` jobs and frequently delays them by 30–60 min — sometimes more. With a 6h00 Paris target and a 7h00 hard cutoff, that queue is the bottleneck (a real incident: alert delivered at 8h00 on 2026-04-28). Running `main.py` **directly** on CT103 removes the queue entirely: the message arrives within seconds of the cron firing.

GH Actions is kept as a free, zero-maintenance fallback for the days CT103 is unreachable.

### Dedup contract between CT103 and GH Actions

CT103 pushes `data/<today>.json` to `main` immediately after sending. The safety-net GH Actions jobs (which trail by 30–60 min) checkout the repo fresh, see the file, and exit silently. No double message, no shared lock needed — the git repo *is* the lock.

If CT103 fails, no file is pushed → the next safety-net firing in the 5h–6h Paris window sends the bulletin.

### Why a public repo?

No sensitive content in the code. Secrets are stored out-of-band (`.env` on CT103, GitHub Secrets for the safety net, macOS Keychain locally). *Secret scanning* + *push protection* are enabled.

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

CT103's cron header `CRON_TZ=Europe/Paris` makes `0 6 * * *` fire at exactly 6h00 Paris year-round (CET and CEST). No drift between summer and winter.

GitHub Actions ignores DST, so the safety net uses three UTC lines (`0 3`, `0 4`, `0 5`) — depending on the season, two of them fall in the valid Paris window (5h–6h) and one is filtered out by the guard. The 5h–6h window (rather than 6h–7h) leaves room for ~1h of queue delay while still arriving before 7h Paris.

### "Yesterday's data" persistence

GH Actions runners are ephemeral, so the daily JSON is **committed to `data/`**. Same on CT103 (via `run.sh`'s `git push`). Benefits:
- Simple, native, zero dependency
- Weather history browsable on GitHub
- No external storage
- The committed file doubles as the dedup signal between CT103 and the safety net

## Setup

### CT103 (primary)

```bash
# Clone on the host
ssh root@192.168.2.64 "cd /opt && gh repo clone barde333/260519-Weather"

# Drop the .env (chmod 600)
cat > /opt/260519-Weather/.env << EOF
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
EOF

# Cron line (CRON_TZ=Europe/Paris must be set at the top of the crontab)
0 6 * * * /opt/260519-Weather/run.sh >> /var/log/weather.log 2>&1
```

`run.sh` does: `git pull --rebase` → load `.env` → `python3 main.py` → commit + push `data/<today>.json`.

### GitHub Secrets (safety net)

In **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token (via [@BotFather](https://t.me/BotFather)) |
| `TELEGRAM_CHAT_ID` | Target chat/group ID |

### Local testing (macOS)

```bash
pip install requests

# Option A — environment variables
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy FORCE_SEND=1 python3 main.py

# Option B — macOS Keychain (automatic fallback)
security add-generic-password -a "$USER" -s telegram-bot-token -w "THE_TOKEN"
security add-generic-password -a "$USER" -s telegram-chat-id   -w "THE_CHAT_ID"
FORCE_SEND=1 python3 main.py
```

### Trigger a manual run on the safety net

GitHub UI: *Actions* tab → *Bulletin météo quotidien* → *Run workflow* (sets `FORCE_SEND=1`).

## Security

- No hardcoded secret in the code or git history
- `.env` on CT103 is `chmod 600`, owned by `root`, never committed (`.gitignore`)
- *Secret scanning* + *push protection* enabled on the repo
- The Telegram bot only sends to the configured `chat_id` (no inbound message listening)

## License

Personal use.
