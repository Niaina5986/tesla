import os
import json
import re
import math
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from itertools import combinations
from difflib import SequenceMatcher

# =========================================================
# TESLA SPORTS INTELLIGENCE
# Football | Basketball | Tennis
# =========================================================

BOT_NAME = "TESLA SPORTS INTELLIGENCE"
VERSION = "1.0"

ODDS_URL = "https://api.the-odds-api.com/v4"
SPORTSCORE_URL = "https://sportscore.com/api/v1"

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "tesla_data.json"

MIN_ODDS = 10.00
MIN_SELECTIONS = 3
MAX_SELECTIONS = 7

REGION = "eu"

TZ = timezone(timedelta(hours=3))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

session = requests.Session()
session.headers.update({
    "User-Agent": "TeslaSportsIntelligence/1.0"
})


# =========================================================
# CONFIGURATION
# =========================================================

def secret(name):
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(f"Secret absent : {name}")

    return value


ODDS_KEY = secret("ODDS_API_KEY")
SPORTSCORE_KEY = os.getenv("SPORTSCORE_API_KEY", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "")

TELEGRAM_TOKEN = secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT = secret("TELEGRAM_CHAT_ID")


# =========================================================
# TELEGRAM PROFESSIONAL NOTIFICATIONS
# =========================================================

def telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    response = session.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        },
        timeout=30
    )

    response.raise_for_status()


def header(title):

    now = datetime.now(TZ)

    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>{BOT_NAME}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {now.strftime('%d/%m/%Y')}\n"
        f"🕒 {now.strftime('%H:%M:%S')} (UTC+3)\n"
        f"🔧 Version {VERSION}\n\n"
        f"<b>{title}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )


# =========================================================
# DATABASE
# =========================================================

def load_database():

    if STATE_FILE.exists():

        try:
            return json.loads(
                STATE_FILE.read_text(encoding="utf-8")
            )

        except Exception:
            logging.exception("Database illisible")

    return {
        "signals": {},
        "last_daily_signal": None,
        "reported_results": []
    }


def save_database(db):

    STATE_FILE.write_text(
        json.dumps(
            db,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )


# =========================================================
# API REQUESTS
# =========================================================

def get_api(url, params=None, headers=None):

    response = session.get(
        url,
        params=params,
        headers=headers,
        timeout=40
    )

    response.raise_for_status()

    return response.json()


def post_api(url, payload, headers=None):

    response = session.post(
        url,
        json=payload,
        headers=headers,
        timeout=40
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# SPORT DISCOVERY
# =========================================================

def discover_sports():

    data = get_api(
        f"{ODDS_URL}/sports",
        {"apiKey": ODDS_KEY}
    )

    sports = {
        "football": [],
        "basketball": [],
        "tennis": []
    }

    for item in data:

        if not item.get("active"):
            continue

        key = item.get("key", "").lower()
        group = item.get("group", "").lower()

        if "soccer" in key or "football" in group:
            sports["football"].append(key)

        elif "basketball" in key or "basketball" in group:
            sports["basketball"].append(key)

        elif "tennis" in key or "tennis" in group:
            sports["tennis"].append(key)

    # Limit the number of competitions to control API quota.
    for sport in sports:
        sports[sport] = sports[sport][:3]

    return sports


# =========================================================
# SPORT SCORE VERIFICATION
# =========================================================

def normalize(value):

    value = str(value or "").lower()

    value = re.sub(
        r"\b(fc|cf|sc|afc|bc|club)\b",
        "",
        value
    )

    return re.sub(r"[^a-z0-9]", "", value)


def similarity(a, b):

    return SequenceMatcher(
        None,
        normalize(a),
        normalize(b)
    ).ratio()


def fixture_names(fixture):

    home = fixture.get("home_team") or fixture.get("home") or ""
    away = fixture.get("away_team") or fixture.get("away") or ""

    if isinstance(home, dict):
        home = home.get("name", "")

    if isinstance(away, dict):
        away = away.get("name", "")

    return str(home), str(away)


def get_fixtures(sport, date):

    headers = {}

    if SPORTSCORE_KEY:
        headers["X-Api-Key"] = SPORTSCORE_KEY

    return get_api(
        f"{SPORTSCORE_URL}/fixtures/",
        {
            "sport": sport,
            "date": date,
            "limit": 200
        },
        headers or None
    )


def extract_fixtures(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "fixtures",
            "results",
            "matches"
        ):

            if isinstance(data.get(key), list):
                return data[key]

    return []


def verify_fixture(event, fixtures):

    home = event.get("home_team", "")
    away = event.get("away_team", "")

    best = None
    best_score = 0

    for fixture in fixtures:

        fh, fa = fixture_names(fixture)

        direct = (
            similarity(home, fh) +
            similarity(away, fa)
        ) / 2

        reverse = (
            similarity(home, fa) +
            similarity(away, fh)
        ) / 2

        score = max(direct, reverse)

        if score > best_score:
            best_score = score
            best = fixture

    if best_score >= 0.84:
        return best

    return None


# =========================================================
# ODDS COLLECTION
# =========================================================

def get_odds(sport_key):

    return get_api(
        f"{ODDS_URL}/sports/{sport_key}/odds",
        {
            "apiKey": ODDS_KEY,
            "regions": REGION,
            "markets": "h2h",
            "oddsFormat": "decimal",
            "dateFormat": "iso"
        }
    )


def analyze_event(event, sport, fixtures):

    fixture = verify_fixture(event, fixtures)

    if not fixture:
        return None

    commence = event.get("commence_time")

    if not commence:
        return None

    try:
        start = datetime.fromisoformat(
            commence.replace("Z", "+00:00")
        )

        if start <= datetime.now(timezone.utc):
            return None

    except Exception:
        return None

    outcomes = {}

    for bookmaker in event.get("bookmakers", []):

        for market in bookmaker.get("markets", []):

            if market.get("key") != "h2h":
                continue

            valid = [
                x for x in market.get("outcomes", [])
                if isinstance(x.get("price"), (int, float))
                and x["price"] > 1
            ]

            if len(valid) < 2:
                continue

            raw = [
                1 / x["price"]
                for x in valid
            ]

            margin = sum(raw)

            if margin <= 0:
                continue

            for outcome, probability in zip(valid, raw):

                name = outcome.get("name")

                outcomes.setdefault(name, []).append({
                    "odds": float(outcome["price"]),
                    "probability": probability / margin
                })

    if not outcomes:
        return None

    candidates = []

    for name, values in outcomes.items():

        average_odds = sum(
            x["odds"] for x in values
        ) / len(values)

        average_probability = sum(
            x["probability"] for x in values
        ) / len(values)

        if not 1.25 <= average_odds <= 4.00:
            continue

        candidates.append({
            "sport": sport,
            "event_id": event.get("id"),
            "home": event.get("home_team"),
            "away": event.get("away_team"),
            "selection": name,
            "odds": round(average_odds, 2),
            "market_probability": round(
                average_probability, 4
            ),
            "start": commence,
            "bookmakers": len(values)
        })

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda x: x["market_probability"]
    )


# =========================================================
# TICKET ENGINE
# =========================================================

def build_ticket(candidates):

    candidates.sort(
        key=lambda x: x["market_probability"],
        reverse=True
    )

    candidates = candidates[:18]

    best_ticket = None

    for number in range(
        MIN_SELECTIONS,
        min(MAX_SELECTIONS, len(candidates)) + 1
    ):

        for ticket in combinations(candidates, number):

            combined = math.prod(
                item["odds"] for item in ticket
            )

            if combined < MIN_ODDS:
                continue

            score = sum(
                math.log(
                    max(item["market_probability"], 0.000001)
                )
                for item in ticket
            )

            if (
                best_ticket is None
                or score > best_ticket["score"]
            ):

                best_ticket = {
                    "legs": list(ticket),
                    "odds": combined,
                    "score": score
                }

    return best_ticket


# =========================================================
# AI DOUBLE VERIFICATION
# =========================================================

def ai_check(ticket):

    content = json.dumps(
        ticket,
        ensure_ascii=False
    )

    prompt = f"""
You are a strict sports data consistency auditor.

Check only:
- Duplicate events.
- Invalid or contradictory selections.
- Missing event information.
- Obviously inconsistent data.

Do not invent statistics.
Do not invent injuries.
Do not claim that a bet is safe.
Do not estimate winning probabilities.

Return only JSON:
{{"approve": true, "reason": "short explanation"}}

Ticket:
{content}
"""

    decisions = []

    if GROQ_KEY:

        try:

            data = post_api(
                "https://api.groq.com/openai/v1/chat/completions",
                {
                    "model": os.getenv(
                        "GROQ_MODEL",
                        "llama-3.3-70b-versatile"
                    ),
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                },
                {
                    "Authorization": f"Bearer {GROQ_KEY}"
                }
            )

            text = data["choices"][0]["message"]["content"]

            match = re.search(r"\{.*\}", text, re.S)

            if match:
                decisions.append(
                    json.loads(match.group())
                )
            else:
                decisions.append({"approve": False})

        except Exception:
            logging.exception("Erreur Groq")
            decisions.append({"approve": False})

    if GEMINI_KEY:

        try:

            data = post_api(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                + os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
                + ":generateContent",
                {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt}
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0
                    }
                },
                {
                    "x-goog-api-key": GEMINI_KEY
                }
            )

            text = data["candidates"][0]["content"]["parts"][0]["text"]

            match = re.search(r"\{.*\}", text, re.S)

            if match:
                decisions.append(
                    json.loads(match.group())
                )
            else:
                decisions.append({"approve": False})

        except Exception:
            logging.exception("Erreur Gemini")
            decisions.append({"approve": False})

    # Both AI reviewers must approve.
    return (
        len(decisions) == 2
        and all(x.get("approve") is True for x in decisions)
    )


# =========================================================
# DAILY SIGNAL
# =========================================================

def send_daily_signal(db):

    today = datetime.now(TZ).date().isoformat()

    if db["last_daily_signal"] == today:
        return

    sports = discover_sports()

    utc_day = datetime.now(
        timezone.utc
    ).date().isoformat()

    fixtures = {}

    for sport in ("football", "basketball", "tennis"):

        try:
            fixtures[sport] = extract_fixtures(
                get_fixtures(sport, utc_day)
            )

        except Exception:
            logging.exception(
                "SportScore indisponible pour %s",
                sport
            )
            fixtures[sport] = []

    candidates = []

    for sport, keys in sports.items():

        for key in keys:

            try:

                events = get_odds(key)

                for event in events:

                    result = analyze_event(
                        event,
                        sport,
                        fixtures[sport]
                    )

                    if result:
                        candidates.append(result)

            except Exception:
                logging.exception(
                    "Erreur Odds API : %s",
                    key
                )

    # One selection per event.
    unique = {}

    for item in candidates:
        unique[item["event_id"]] = item

    ticket = build_ticket(
        list(unique.values())
    )

    if not ticket:

        telegram(
            header("📭 AUCUN SIGNAL VALIDÉ")
            + "Aucun combiné ne satisfait les critères "
              "de sélection aujourd'hui.\n\n"
              f"🎯 Cote minimale : {MIN_ODDS:.2f}\n"
              f"📌 Sélections requises : "
              f"{MIN_SELECTIONS} à {MAX_SELECTIONS}\n\n"
              "Le système ne force pas de pronostic."
        )

        db["last_daily_signal"] = today
        save_database(db)
        return

    if not ai_check(ticket["legs"]):

        telegram(
            header("⚠️ CONTRÔLE NON VALIDÉ")
            + "Le ticket n'a pas passé les deux contrôles IA.\n"
              "Aucun signal n'est publié."
        )

        db["last_daily_signal"] = today
        save_database(db)
        return

    ticket_id = datetime.now(TZ).strftime(
        "TESLA-%Y%m%d-%H%M%S"
    )

    lines = [
        header("🎯 NOUVEAU SIGNAL"),
        f"🆔 <code>{ticket_id}</code>",
        ""
    ]

    for index, leg in enumerate(ticket["legs"], 1):

        lines.extend([
            f"<b>{index}. {leg['sport'].upper()}</b>",
            f"⚔️ {leg['home']} vs {leg['away']}",
            f"🎯 Choix : <b>{leg['selection']}</b>",
            f"📈 Cote moyenne : <b>{leg['odds']:.2f}</b>",
            f"🕒 Début : {leg['start']}",
            f"🏦 Bookmakers comparés : {leg['bookmakers']}",
            ""
        ])

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"💎 <b>COTE COMBINÉE : {ticket['odds']:.2f}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "🔎 Vérifications :",
        "✅ Correspondance des rencontres",
        "✅ Cotes disponibles",
        "✅ Contrôle Gemini",
        "✅ Contrôle Groq",
        "",
        "⚠️ Les cotes peuvent changer.",
        "⚠️ Aucun gain n'est garanti.",
        "📊 Résultats suivis automatiquement."
    ])

    telegram("\n".join(lines))

    db["signals"][ticket_id] = {
        "date": today,
        "legs": ticket["legs"],
        "combined_odds": round(ticket["odds"], 2),
        "status": "pending"
    }

    db["last_daily_signal"] = today

    save_database(db)


# =========================================================
# RESULT TRACKING
# =========================================================

def check_results(db):

    # This section uses SportScore's finished fixtures.
    # Score formats differ by sport, so unresolved formats
    # remain pending instead of being incorrectly marked won/lost.

    pending = {
        key: value
        for key, value in db["signals"].items()
        if value["status"] == "pending"
    }

    if not pending:
        return

    dates = [
        datetime.now(timezone.utc).date() - timedelta(days=n)
        for n in range(3)
    ]

    all_fixtures = {
        "football": [],
        "basketball": [],
        "tennis": []
    }

    for sport in all_fixtures:

        for day in dates:

            try:

                all_fixtures[sport].extend(
                    extract_fixtures(
                        get_fixtures(
                            sport,
                            day.isoformat()
                        )
                    )
                )

            except Exception:
                logging.exception(
                    "Résultats indisponibles : %s",
                    sport
                )

    for ticket_id, ticket in pending.items():

        results = []
        lost = False
        all_finished = True

        for leg in ticket["legs"]:

            fixture = None
            best = 0

            for item in all_fixtures[leg["sport"]]:

                home, away = fixture_names(item)

                score = max(
                    (
                        similarity(leg["home"], home)
                        + similarity(leg["away"], away)
                    ) / 2,
                    (
                        similarity(leg["home"], away)
                        + similarity(leg["away"], home)
                    ) / 2
                )

                if score > best:
                    best = score
                    fixture = item

            if not fixture or best < 0.84:

                all_finished = False
                results.append("⏳ Rencontre non retrouvée")
                continue

            status = str(
                fixture.get("status", "")
            ).lower()

            if not any(
                word in status
                for word in (
                    "finished",
                    "complete",
                    "ended",
                    "full_time",
                    "ft"
                )
            ):

                all_finished = False
                results.append("⏳ Match en cours ou non terminé")
                continue

            # SportScore result fields can differ.
            # Do not guess a winner from an unknown score format.
            score_data = (
                fixture.get("score")
                or fixture.get("scores")
                or fixture.get("result")
            )

            if not isinstance(score_data, dict):

                all_finished = False
                results.append("❔ Score non interprétable")
                continue

            home_score = (
                score_data.get("home")
                or score_data.get("home_score")
            )

            away_score = (
                score_data.get("away")
                or score_data.get("away_score")
            )

            if isinstance(home_score, dict):
                home_score = home_score.get("total")

            if isinstance(away_score, dict):
                away_score = away_score.get("total")

            try:
                home_score = float(home_score)
                away_score = float(away_score)

            except (TypeError, ValueError):

                all_finished = False
                results.append("❔ Score indisponible")
                continue

            selection = normalize(
                leg["selection"]
            )

            home = normalize(leg["home"])
            away = normalize(leg["away"])

            if selection == home:
                won = home_score > away_score

            elif selection == away:
                won = away_score > home_score

            elif selection in ("draw", "tie"):
                won = home_score == away_score

            else:

                all_finished = False
                results.append("❔ Sélection non reconnue")
                continue

            if won:

                results.append(
                    f"✅ {leg['home']} — {home_score:g}:{away_score:g}"
                )

            else:

                lost = True

                results.append(
                    f"❌ {leg['home']} — {home_score:g}:{away_score:g}"
                )

        if lost:

            ticket["status"] = "lost"

        elif all_finished:

            ticket["status"] = "won"

        else:

            continue

        if ticket_id not in db["reported_results"]:

            title = (
                "🏆 COMBINÉ GAGNÉ"
                if ticket["status"] == "won"
                else "❌ COMBINÉ PERDU"
            )

            telegram(
                header(title)
                + f"🆔 <code>{ticket_id}</code>\n"
                + f"💎 Cote : {ticket['combined_odds']}\n\n"
                + "\n".join(results)
            )

            db["reported_results"].append(ticket_id)

            save_database(db)


# =========================================================
# MAIN
# =========================================================

def main():

    db = load_database()

    telegram(
        header("🟢 SYSTÈME EN LIGNE")
        + "Analyse des rencontres et suivi des résultats."
    )

    check_results(db)

    send_daily_signal(db)

    save_database(db)

    logging.info("TESLA terminé.")


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        logging.exception("Erreur TESLA")

        try:

            telegram(
                header("🚨 ERREUR SYSTÈME")
                + f"<code>{type(error).__name__}</code>\n"
                + str(error)[:1000]
            )

        except Exception:
            pass

        raise