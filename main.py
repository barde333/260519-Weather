#!/usr/bin/env python3
"""
Météo Saint-Ismier → Telegram.

Récupère les prévisions du jour via Open-Meteo, extrait 7 créneaux horaires,
compare avec la veille, détermine la veste à porter, évalue le risque de grêle,
et envoie un bulletin HTML via Telegram. Destiné à GitHub Actions (cron 7h Paris).
"""

import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PARIS_TZ = ZoneInfo("Europe/Paris")

# Saint-Ismier, Isère, France
LATITUDE = 45.24
LONGITUDE = 5.82

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

# Créneaux horaires du bulletin (heure locale Paris)
TARGET_HOURS = [8, 10, 12, 14, 16, 18, 20]

# Répertoire de persistance (JSON quotidien, committé par le workflow)
DATA_DIR = Path(__file__).parent / "data"

# Codes météo WMO : (description FR, emoji)
WEATHER_CODES = {
    0:  ("Clair", "☀️"),
    1:  ("Principalement clair", "🌤️"),
    2:  ("Partiellement nuageux", "⛅"),
    3:  ("Nuageux", "☁️"),
    45: ("Brouillard", "🌫️"),
    48: ("Brouillard givrant", "🌫️"),
    51: ("Bruine légère", "🌧️"),
    53: ("Bruine modérée", "🌧️"),
    55: ("Bruine dense", "🌧️"),
    61: ("Pluie légère", "🌧️"),
    63: ("Pluie modérée", "🌧️"),
    65: ("Pluie dense", "🌧️"),
    71: ("Neige légère", "❄️"),
    73: ("Neige modérée", "❄️"),
    75: ("Neige dense", "❄️"),
    77: ("Grains de neige", "❄️"),
    80: ("Averses légères", "🌧️"),
    81: ("Averses modérées", "🌧️"),
    82: ("Averses violentes", "⛈️"),
    85: ("Averses de neige légères", "❄️"),
    86: ("Averses de neige denses", "❄️"),
    95: ("Orage", "⛈️"),
    96: ("Orage avec grêle légère", "⛈️"),
    99: ("Orage avec grêle dense", "⛈️"),
}

DAY_NAMES_FR = {
    "Monday": "lundi", "Tuesday": "mardi", "Wednesday": "mercredi",
    "Thursday": "jeudi", "Friday": "vendredi", "Saturday": "samedi",
    "Sunday": "dimanche",
}


# ---------------------------------------------------------------------------
# Fonctions (à implémenter dans les étapes suivantes)
# ---------------------------------------------------------------------------

def get_secrets():
    """Retourne (bot_token, chat_id) depuis les variables d'env ou le Keychain macOS."""
    import os
    import subprocess

    def from_keychain(service):
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                capture_output=True, text=True, check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or from_keychain("telegram-bot-token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or from_keychain("telegram-chat-id")

    if not token or not chat_id:
        raise RuntimeError(
            "Secrets manquants. Définir TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID "
            "(env vars), ou stocker via Keychain macOS sous les services "
            "'telegram-bot-token' et 'telegram-chat-id'."
        )
    return token, chat_id


def fetch_meteo(max_retries=4, base_delay=5):
    """Appelle Open-Meteo et retourne le JSON brut pour la journée.

    Retry avec backoff exponentiel sur les erreurs transitoires (5xx, timeout).
    """
    import time

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "temperature_2m,precipitation,cloudcover,weathercode,sunshine_duration",
        "timezone": "Europe/Paris",
        "forecast_days": 1,
    }

    last_exc = None
    for attempt in range(max_retries):
        if attempt > 0:
            delay = base_delay * (2 ** (attempt - 1))  # 5s, 10s, 20s
            logger.warning(f"Tentative {attempt + 1}/{max_retries} dans {delay}s…")
            time.sleep(delay)
        try:
            logger.info(f"Appel Open-Meteo (tentative {attempt + 1}/{max_retries})…")
            response = requests.get(OPEN_METEO_URL, params=params, timeout=15)
            if response.status_code in (502, 503, 504):
                last_exc = requests.HTTPError(
                    f"{response.status_code} Server Error: {response.reason} for url: {response.url}",
                    response=response,
                )
                logger.warning(f"Erreur {response.status_code} — nouvelle tentative")
                continue
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            last_exc = e
            logger.warning(f"Timeout — nouvelle tentative")
        except requests.exceptions.ConnectionError as e:
            last_exc = e
            logger.warning(f"Erreur réseau — nouvelle tentative")

    raise last_exc


def extract_hourly_data(meteo_data):
    """Extrait les 7 créneaux horaires + agrégats journaliers depuis la réponse Open-Meteo."""
    hourly = meteo_data["hourly"]
    times = hourly["time"]                          # liste de "YYYY-MM-DDTHH:MM"
    temps = hourly["temperature_2m"]
    precips = hourly["precipitation"]
    clouds = hourly["cloudcover"]
    codes = hourly["weathercode"]
    sunshine = hourly["sunshine_duration"]          # secondes par heure

    # Index des créneaux cibles (heure == TARGET_HOURS)
    slots = []
    for i, t in enumerate(times):
        hour = int(t[11:13])
        if hour in TARGET_HOURS:
            slots.append({
                "hour": hour,
                "temp": temps[i],
                "precip": precips[i],
                "cloud": clouds[i],
                "code": codes[i],
                "sunshine_s": sunshine[i],
            })

    all_temps = [t for t in temps if t is not None]
    all_precips = [p for p in precips if p is not None]
    total_sunshine_h = sum(s for s in sunshine if s is not None) / 3600

    daily = {
        "temp_min": min(all_temps),
        "temp_max": max(all_temps),
        "precipitation_sum": round(sum(all_precips), 1),
        "sunshine_hours": round(total_sunshine_h, 2),
    }

    return slots, daily


def get_hail_risk(hourly_data):
    """Retourne 'XS', 'S', 'L' ou 'XL' selon les codes WMO et les précipitations."""
    codes = {slot["code"] for slot in hourly_data}
    max_precip = max((slot["precip"] for slot in hourly_data), default=0)

    if 99 in codes:
        return "XL"
    if 96 in codes or (95 in codes and max_precip > 5):
        return "L"
    if 95 in codes or max_precip > 2:
        return "S"
    return "XS"


def get_jacket_recommendation(temp_min, temp_max):
    """Retourne la recommandation de veste selon la température moyenne."""
    temp_avg = (temp_min + temp_max) / 2
    if temp_avg < 10:
        return "🧥 Manteau violet"
    if temp_avg <= 20:
        return "🦺 Gilet / veste blanche"
    return None


def build_telegram_message(hourly, daily, jacket, hail, yesterday):
    """Formate le bulletin Telegram en HTML."""
    import datetime

    MONTHS_FR = {
        1: "janvier", 2: "février", 3: "mars", 4: "avril", 5: "mai", 6: "juin",
        7: "juillet", 8: "août", 9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
    }
    now = datetime.datetime.now(PARIS_TZ)
    day_fr = DAY_NAMES_FR[now.strftime("%A")]
    date_str = f"{day_fr} {now.day} {MONTHS_FR[now.month]}"

    temp_min = round(daily["temp_min"])
    temp_max = round(daily["temp_max"])

    # Ensoleillement → "XhYY"
    total_s = daily["sunshine_hours"] * 3600
    sun_h = int(total_s // 3600)
    sun_m = int((total_s % 3600) // 60)
    sun_str = f"{sun_h}h{sun_m:02d}"

    lines = [f"🌤️ <b>Météo Saint-Ismier — {date_str}</b>"]

    if jacket:
        lines.append(f"{jacket} aujourd'hui ({temp_min}–{temp_max}°C)")
    else:
        lines.append(f"👕 Pas de veste aujourd'hui ({temp_min}–{temp_max}°C)")

    hail_icon = {"XL": "🔴", "L": "🟠", "S": "🟢", "XS": "🟢"}.get(hail, "")
    lines.append(f"🧊 Risque de grêle : {hail} {hail_icon}")
    lines.append("")
    lines.append("⏰ <b>Créneaux :</b>")

    for slot in hourly:
        emoji = WEATHER_CODES.get(slot["code"], ("❓", ""))[1]
        precip = int(slot["precip"]) if slot["precip"] == int(slot["precip"]) else slot["precip"]
        lines.append(
            f"{slot['hour']:02d}h — {round(slot['temp'])}°C | {emoji} {slot['cloud']}% | 💧 {precip}mm"
        )

    if yesterday:
        y_max = yesterday.get("daily", {}).get("temp_max")
        y_min = yesterday.get("daily", {}).get("temp_min")
        if y_max is not None and y_min is not None:
            diff_max = round(daily["temp_max"] - y_max, 1)
            diff_min = round(daily["temp_min"] - y_min, 1)
            sign = lambda v: f"+{v}" if v >= 0 else str(v)
            lines.append("")
            lines.append(f"📊 vs hier : Max {sign(diff_max)}°C | Min {sign(diff_min)}°C")

    return "\n".join(lines)


def send_telegram(token, chat_id, message):
    """Envoie le message HTML via l'API Telegram Bot."""
    url = TELEGRAM_API_URL.format(token=token)
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")


def load_yesterday():
    """Lit le JSON de la veille depuis data/<hier>.json, ou None si absent."""
    import datetime
    yesterday = (datetime.datetime.now(PARIS_TZ).date() - datetime.timedelta(days=1)).isoformat()
    path = DATA_DIR / f"{yesterday}.json"
    if path.exists():
        import json
        return json.loads(path.read_text())
    return None


def save_today(payload):
    """Écrit le JSON du jour dans data/<aujourd'hui>.json."""
    import datetime
    import json
    today = datetime.datetime.now(PARIS_TZ).date().isoformat()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{today}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def send_alert(token, chat_id, error: Exception):
    """Envoie un message d'alerte Telegram en cas d'erreur critique."""
    try:
        msg = f"⚠️ <b>Météo Saint-Ismier — erreur</b>\n<code>{type(error).__name__}: {error}</code>"
        send_telegram(token, chat_id, msg)
    except Exception as alert_err:
        logger.error(f"Impossible d'envoyer l'alerte Telegram : {alert_err}")


def main():
    """Orchestration du bulletin météo quotidien."""
    import datetime, os

    # Garde : les crons UTC couvrent plusieurs heures, mais seuls ceux qui tombent
    # sur 5h ou 6h Paris doivent envoyer (objectif : alerte reçue ≤ 7h malgré le
    # retard fréquent de GH Actions, qui peut atteindre ~1h).
    # Bypass via FORCE_SEND=1 pour les déclenchements manuels (workflow_dispatch, local).
    if not os.environ.get("FORCE_SEND"):
        paris_hour = datetime.datetime.now(PARIS_TZ).hour
        if paris_hour not in (5, 6):
            logger.info(f"Hors créneau (Paris {paris_hour}h) → exit silencieux")
            return

        # Dédup : si le bulletin du jour a déjà été envoyé (fichier présent),
        # le cron backup 7h sort sans rien faire.
        today = datetime.datetime.now(PARIS_TZ).date().isoformat()
        if (DATA_DIR / f"{today}.json").exists():
            logger.info("Bulletin déjà envoyé aujourd'hui → exit silencieux")
            return

    token, chat_id = None, None
    try:
        token, chat_id = get_secrets()
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        meteo = fetch_meteo()
        hourly, daily = extract_hourly_data(meteo)

        hail = get_hail_risk(hourly)
        jacket = get_jacket_recommendation(daily["temp_min"], daily["temp_max"])
        yesterday = load_yesterday()

        message = build_telegram_message(hourly, daily, jacket, hail, yesterday)
        send_telegram(token, chat_id, message)
        save_today({"hourly": hourly, "daily": daily, "hail": hail})

        logger.info("✓ Bulletin envoyé")

    except Exception as e:
        logger.error(f"Erreur : {e}")
        if token and chat_id:
            send_alert(token, chat_id, e)
        sys.exit(1)


if __name__ == "__main__":
    main()
