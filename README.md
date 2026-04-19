# 260519-Weather — Bulletin météo quotidien · Saint-Ismier

Envoie chaque matin à 7h (heure de Paris) un bulletin météo Telegram pour Saint-Ismier,
via [Open-Meteo](https://open-meteo.com/) (gratuit, sans clé API) et un bot Telegram existant.

Fonctionne sur **GitHub Actions** (cron), sans serveur ni Docker.

## Exemple de message

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

## Setup GitHub Secrets

Dans **Settings → Secrets and variables → Actions**, ajouter :

| Secret | Valeur |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token du bot (ex. `123456:ABC-DEF…`) |
| `TELEGRAM_CHAT_ID` | ID du chat/groupe destinataire |

## Persistance

Chaque run sauvegarde un fichier `data/YYYY-MM-DD.json` dans le repo (commit automatique).
Cela permet la comparaison avec la veille et constitue un historique météo consultable sur GitHub.

## Test local

```bash
pip install requests
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python3 main.py
```

Sans les variables d'env, le script tente un fallback sur le Keychain macOS
(service `meteo_telegram`, comptes `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID`).
