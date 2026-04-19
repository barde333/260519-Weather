# 260519-Weather — Bulletin météo quotidien Telegram

> Un message automatique chaque matin à 7h (Paris) pour savoir comment s'habiller et si la journée présente un risque d'orage/grêle à Saint-Ismier (38330, Isère).

## Problème résolu

Consulter une appli météo chaque matin est une friction : il faut ouvrir l'app, lire plusieurs écrans, synthétiser. On veut l'info **poussée**, pré-digérée, au moment où elle est utile (au réveil). Les critères utiles *pour cette personne* :

- Température min/max et créneaux de la journée pour choisir les vêtements
- Durée d'ensoleillement totale
- Pluie cumulée
- Risque de grêle (gradué, sans jargon)
- Comparaison avec la veille (pour savoir si on s'habille différemment)

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

## Architecture

```
┌─────────────────┐   cron 5h+6h UTC    ┌──────────────────────┐
│ GitHub Actions  │────────────────────▶│ main.py (runner)     │
│ (daily.yml)     │                     │                      │
└─────────────────┘                     │  1. fetch Open-Meteo │
                                        │  2. extraire 7       │
                ┌──────────────────────┐│     créneaux + agrég.│
                │   Open-Meteo API     │◀┤  3. calcul grêle,   │
                │ (gratuit, sans clé)  │ │     veste           │
                └──────────────────────┘ │  4. charger veille  │
                                         │     (data/*.json)   │
                ┌──────────────────────┐ │  5. formater HTML   │
                │  Telegram Bot API    │◀┤  6. envoyer message │
                └──────────────────────┘ │  7. sauver du jour  │
                         │               └──────────────────────┘
                         ▼                          │
                   📱 Message reçu                  ▼
                                          git commit + push
                                          (data/YYYY-MM-DD.json)
```

### Flux d'exécution

1. GitHub Actions déclenche le workflow à 5h **et** 6h UTC (double cron pour absorber le changement d'heure).
2. Le script vérifie qu'il est bien 7h heure de Paris — sinon sortie silencieuse (évite double envoi).
3. Appel Open-Meteo (hourly : temp, précip, couverture nuageuse, weathercode, sunshine) pour la journée.
4. Extraction de 7 créneaux : **8h, 10h, 12h, 14h, 16h, 18h, 20h**.
5. Calcul des agrégats journaliers + heuristique grêle + recommandation veste.
6. Lecture de `data/<hier>.json` si présent → calcul Δmin/Δmax.
7. Envoi Telegram (HTML, `sendMessage`).
8. Écriture de `data/<aujourd'hui>.json` + commit automatique dans le repo.

## Stack

| Composant | Choix | Pourquoi |
|---|---|---|
| Données météo | [Open-Meteo](https://open-meteo.com) | Gratuit, sans clé API, couverture Europe fiable |
| Langage | Python 3.12 (runner) / 3.9 (local) | Simplicité, écosystème `requests` |
| Dépendances | `requests` uniquement | Éviter la surcharge (`python-telegram-bot` remplacé par POST direct) |
| Planification | GitHub Actions cron | Gratuit, zéro infra, sans serveur 24/7 |
| Notification | Telegram Bot API | Bot existant réutilisé du projet `260418-Telegram` |
| Persistance | JSON commité dans le repo (`data/`) | Runner éphémère → commit auto ; bonus : historique public |
| Secrets | GitHub Secrets (prod) · Keychain macOS (local) | Aucun secret dans le code, repo public safe |

## Décisions d'architecture

### Pourquoi GitHub Actions, pas Docker/serveur ?

Ce projet est un cron de 10 secondes par jour, sans service web. Un container Docker sur un serveur 24/7 serait **surdimensionné** pour ça. GitHub Actions fournit :
- Un runner gratuit à la demande
- Un cron intégré
- Une gestion native des secrets
- Zéro infrastructure à maintenir

Docker aurait eu du sens si on avait une API HTTP, un dashboard ou un process long.

### Pourquoi repo public ?

Pas de contenu sensible dans le code. Les secrets (token bot, chat_id) sont dans **GitHub Secrets**, jamais commités. Le *secret scanning* + *push protection* sont activés. Bénéfices : historique météo visible, transparence, réutilisable par d'autres.

### Heuristique grêle (XS/S/L/XL, sans M)

Open-Meteo ne fournit pas de "prévision grêle" directe. On la **dérive des codes WMO** :

| Taille | Condition |
|---|---|
| **XL** | Code 99 présent (orage avec grêle dense) |
| **L** | Code 96 (grêle légère) **ou** code 95 + précip > 5 mm/h sur un créneau |
| **S** | Code 95 (orage) **ou** précip > 2 mm/h sur un créneau |
| **XS** | Aucune des conditions ci-dessus |

Proxy honnête — pas une prévision professionnelle, mais suffisant pour décider d'annuler un barbecue.

### Recommandation de veste

| Temp moyenne (min+max)/2 | Veste |
|---|---|
| < 10°C | 🧥 Manteau violet |
| 10–20°C | 🦺 Gilet / veste blanche |
| > 20°C | Aucune |

Logique personnelle du destinataire — garde-robe dédiée, pas générique.

### Gestion du changement d'heure (DST)

GitHub Actions cron tourne **en UTC**. 7h Paris = 5h UTC (été) ou 6h UTC (hiver). Solution retenue : **double cron** (5h et 6h UTC) + garde dans le script qui vérifie `datetime.now(Europe/Paris).hour == 7`, sinon exit silencieux. Simple, robuste, pas de lib tierce.

### Persistance "données de la veille"

Le runner GitHub Actions est éphémère — impossible de garder un fichier entre deux runs sans artifact. Choix : **commit automatique** du JSON quotidien dans `data/` via `GITHUB_TOKEN` (permission `contents: write`). Bénéfices :
- Simple, natif, zéro dépendance
- Historique météo consultable sur GitHub
- Pas de stockage externe à gérer

## Setup

### Secrets GitHub

Dans **Settings → Secrets and variables → Actions**, ajouter :

| Secret | Valeur |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token du bot (via [@BotFather](https://t.me/BotFather)) |
| `TELEGRAM_CHAT_ID` | ID du chat/groupe destinataire |

### Test local (macOS)

```bash
pip install requests

# Option A — variables d'env
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python3 main.py

# Option B — Keychain macOS (fallback automatique)
security add-generic-password -a "$USER" -s telegram-bot-token -w "LE_TOKEN"
security add-generic-password -a "$USER" -s telegram-chat-id   -w "LE_CHAT_ID"
python3 main.py
```

### Déclencher un run manuel

Via l'UI GitHub : onglet *Actions* → *Bulletin météo quotidien* → *Run workflow*.

## Sécurité

- Aucun secret en dur dans le code ni dans l'historique git
- *Secret scanning* + *push protection* activés sur le repo
- Le bot Telegram n'envoie qu'au `chat_id` configuré (pas d'écoute de messages entrants)

## Licence

Usage personnel.
