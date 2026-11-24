import os
import re
import json
import math
import html
import logging
import requests

from pathlib import Path
from datetime import datetime, timezone, timedelta
from itertools import combinations
from difflib import SequenceMatcher

# =========================================================
# TESLA SPORTS INTELLIGENCE V2
# =========================================================

BOT_NAME = "TESLA SPORTS INTELLIGENCE"
VERSION = "2.0"

ODDS_URL = "https://api.the-odds-api.com/v4"
SPORTSCORE_URL = "https://sportscore.com/api/v1"

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "tesla_data.json"

TZ = timezone(timedelta(hours=3))

MIN_CONFIDENCE = 50
MIN_TOTAL_ODDS = 2.00

MIN_SELECTIONS = 1
MAX_SELECTIONS = 10

ANALYSIS_INTERVAL = 2 * 60 * 60
REGIONS = os.getenv("ODDS_REGIONS", "eu")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

http = requests.Session()
http.headers.update({
    "User-Agent": "Tesla-Sports-Intelligence/2.0"
})


# =========================================================
# SECRETS
# =========================================================

def secret(name):
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(f"Secret manquant : {name}")

    return value


ODDS_KEY = secret("ODDS_API_KEY")
TELEGRAM_TOKEN = secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT = secret("TELEGRAM_CHAT_ID")

SPORTSCORE_KEY = os.getenv("SPORTSCORE_API_KEY", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "")


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    # Split long messages safely.
    for start in range(0, len(message), 3900):

        part = message[start:start + 3900]

        response = http.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT,
                "text": part,
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
        f"🕒 {now.strftime('%H:%M:%S')} UTC+3\n"
        f"🔧 VERSION {VERSION}\n\n"
        f"<b>{title}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )


# =========================================================
# DATABASE
# =========================================================

def load_db():

    if DB_FILE.exists():

        try:
            return json.loads(
                DB_FILE.read_text(encoding="utf-8")
            )

        except Exception:
            logging.exception("Database illisible")

    return {
        "last_analysis": None,
        "tickets": {},
        "reported_results": []
    }


def save_db(db):

    DB_FILE.write_text(
        json.dumps(
            db,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )


# =========================================================
# HTTP
# =========================================================

def get_json(url, params=None, headers=None):

    response = http.get(
        url,
        params=params,
        headers=headers,
        timeout=40
    )

    response.raise_for_status()

    return response.json()


def post_json(url, payload, headers=None):

    response = http.post(
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

    data = get_json(
        f"{ODDS_URL}/sports",
        {"apiKey": ODDS_KEY}
    )

    result = {
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
            result["football"].append(key)

        elif "basketball" in key or "basketball" in group:
            result["basketball"].append(key)

        elif "tennis" in key or "tennis" in group:
            result["tennis"].append(key)

    # Limit API consumption.
    for sport in result:
        result[sport] = result[sport][:3]

    return result


# =========================================================
# SPORT SCORE FIXTURES
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


def extract_list(data):

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


def fixture_names(fixture):

    home = (
        fixture.get("home_team")
        or fixture.get("home")
        or ""
    )

    away = (
        fixture.get("away_team")
        or fixture.get("away")
        or ""
    )

    if isinstance(home, dict):
        home = home.get("name", "")

    if isinstance(away, dict):
        away = away.get("name", "")

    return str(home), str(away)


def get_fixtures(sport, date, status=None):

    params = {
        "sport": sport,
        "date": date,
        "limit": 200
    }

    if status:
        params["status"] = status

    headers = {}

    if SPORTSCORE_KEY:
        headers["X-Api-Key"] = SPORTSCORE_KEY

    data = get_json(
        f"{SPORTSCORE_URL}/fixtures/",
        params,
        headers or None
    )

    return extract_list(data)


def find_fixture(home, away, fixtures):

    best = None
    best_score = 0

    for fixture in fixtures:

        fh, fa = fixture_names(fixture)

        direct = (
            similarity(home, fh)
            + similarity(away, fa)
        ) / 2

        reverse = (
            similarity(home, fa)
            + similarity(away, fh)
        ) / 2

        score = max(direct, reverse)

        if score > best_score:
            best = fixture
            best_score = score

    if best_score >= 0.84:
        return best

    return None


# =========================================================
# MARKET ANALYSIS
# =========================================================

def analyze_event(event, sport, fixtures):

    home = event.get("home_team", "")
    away = event.get("away_team", "")

    fixture = find_fixture(home, away, fixtures)

    if not fixture:
        return []

    start_text = event.get("commence_time")

    if not start_text:
        return []

    try:

        start = datetime.fromisoformat(
            start_text.replace("Z", "+00:00")
        )

        if start <= datetime.now(timezone.utc):
            return []

    except Exception:
        return []

    outcomes = {}

    for bookmaker in event.get("bookmakers", []):

        for market in bookmaker.get("markets", []):

            if market.get("key") != "h2h":
                continue

            valid = [
                item
                for item in market.get("outcomes", [])
                if isinstance(item.get("price"), (int, float))
                and item["price"] > 1
            ]

            if len(valid) < 2:
                continue

            raw = [
                1 / item["price"]
                for item in valid
            ]

            margin = sum(raw)

            if margin <= 0:
                continue

            for item, probability in zip(valid, raw):

                name = item.get("name", "")

                outcomes.setdefault(name, []).append({
                    "odds": float(item["price"]),
                    "probability": probability / margin
                })

    candidates = []

    for selection, values in outcomes.items():

        average_odds = sum(
            x["odds"] for x in values
        ) / len(values)

        average_probability = sum(
            x["probability"] for x in values
        ) / len(values)

        if not 1.15 <= average_odds <= 8:
            continue

        probabilities = [
            x["probability"] for x in values
        ]

        dispersion = max(probabilities) - min(probabilities)

        # -------------------------------------------------
        # DATA QUALITY SCORE: NOT A WIN PROBABILITY
        # -------------------------------------------------

        bookmaker_score = min(
            len(values) / 5 * 20,
            20
        )

        agreement_score = max(
            0,
            20 - dispersion * 100
        )

        fixture_score = 20

        freshness_score = 20 if start > datetime.now(
            timezone.utc
        ) else 0

        market_score = min(
            average_probability * 40,
            20
        )

        confidence = round(
            bookmaker_score
            + agreement_score
            + fixture_score
            + freshness_score
            + market_score
        )

        confidence = min(100, max(0, confidence))

        candidates.append({

            "sport": sport,
            "event_id": event.get("id"),

            "home": home,
            "away": away,

            "selection": selection,

            "odds": round(average_odds, 2),

            "market_probability": round(
                average_probability, 4
            ),

            "confidence": confidence,

            "bookmakers": len(values),

            "start": start_text,

            "fixture_status": fixture.get("status", "")

        })

    return candidates


# =========================================================
# AI AUDIT
# =========================================================

def ai_review(ticket):

    prompt = (
        "You are a strict sports data auditor. "
        "Check duplicate events, inconsistent team names, "
        "missing information and contradictory selections. "
        "Do not invent statistics or probabilities. "
        "Return only JSON: "
        '{"approve":true,"reason":"short explanation"} '
        "Ticket: "
        + json.dumps(ticket, ensure_ascii=False)
    )

    decisions = []

    if GROQ_KEY:

        try:

            data = post_json(
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

            content = data["choices"][0]["message"]["content"]

            match = re.search(r"\{.*\}", content, re.S)

            if match:
                decisions.append(json.loads(match.group()))

        except Exception:
            logging.exception("Groq indisponible")

    if GEMINI_KEY:

        try:

            model = os.getenv(
                "GEMINI_MODEL",
                "gemini-2.5-flash"
            )

            data = post_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
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

            content = data["candidates"][0]["content"]["parts"][0]["text"]

            match = re.search(r"\{.*\}", content, re.S)

            if match:
                decisions.append(json.loads(match.group()))

        except Exception:
            logging.exception("Gemini indisponible")

    # If configured reviewers fail, do not claim AI validation.
    return (
        len(decisions) == 2
        and all(x.get("approve") is True for x in decisions)
    )


# =========================================================
# TICKET ENGINE
# =========================================================

def build_ticket(candidates):

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: (
            x["confidence"],
            x["market_probability"]
        ),
        reverse=True
    )

    # Prefer a strong single selection.
    best = candidates[0]

    if (
        best["odds"] >= MIN_TOTAL_ODDS
        and best["confidence"] >= 75
    ):

        return {
            "mode": "SIMPLE",
            "legs": [best],
            "odds": best["odds"]
        }

    # Otherwise search for a combination.
    best_ticket = None

    for count in range(
        2,
        min(MAX_SELECTIONS, len(candidates)) + 1
    ):

        for combo in combinations(candidates[:20], count):

            event_ids = [
                x["event_id"] for x in combo
            ]

            if len(event_ids) != len(set(event_ids)):
                continue

            total = math.prod(
                x["odds"] for x in combo
            )

            if total < MIN_TOTAL_ODDS:
                continue

            average_confidence = sum(
                x["confidence"] for x in combo
            ) / count

            score = (
                average_confidence,
                sum(
                    math.log(max(x["market_probability"], 0.000001))
                    for x in combo
                )
            )

            if (
                best_ticket is None
                or score > best_ticket["score"]
            ):

                best_ticket = {
                    "mode": "COMBINÉ",
                    "legs": list(combo),
                    "odds": total,
                    "score": score
                }

    if best_ticket:
        best_ticket.pop("score", None)
        return best_ticket

    # If no combination reaches 2.00, retain the best candidate.
    return {
        "mode": "SIMPLE",
        "legs": [best],
        "odds": best["odds"]
    }


# =========================================================
# TELEGRAM SIGNAL
# =========================================================

def publish_signal(db, ticket):

    confidence = round(
        sum(x["confidence"] for x in ticket["legs"])
        / len(ticket["legs"])
    )

    if confidence >= 85:
        label = "🟢 TRÈS FORTE"

    elif confidence >= 75:
        label = "🟢 FORTE"

    elif confidence >= 65:
        label = "🟡 BONNE"

    elif confidence >= 50:
        label = "🟠 MODÉRÉE"

    else:
        label = "🔴 SOUS LE SEUIL"

    ticket_id = datetime.now(TZ).strftime(
        "TESLA-%Y%m%d-%H%M%S"
    )

    lines = [
        header("🎯 NOUVEAU PRONOSTIC"),
        f"🆔 <code>{ticket_id}</code>",
        f"📌 Mode : <b>{ticket['mode']}</b>",
        f"📊 Indice de confiance : <b>{confidence}/100</b>",
        f"🏷️ Classification : {label}",
        ""
    ]

    for i, leg in enumerate(ticket["legs"], 1):

        lines.extend([
            f"<b>SÉLECTION {i} — {leg['sport'].upper()}</b>",
            f"⚔️ {html.escape(leg['home'])} vs {html.escape(leg['away'])}",
            f"🎯 Pronostic : <b>{html.escape(leg['selection'])}</b>",
            f"📈 Cote moyenne : <b>{leg['odds']:.2f}</b>",
            f"🏦 Bookmakers : {leg['bookmakers']}",
            f"📅 Début : {leg['start']}",
            f"📊 Qualité des données : {leg['confidence']}/100",
            ""
        ])

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"💎 <b>COTE TOTALE : {ticket['odds']:.2f}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "🔍 CONTRÔLE :",
        "✅ Rencontre retrouvée dans SportScore",
        "✅ Comparaison des cotes",
        "",
        (
            "⚠️ Indice inférieur à 50 : signal non validé."
            if confidence < MIN_CONFIDENCE
            else "✅ Indice supérieur ou égal à 50."
        ),
        "",
        "ℹ️ L'indice mesure la qualité des données, "
        "pas une probabilité de gain.",
        "⚠️ Aucun gain n'est garanti."
    ])

    telegram("\n".join(lines))

    db["tickets"][ticket_id] = {
        "mode": ticket["mode"],
        "legs": ticket["legs"],
        "odds": round(ticket["odds"], 2),
        "confidence": confidence,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    save_db(db)


# =========================================================
# ANALYSIS CYCLE
# =========================================================

def run_analysis(db):

    sports = discover_sports()

    utc_today = datetime.now(timezone.utc).date()

    dates = [
        utc_today + timedelta(days=i)
        for i in range(3)
    ]

    fixtures = {
        "football": [],
        "basketball": [],
        "tennis": []
    }

    for sport in fixtures:

        for day in dates:

            try:

                fixtures[sport].extend(
                    get_fixtures(
                        sport,
                        day.isoformat(),
                        "upcoming"
                    )
                )

            except Exception:
                logging.exception(
                    "SportScore : %s",
                    sport
                )

    candidates = []

    for sport, keys in sports.items():

        for key in keys:

            try:

                events = get_json(
                    f"{ODDS_URL}/sports/{key}/odds",
                    {
                        "apiKey": ODDS_KEY,
                        "regions": REGION,
                        "markets": "h2h",
                        "oddsFormat": "decimal"
                    }
                )

                for event in events:

                    candidates.extend(
                        analyze_event(
                            event,
                            sport,
                            fixtures[sport]
                        )
                    )

            except Exception:
                logging.exception(
                    "Odds API : %s",
                    key
                )

    # Keep only the best candidate per event.
    unique = {}

    for item in candidates:

        event_id = item["event_id"]

        if (
            event_id not in unique
            or item["confidence"] > unique[event_id]["confidence"]
        ):
            unique[event_id] = item

    candidates = list(unique.values())

    # Prefer signals at or above 50.
    valid = [
        x for x in candidates
        if x["confidence"] >= MIN_CONFIDENCE
    ]

    if valid:
        candidates = valid

    ticket = build_ticket(candidates)

    if not ticket:

        telegram(
            header("📭 AUCUN MATCH EXPLOITABLE")
            + "Aucune rencontre exploitable n'a été trouvée.\n"
              "TESLA attendra le prochain cycle."
        )

        return

    # If no selection passes the threshold, send the best
    # available candidate, clearly marked as unvalidated.
    if not ai_review(ticket["legs"]):

        telegram(
            header("⚠️ CONTRÔLE IA NON VALIDÉ")
            + "Le contrôle Gemini/Groq n'a pas été "
              "confirmé par les deux services.\n"
              "Le ticket ne sera pas publié comme validé."
        )

        return

    publish_signal(db, ticket)


# =========================================================
# RESULT TRACKING
# =========================================================

def result_winner(fixture):

    # SportScore fixtures expose home_score / away_score.
    # Some sports may expose a different score structure.
    # Unknown formats must remain pending.

    winner = fixture.get("winner")

    if isinstance(winner, dict):
        winner = winner.get("name") or winner.get("team")

    if winner:
        return str(winner)

    home_score = fixture.get("home_score")
    away_score = fixture.get("away_score")

    try:

        home_score = float(home_score)
        away_score = float(away_score)

    except (TypeError, ValueError):
        return None

    if home_score > away_score:
        return fixture_names(fixture)[0]

    if away_score > home_score:
        return fixture_names(fixture)[1]

    return "Draw"


def is_finished(fixture):

    status = str(
        fixture.get("status", "")
    ).lower()

    return any(
        word in status
        for word in (
            "finished",
            "complete",
            "ended",
            "full_time",
            "ft"
        )
    )


def check_results(db):

    pending = {
        key: value
        for key, value in db["tickets"].items()
        if value["status"] == "pending"
    }

    if not pending:
        return

    dates = [
        datetime.now(timezone.utc).date() - timedelta(days=i)
        for i in range(3)
    ]

    fixtures = {
        "football": [],
        "basketball": [],
        "tennis": []
    }

    for sport in fixtures:

        for day in dates:

            try:

                fixtures[sport].extend(
                    get_fixtures(
                        sport,
                        day.isoformat()
                    )
                )

            except Exception:
                logging.exception(
                    "Résultats indisponibles : %s",
                    sport
                )

    for ticket_id, ticket in pending.items():

        lost = False
        all_finished = True
        lines = []

        for leg in ticket["legs"]:

            fixture = find_fixture(
                leg["home"],
                leg["away"],
                fixtures[leg["sport"]]
            )

            if not fixture or not is_finished(fixture):

                all_finished = False

                lines.append(
                    f"⏳ {html.escape(leg['home'])} : en attente"
                )

                continue

            winner = result_winner(fixture)

            if winner is None:

                all_finished = False

                lines.append(
                    f"❔ {html.escape(leg['home'])} : score indisponible"
                )

                continue

            selected = normalize(leg["selection"])
            winner_norm = normalize(winner)

            if selected == winner_norm:

                lines.append(
                    f"✅ {html.escape(leg['home'])} : gagné"
                )

            else:

                lost = True

                lines.append(
                    f"❌ {html.escape(leg['home'])} : perdu"
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
                + f"💎 Cote : {ticket['odds']}\n"
                + f"📊 Confiance initiale : {ticket['confidence']}/100\n\n"
                + "\n".join(lines)
            )

            db["reported_results"].append(ticket_id)

        save_db(db)


# =========================================================
# MAIN
# =========================================================

def main():

    db = load_db()

    # Results are checked at every workflow execution.
    check_results(db)

    now = datetime.now(timezone.utc)

    last = db.get("last_analysis")

    should_analyze = True

    if last:

        try:

            previous = datetime.fromisoformat(last)

            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)

            elapsed = (
                now - previous
            ).total_seconds()

            if elapsed < ANALYSIS_INTERVAL:
                should_analyze = False

        except Exception:
            logging.exception("Date d'analyse invalide")

    if should_analyze:

        logging.info("Lancement de l'analyse TESLA V2")

        run_analysis(db)

        db["last_analysis"] = now.isoformat()

        save_db(db)

    else:

        logging.info(
            "Analyse non nécessaire. Suivi des résultats effectué."
        )


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        logging.exception("Erreur TESLA")

        try:

            telegram(
                header("🚨 ERREUR SYSTÈME")
                + f"<code>{html.escape(type(error).__name__)}</code>\n"
                + html.escape(str(error)[:1000])
            )

        except Exception:
            pass

        raise