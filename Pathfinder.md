# Pathfinder — Bulletin météo quotidien Telegram (Saint-Ismier)

Base : script Python autonome, exécuté par **GitHub Actions** (cron quotidien 7h heure de Paris), récupère la météo via **Open-Meteo**, envoie un message **Telegram** via le bot existant (`260418-Telegram`). Repo **public** `260519-Weather`. Pas de Docker. **S'inspire d'un script antérieur** (`meteo.py`, Google Drive) — structure, WMO codes, créneaux horaires et recommandation veste repris ; heuristique grêle simplifiée ; persistance adaptée à GitHub Actions ; lib Telegram allégée.

## Données récupérées (Open-Meteo forecast API)

- Coordonnées Saint-Ismier : 45.24°N, 5.82°E — `timezone=Europe/Paris`, `forecast_days=1`.
- *Hourly* : `temperature_2m`, `precipitation`, `cloudcover`, `weathercode`, `sunshine_duration`.
- Créneaux extraits : **8h, 10h, 12h, 14h, 16h, 18h, 20h**.
- Agrégats journaliers calculés côté script : `temp_min`, `temp_max`, `precipitation_sum`, `sunshine_hours`.

## Heuristique grêle (basée sur les codes WMO)

| Taille | Condition |
|---|---|
| **XL** | code 99 présent (orage avec grêle dense) |
| **L**  | code 96 (grêle légère) **ou** code 95 + précipitations > 5 mm/h sur un créneau |
| **S**  | code 95 (orage) **ou** précipitations > 2 mm/h sur un créneau |
| **XS** | aucune des conditions ci-dessus |

Reprend la logique de `meteo.py` ; pas de M par design (demande utilisateur).

## Recommandation de veste (repris de `meteo.py`)

| Temp moyenne (min+max)/2 | Veste |
|---|---|
| < 10°C | 🧥 Manteau violet |
| 10–20°C | 🦺 Gilet / veste blanche |
| > 20°C | Aucune |

## Format du message Telegram (HTML)

```
🌤️ Météo Saint-Ismier — lundi 20 avril
🧥 Gilet blanc aujourd'hui (8–19°C)
☀️ Ensoleillement : 8h20
🌧️ Pluie totale : 2.4 mm
🧊 Risque de grêle : S

⏰ Créneaux :
08h — 9°C  | ☀️ 15%  | 💧 0mm
10h — 13°C | 🌤️ 30% | 💧 0mm
...
20h — 14°C | ☁️ 70% | 💧 1mm

📊 vs hier : Max +2.1°C | Min -0.5°C
```

## Persistance "données de la veille" sur GitHub Actions

Le runner est éphémère → stocker les JSON quotidiens **dans le repo** (`data/YYYY-MM-DD.json`) et **commit auto** en fin de run (via `git config` + `git push` avec `GITHUB_TOKEN`). Bonus : historique météo consultable sur GitHub.

## Partie A — Script Python

| # | Statut | Description |
|---|---|---|
| 1 | ✅ | Table `WEATHER_CODES` WMO, constantes, structure `main()` — fichier `main.py` |
| 2 | ✅ | `fetch_meteo()` : appel Open-Meteo avec `sunshine_duration` |
| 3 | ✅ | `extract_hourly_data()` : 7 créneaux + agrégats journaliers (min/max, sunshine_hours, precip_sum) |
| 4 | ✅ | `get_hail_risk()` : codes WMO 95/96/99 + précipitations → XS/S/L/XL |
| 5 | ✅ | `get_jacket_recommendation()` : moyenne (min+max)/2 → violet/blanc/rien |
| 6 | ✅ | `build_telegram_message()` : HTML, mois FR, jour FR, créneaux, vs hier — **bug mois EN corrigé** |
| 7 | ✅ | `send_telegram()` via `requests` POST sendMessage |
| 8 | ✅ | `get_secrets()` : env vars → fallback Keychain macOS (service `meteo_telegram`) |
| 9 | ✅ | `load_yesterday()` / `save_today()` : JSON dans `data/YYYY-MM-DD.json` |
| 10 | ✅ | `send_alert()` + `main()` avec gestion d'erreurs → alerte Telegram si crash |
| 11 | ✅ | Test local end-to-end réussi (API réelle Open-Meteo, message formaté correct) |

## Partie B — Déploiement GitHub Actions

| # | Statut | Description | Modèle | Tokens |
|---|---|---|---|---|
| 12 | ✅ | `.gitignore` : `.venv/`, `__pycache__/`, `.DS_Store`, `.meteo_secrets` | — | — |
| 13 | ✅ | `requirements.txt` : `requests` uniquement | — | — |
| 14 | ✅ | `.github/workflows/daily.yml` : double cron `0 5/6 * * *`, checkout, pip install, run, commit auto `data/` | — | — |
| 15 | ✅ | `permissions: contents: write` dans le workflow | — | — |
| 16 | ✅ | Audit secrets en dur : aucun token/ID trouvé dans le code | — | — |
| 17 | ✅ | `README.md` : description, exemple de message, setup GitHub Secrets, test local | — | — |
| 18 | ✅ | `git init` + premier commit (`main`) | — | — |
| 19 | ✅ | Repo `barde333/260519-Weather` créé sur GitHub, `gh` CLI v2.90 dispo | — | — |
| 20 | ✅ | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` ajoutés dans Secrets (runs OK depuis 2026-04-19) | — | — |
| 21 | ✅ | Run manuel `workflow_dispatch` validé | — | — |
| 22 | ✅ | Secret scanning + push protection actifs (défaut repos publics, vérifié via `gh api`) | — | — |

## Partie C — Fiabilisation trigger (cron externe Proxmox)

Problème : les `schedule` GitHub Actions sont best-effort et régulièrement skippés sous charge (cas du 2026-04-23, aucun des 3 créneaux n'a tourné). Solution : un cron système sur un CT Proxmox existant appelle l'API GitHub `workflow_dispatch` à 6h Paris. Le workflow reste inchangé.

| # | Statut | Description | Modèle | Tokens |
|---|---|---|---|---|
| 23 | ✅ | CT 103 : `gh` v2.91 installé + authentifié (token Mac réutilisé, scope `workflow`), `gh workflow list` OK | Opus | 2k |
| 24 | ✅ | CT 103 crontab : `CRON_TZ=Europe/Paris` + `0 6 * * * gh workflow run daily.yml -R barde333/260519-Weather` | Sonnet | 2k |
| 25 | ✅ | Workflow réduit à 1 seul `schedule: 0 6 UTC` en filet + `workflow_dispatch` | Sonnet | 1k |

Total Partie C ≈ **5k tokens**.

## Blocages connus

- **`gh` CLI absent** : ni `gh` ni `brew` disponibles sur cette machine. Les étapes 19-22 doivent être faites manuellement sur GitHub ou après installation de `gh` (`brew install gh` ou [cli.github.com](https://cli.github.com)).
- **Python système 3.9** : `pip3 install requests` a fonctionné mais avec avertissements SSL (LibreSSL). Le runner GitHub Actions utilisera Python 3.12 (configuré dans le workflow) — pas de problème en prod.

## Décisions d'architecture retenues

- **GitHub Actions plutôt que Docker/Proxmox** : cron quotidien 10s, pas de service web.
- **Repo public** : aucun secret dans le code, tout via GitHub Secrets.
- **Open-Meteo** : gratuit, pas de clé API.
- **Grêle = codes WMO 95/96/99 + précipitations** (simplification vs heuristique CAPE initialement envisagée ; repris de `meteo.py`).
- **Veste violet/blanc/rien** : feature reprise de l'ancien script.
- **Créneaux 8-20h** : repris de `meteo.py` (7 créneaux pairs).
- **`requests` direct pour Telegram** (pas `python-telegram-bot`) — cohérent avec `260418-Telegram`.
- **Persistance veille = commit auto dans `data/`** — contourne l'éphémérité du runner, historique bonus.
- **DST** : double cron UTC (5h + 6h) + garde `datetime.now(Europe/Paris).hour == 7` → sortie silencieuse sinon.
- **Zéro coût tokens Claude** en runtime.

Total estimé : Partie A ≈ 3800 tokens, Partie B ≈ 2600 tokens. Sonnet suffit.
