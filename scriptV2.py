import os
import re
import json
import html
import math
import logging
import requests

from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

# ==========================================================
# TESLA SPORTS INTELLIGENCE V2
# ==========================================================

BOT_NAME = "TESLA SPORTS INTELLIGENCE"
VERSION = "2.0"

BASE_DIR = Path(__file__).resolve().parent

# IMPORTANT : base V2 indépendante de V1
DB_FILE = BASE_DIR / "tesla_v2_data.json"

ODDS_URL = "https://api.the-odds-api.com/v4"
SPORTSCORE_URL = "https://sportscore.com/api/v1"

MIN_CONFIDENCE = 50
MIN_TOTAL_ODDS = 2.00
MAX_SELECTIONS = 10

ANALYSIS_INTERVAL = 7200
REGION = os.getenv("ODDS_REGIONS", "eu")

TZ = timezone(timedelta(hours=3))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

session = requests.Session()

session.headers.update({
    "User-Agent": "TESLA-Sports-Intelligence/2.0"
})


# ==========================================================
# CONFIGURATION
# ==========================================================

def get_secret(name, required=True):

    value = os.getenv(name, "").strip()

    if required and not value:
        raise RuntimeError(
            f"Secret GitHub manquant : {name}"
        )

    return value


ODDS_KEY = get_secret("ODDS_API_KEY")
TELEGRAM_TOKEN = get_secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT = get_secret("TELEGRAM_CHAT_ID")

SPORTSCORE_KEY = get_secret(
    "SPORTSCORE_API_KEY",
    required=False
)

GEMINI_KEY = get_secret(
    "GEMINI_API_KEY",
    required=False
)

GROQ_KEY = get_secret(
    "GROQ_API_KEY",
    required=False
)


# ==========================================================
# TELEGRAM
# ==========================================================

def telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    chunks = [
        message[i:i + 3900]
        for i in range(0, len(message), 3900)
    ]

    for chunk in chunks:

        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=30
        )

        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):
            raise RuntimeError(
                "Erreur Telegram : "
                + str(result)
            )


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


# ==========================================================
# DATABASE
# ==========================================================

def load_db():

    if not DB_FILE.exists():

        return {
            "last_analysis": None,
            "tickets": {},
            "reported_results": []
        }

    try:

        data = json.loads(
            DB_FILE.read_text(
                encoding="utf-8"
            )
        )

        data.setdefault("last_analysis", None)
        data.setdefault("tickets", {})
        data.setdefault("reported_results", [])

        return data

    except Exception:

        logging.exception(
            "Impossible de lire la base V2"
        )

        raise


def save_db(db):

    DB_FILE.write_text(
        json.dumps(
            db,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )


# ==========================================================
# HTTP API
# ==========================================================

def get_json(url, params=None, headers=None):

    response = session.get(
        url,
        params=params,
        headers=headers,
        timeout=40
    )

    response.raise_for_status()

    return response.json()


def post_json(url, payload, headers=None):

    response = session.post(
        url,
        json=payload,
        headers=headers,
        timeout=40
    )

    response.raise_for_status()

    return response.json()


# ==========================================================
# SPORT DISCOVERY
# ==========================================================

def discover_sports():

    data = get_json(
        f"{ODDS_URL}/sports",
        {
            "apiKey": ODDS_KEY
        }
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

        if key.startswith("soccer_"):
            result["football"].append(key)

        elif "basketball" in key or "basketball" in group:
            result["basketball"].append(key)

        elif "tennis" in key or "tennis" in group:
            result["tennis"].append(key)

    # Limitation volontaire pour préserver le quota.
    for sport in result:

        result[sport] = result[sport][:5]

    return result


# ==========================================================
# TEAM NORMALIZATION
# ==========================================================

def normalize(value):

    value = str(value or "").lower()

    value = re.sub(
        r"\b(fc|cf|sc|afc|bc|club)\b",
        "",
        value
    )

    return re.sub(
        r"[^a-z0-9]",
        "",
        value
    )


def similarity(a, b):

    return SequenceMatcher(
        None,
        normalize(a),
        normalize(b)
    ).ratio()


def fixture_names(fixture):

    home = (
        fixture.get("home_team")
        or fixture.get("home")
        or fixture.get("participant1")
        or ""
    )

    away = (
        fixture.get("away_team")
        or fixture.get("away")
        or fixture.get("participant2")
        or ""
    )

    if isinstance(home, dict):
        home = home.get("name", "")

    if isinstance(away, dict):
        away = away.get("name", "")

    return str(home), str(away)


# ==========================================================
# SPORT SCORE
# ==========================================================

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


# ==========================================================
# ODDS ANALYSIS
# ==========================================================

def get_odds(sport_key):

    return get_json(
        f"{ODDS_URL}/sports/{sport_key}/odds",
        {
            "apiKey": ODDS_KEY,
            "regions": REGION,
            "markets": "h2h",
            "oddsFormat": "decimal"
        }
    )


def parse_event(event, sport, fixtures):

    home = event.get("home_team", "")
    away = event.get("away_team", "")

    if not home or not away:
        return []

    fixture = find_fixture(
        home,
        away,
        fixtures
    )

    if not fixture:
        return []

    commence = event.get("commence_time")

    if not commence:
        return []

    try:

        start = datetime.fromisoformat(
            commence.replace("Z", "+00:00")
        )

        if start <= datetime.now(timezone.utc):
            return []

    except Exception:
        return []

    markets = {}

    for bookmaker in event.get("bookmakers", []):

        for market in bookmaker.get("markets", []):

            if market.get("key") != "h2h":
                continue

            outcomes = market.get("outcomes", [])

            valid = [
                x for x in outcomes
                if isinstance(x.get("price"), (int, float))
                and x["price"] > 1
            ]

            if len(valid) < 2:
                continue

            implied = [
                1 / x["price"]
                for x in valid
            ]

            margin = sum(implied)

            if margin <= 0:
                continue

            for outcome, probability in zip(
                valid,
                implied
            ):

                name = outcome.get("name", "")

                if not name:
                    continue

                markets.setdefault(
                    name,
                    []
                ).append({
                    "odds": float(outcome["price"]),
                    "probability": probability / margin
                })

    candidates = []

    for selection, values in markets.items():

        odds_values = [
            x["odds"] for x in values
        ]

        probabilities = [
            x["probability"] for x in values
        ]

        average_odds = sum(
            odds_values
        ) / len(odds_values)

        average_probability = sum(
            probabilities
        ) / len(probabilities)

        if not 1.10 <= average_odds <= 10:
            continue

        dispersion = (
            max(probabilities)
            - min(probabilities)
        )

        # --------------------------------------------------
        # SCORE DE QUALITE DES DONNEES
        # Ce score n'est PAS une probabilité de gain.
        # --------------------------------------------------

        bookmaker_score = min(
            20,
            len(values) * 4
        )

        agreement_score = max(
            0,
            20 - dispersion * 100
        )

        fixture_score = 20

        freshness_score = 20

        market_score = min(
            20,
            average_probability * 20
        )

        confidence = round(
            bookmaker_score
            + agreement_score
            + fixture_score
            + freshness_score
            + market_score
        )

        confidence = max(
            0,
            min(100, confidence)
        )

        candidates.append({

            "sport": sport,

            "event_id": event.get("id"),

            "home": home,

            "away": away,

            "selection": selection,

            "odds": round(
                average_odds,
                2
            ),

            "market_probability": round(
                average_probability,
                4
            ),

            "confidence": confidence,

            "bookmakers": len(values),

            "start": commence,

            "fixture_id": fixture.get("id")

        })

    return candidates


# ==========================================================
# AI AUDIT - ADVISORY ONLY
# ==========================================================

def ai_review(ticket):

    prompt = (
        "You are a strict sports data auditor. "
        "Do not invent statistics or probabilities. "
        "Check whether the selections contain obvious "
        "contradictions, duplicate matches or missing data. "
        "Return a short advisory opinion. "
        "Do not decide whether the ticket is published. "
        "Ticket: "
        + json.dumps(
            ticket,
            ensure_ascii=False
        )
    )

    opinions = []

    if GROQ_KEY:

        try:

            result = post_json(
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
                    "Authorization": (
                        f"Bearer {GROQ_KEY}"
                    )
                }
            )

            text = result[
                "choices"
            ][0][
                "message"
            ][
                "content"
            ]

            opinions.append(
                "Groq : " + text[:700]
            )

        except Exception:

            logging.exception(
                "Erreur audit Groq"
            )

            opinions.append(
                "Groq : indisponible"
            )

    if GEMINI_KEY:

        try:

            model = os.getenv(
                "GEMINI_MODEL",
                "gemini-2.5-flash"
            )

            result = post_json(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                + model
                + ":generateContent",
                {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": prompt
                                }
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

            text = result[
                "candidates"
            ][0][
                "content"
            ][
                "parts"
            ][0][
                "text"
            ]

            opinions.append(
                "Gemini : " + text[:700]
            )

        except Exception:

            logging.exception(
                "Erreur audit Gemini"
            )

            opinions.append(
                "Gemini : indisponible"
            )

    return opinions


# ==========================================================
# TICKET GENERATION
# ==========================================================

def build_ticket(candidates):

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: (
            x["confidence"],
            x["bookmakers"],
            x["market_probability"]
        ),
        reverse=True
    )

    # Éliminer les doublons d'événements.
    unique = {}

    for candidate in candidates:

        event_id = candidate["event_id"]

        if not event_id:
            continue

        if event_id not in unique:

            unique[event_id] = candidate

    candidates = list(unique.values())

    # Priorité aux candidats qui atteignent le seuil.
    qualified = [
        x for x in candidates
        if x["confidence"] >= MIN_CONFIDENCE
    ]

    pool = qualified if qualified else candidates

    # Le meilleur candidat est toujours conservé.
    selected = [pool[0]]

    total_odds = pool[0]["odds"]

    # Construire un combiné si la cote simple est insuffisante.
    if total_odds < MIN_TOTAL_ODDS:

        for candidate in pool[1:]:

            if len(selected) >= MAX_SELECTIONS:
                break

            selected.append(candidate)

            total_odds *= candidate["odds"]

            if total_odds >= MIN_TOTAL_ODDS:
                break

    mode = (
        "SIMPLE"
        if len(selected) == 1
        else "COMBINÉ"
    )

    return {
        "mode": mode,
        "legs": selected,
        "odds": round(total_odds, 2)
    }


# ==========================================================
# SIGNAL PUBLICATION
# ==========================================================

def ticket_identifier(ticket):

    parts = sorted(
        str(x["event_id"])
        + ":"
        + normalize(x["selection"])
        for x in ticket["legs"]
    )

    raw = "|".join(parts)

    import hashlib

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()[:16]


def publish_signal(db, ticket):

    confidence = round(
        sum(
            x["confidence"]
            for x in ticket["legs"]
        ) / len(ticket["legs"])
    )

    if confidence >= 85:
        classification = "🟢 TRÈS FORTE"

    elif confidence >= 75:
        classification = "🟢 FORTE"

    elif confidence >= 65:
        classification = "🟡 BONNE"

    elif confidence >= 50:
        classification = "🟠 MODÉRÉE"

    else:
        classification = "🔴 SOUS LE SEUIL — NON VALIDÉ"

    identifier = ticket_identifier(ticket)

    # Éviter de renvoyer le même ticket.
    if identifier in db["tickets"]:

        logging.info(
            "Ticket déjà publié : %s",
            identifier
        )

        return

    opinions = ai_review(ticket["legs"])

    lines = [
        header("🎯 NOUVEAU PRONOSTIC"),

        f"🆔 <code>{identifier}</code>",

        f"📌 Mode : <b>{ticket['mode']}</b>",

        f"📊 Indice de confiance : <b>{confidence}/100</b>",

        f"🏷️ Classification : {classification}",

        ""
    ]

    for index, leg in enumerate(
        ticket["legs"],
        1
    ):

        lines.extend([

            f"<b>SÉLECTION {index} — {leg['sport'].upper()}</b>",

            "⚔️ "
            + html.escape(leg["home"])
            + " vs "
            + html.escape(leg["away"]),

            "🎯 Pronostic : <b>"
            + html.escape(leg["selection"])
            + "</b>",

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

        ""
    ])

    if ticket["odds"] < MIN_TOTAL_ODDS:

        lines.append(
            "⚠️ Cote totale inférieure à 2.00 : "
            "ticket informatif, non conforme au seuil."
        )

    if opinions:

        lines.append("<b>🤖 AVIS IA</b>")

        for opinion in opinions:

            lines.append(
                html.escape(opinion)
            )

    else:

        lines.append(
            "🤖 Audit IA : non configuré."
        )

    lines.extend([

        "",

        "ℹ️ L'indice mesure la qualité des données, "
        "pas une probabilité de gain.",

        "⚠️ Aucun gain n'est garanti."

    ])

    telegram(
        "\n".join(lines)
    )

    db["tickets"][identifier] = {

        "mode": ticket["mode"],

        "legs": ticket["legs"],

        "odds": ticket["odds"],

        "confidence": confidence,

        "status": "pending",

        "created_at": datetime.now(
            timezone.utc
        ).isoformat()

    }

    save_db(db)


# ==========================================================
# ANALYSIS
# ==========================================================

def run_analysis(db):

    logging.info(
        "Démarrage analyse TESLA V2"
    )

    sports = discover_sports()

    today = datetime.now(
        timezone.utc
    ).date()

    dates = [
        today + timedelta(days=i)
        for i in range(3)
    ]

    fixtures = {
        "football": [],
        "basketball": [],
        "tennis": []
    }

    for sport in fixtures:

        for date in dates:

            try:

                fixtures[sport].extend(
                    get_fixtures(
                        sport,
                        date.isoformat(),
                        "upcoming"
                    )
                )

            except Exception:

                logging.exception(
                    "SportScore indisponible : %s",
                    sport
                )

    candidates = []

    for sport, keys in sports.items():

        for key in keys:

            try:

                events = get_odds(key)

                for event in events:

                    candidates.extend(
                        parse_event(
                            event,
                            sport,
                            fixtures[sport]
                        )
                    )

            except Exception:

                logging.exception(
                    "Erreur Odds API : %s",
                    key
                )

    logging.info(
        "%s candidats trouvés",
        len(candidates)
    )

    ticket = build_ticket(candidates)

    if not ticket:

        telegram(
            header("📭 AUCUN MATCH EXPLOITABLE")
            + "Aucune rencontre avec des données "
              "suffisantes n'a été trouvée.\n\n"
              "Prochaine analyse dans environ 2 heures."
        )

        return

    publish_signal(
        db,
        ticket
    )


# ==========================================================
# RESULT TRACKING
# ==========================================================

def fixture_status(fixture):

    return str(
        fixture.get("status", "")
    ).lower()


def is_finished(fixture):

    status = fixture_status(fixture)

    return any(
        x in status
        for x in (
            "finished",
            "complete",
            "ended",
            "full_time",
            "ft"
        )
    )


def extract_winner(fixture, sport):

    # Priorité au vainqueur explicitement fourni.
    winner = fixture.get("winner")

    if isinstance(winner, dict):

        winner = (
            winner.get("name")
            or winner.get("team")
        )

    if winner:

        return str(winner)

    # Le tennis ne doit pas être interprété à partir
    # d'un simple score global.
    if sport == "tennis":
        return None

    home_score = fixture.get("home_score")
    away_score = fixture.get("away_score")

    if isinstance(home_score, dict):
        home_score = home_score.get("total")

    if isinstance(away_score, dict):
        away_score = away_score.get("total")

    try:

        home_score = float(home_score)
        away_score = float(away_score)

    except (TypeError, ValueError):

        return None

    home, away = fixture_names(fixture)

    if home_score > away_score:
        return home

    if away_score > home_score:
        return away

    if sport == "football":
        return "Draw"

    return None


def check_results(db):

    pending = {

        key: value

        for key, value in db["tickets"].items()

        if value["status"] == "pending"

    }

    if not pending:
        return

    today = datetime.now(
        timezone.utc
    ).date()

    dates = [
        today - timedelta(days=i)
        for i in range(3)
    ]

    fixtures = {
        "football": [],
        "basketball": [],
        "tennis": []
    }

    for sport in fixtures:

        for date in dates:

            try:

                fixtures[sport].extend(
                    get_fixtures(
                        sport,
                        date.isoformat()
                    )
                )

            except Exception:

                logging.exception(
                    "Erreur récupération résultats : %s",
                    sport
                )

    for ticket_id, ticket in pending.items():

        lost = False
        all_finished = True

        messages = []

        for leg in ticket["legs"]:

            fixture = find_fixture(
                leg["home"],
                leg["away"],
                fixtures[leg["sport"]]
            )

            if not fixture or not is_finished(fixture):

                all_finished = False

                messages.append(
                    "⏳ "
                    + html.escape(leg["home"])
                    + " : résultat en attente"
                )

                continue

            winner = extract_winner(
                fixture,
                leg["sport"]
            )

            if winner is None:

                all_finished = False

                messages.append(
                    "❔ "
                    + html.escape(leg["home"])
                    + " : résultat non interprétable"
                )

                continue

            selected = normalize(
                leg["selection"]
            )

            actual = normalize(winner)

            if selected == actual:

                messages.append(
                    "✅ "
                    + html.escape(leg["home"])
                    + " : gagné"
                )

            else:

                lost = True

                messages.append(
                    "❌ "
                    + html.escape(leg["home"])
                    + " : perdu"
                )

        # Une seule sélection perdue suffit à perdre le combiné.
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
                + f"📊 Indice initial : "
                  f"{ticket['confidence']}/100\n\n"
                + "\n".join(messages)
            )

            db["reported_results"].append(
                ticket_id
            )

        save_db(db)


# ==========================================================
# MAIN
# ==========================================================

def main():

    db = load_db()

    # Vérification des résultats à chaque exécution.
    check_results(db)

    now = datetime.now(
        timezone.utc
    )

    last = db.get("last_analysis")

    should_analyze = True

    if last:

        try:

            previous = datetime.fromisoformat(
                last
            )

            if previous.tzinfo is None:

                previous = previous.replace(
                    tzinfo=timezone.utc
                )

            elapsed = (
                now - previous
            ).total_seconds()

            if elapsed < ANALYSIS_INTERVAL:

                should_analyze = False

        except Exception:

            logging.exception(
                "Date précédente invalide"
            )

    if should_analyze:

        # Enregistrer le début du cycle avant l'analyse.
        # Cela évite de relancer l'analyse toutes les 15 min
        # si une API rencontre une erreur.
        db["last_analysis"] = now.isoformat()

        save_db(db)

        run_analysis(db)

    else:

        logging.info(
            "Pas de nouvelle analyse nécessaire."
        )


if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        logging.exception(
            "Erreur générale TESLA V2"
        )

        try:

            telegram(
                header("🚨 ERREUR SYSTÈME")
                + "<code>"
                + html.escape(
                    type(error).__name__
                )
                + "</code>\n"
                + html.escape(
                    str(error)[:1000]
                )
            )

        except Exception:

            logging.exception(
                "Impossible d'envoyer l'erreur Telegram"
            )

        raise