import os
import re
import json
import html
import math
import time
import hashlib
import logging
import requests

from pathlib import Path
from datetime import datetime, timezone, timedelta
from itertools import combinations

# ============================================================
# TESLA SPORTS INTELLIGENCE V2
# FOOTBALL | BASKETBALL | TENNIS
# ============================================================

BOT_NAME = "TESLA SPORTS INTELLIGENCE"
VERSION = "2.0"

BASE_DIR = Path(__file__).resolve().parent

DB_FILE = BASE_DIR / "tesla_v2_data.json"

ODDS_URL = "https://api.the-odds-api.com/v4"

# PARAMÈTRES PRINCIPAUX
MIN_TOTAL_ODDS = 2.00
MAX_TOTAL_ODDS = 3.00

MIN_CONFIDENCE = 50

MIN_SELECTIONS = 1
MAX_SELECTIONS = 10

ANALYSIS_INTERVAL = 7200

REGION = os.getenv("ODDS_REGIONS", "eu")

TZ = timezone(timedelta(hours=3))

MAX_SPORTS_PER_CATEGORY = 5
MAX_CANDIDATES = 14

REQUEST_TIMEOUT = 35

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

session = requests.Session()

session.headers.update({
    "User-Agent": "TESLA-Sports-Intelligence/2.0"
})


# ============================================================
# CONFIGURATION
# ============================================================

def get_secret(name, required=True):

    value = os.getenv(name, "").strip()

    if required and not value:
        raise RuntimeError(
            f"Secret GitHub manquant : {name}"
        )

    return value


ODDS_KEY = get_secret("ODDS_API_KEY")

TELEGRAM_TOKEN = get_secret(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT = get_secret(
    "TELEGRAM_CHAT_ID"
)

GEMINI_KEY = get_secret(
    "GEMINI_API_KEY",
    required=False
)

GROQ_KEY = get_secret(
    "GROQ_API_KEY",
    required=False
)


# ============================================================
# TIME
# ============================================================

def now_utc():

    return datetime.now(timezone.utc)


def now_local():

    return datetime.now(TZ)


def iso_now():

    return now_utc().isoformat()


# ============================================================
# DATABASE
# ============================================================

def empty_database():

    return {
        "version": VERSION,
        "last_analysis": None,
        "last_successful_analysis": None,
        "tickets": {},
        "reported_results": [],
        "statistics": {
            "analyses": 0,
            "signals": 0,
            "won": 0,
            "lost": 0,
            "pending": 0
        }
    }


def load_db():

    if not DB_FILE.exists():

        return empty_database()

    try:

        data = json.loads(
            DB_FILE.read_text(
                encoding="utf-8"
            )
        )

        defaults = empty_database()

        for key, value in defaults.items():

            if key not in data:
                data[key] = value

        return data

    except Exception:

        logging.exception(
            "Erreur lecture base V2"
        )

        raise


def save_db(db):

    temporary = DB_FILE.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(
            db,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    temporary.replace(DB_FILE)


# ============================================================
# HTTP REQUESTS
# ============================================================

def get_json(url, params=None):

    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()


def post_json(url, payload, headers=None):

    response = session.post(
        url,
        json=payload,
        headers=headers,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    url = (
        "https://api.telegram.org/"
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

    result = response.json()

    if not result.get("ok"):

        raise RuntimeError(
            "Erreur Telegram : "
            + str(result)
        )


def header(title):

    now = now_local()

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


# ============================================================
# SPORTS DISCOVERY
# ============================================================

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

        group = item.get(
            "group", ""
        ).lower()

        if key.startswith("soccer_"):

            result["football"].append(key)

        elif "basketball" in key or "basketball" in group:

            result["basketball"].append(key)

        elif "tennis" in key or "tennis" in group:

            result["tennis"].append(key)

    for sport in result:

        result[sport] = result[sport][
            :MAX_SPORTS_PER_CATEGORY
        ]

    logging.info(
        "Sports disponibles : %s",
        result
    )

    return result


# ============================================================
# ODDS COLLECTION
# ============================================================

def get_odds(sport_key):

    return get_json(
        f"{ODDS_URL}/sports/{sport_key}/odds",
        {
            "apiKey": ODDS_KEY,
            "regions": REGION,
            "markets": "h2h",
            "oddsFormat": "decimal",
            "dateFormat": "iso"
        }
    )


# ============================================================
# NORMALIZATION
# ============================================================

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


# ============================================================
# EVENT ANALYSIS
# ============================================================

def analyze_event(event, sport):

    event_id = event.get("id")

    home = event.get("home_team")

    away = event.get("away_team")

    commence = event.get("commence_time")

    if not all([
        event_id,
        home,
        away,
        commence
    ]):

        return []

    try:

        start = datetime.fromisoformat(
            commence.replace("Z", "+00:00")
        )

        if start <= now_utc():
            return []

    except Exception:

        return []

    outcomes = {}

    for bookmaker in event.get(
        "bookmakers", []
    ):

        for market in bookmaker.get(
            "markets", []
        ):

            if market.get("key") != "h2h":
                continue

            valid = [

                x for x in market.get(
                    "outcomes", []
                )

                if isinstance(
                    x.get("price"),
                    (int, float)
                )

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

                name = outcome.get("name")

                if not name:
                    continue

                outcomes.setdefault(
                    name,
                    []
                ).append({

                    "odds": float(
                        outcome["price"]
                    ),

                    "probability": (
                        probability / margin
                    )

                })

    candidates = []

    for selection, values in outcomes.items():

        odds_values = [
            x["odds"]
            for x in values
        ]

        probabilities = [
            x["probability"]
            for x in values
        ]

        average_odds = (
            sum(odds_values)
            / len(odds_values)
        )

        average_probability = (
            sum(probabilities)
            / len(probabilities)
        )

        # Cote individuelle exploitable.
        if not 1.10 <= average_odds <= MAX_TOTAL_ODDS:
            continue

        dispersion = (
            max(probabilities)
            - min(probabilities)
        )

        # SCORE DE QUALITÉ DES DONNÉES.
        # Ce score n'est PAS une probabilité de gain.

        bookmaker_score = min(
            20,
            len(values) * 4
        )

        agreement_score = max(
            0,
            20 - dispersion * 100
        )

        freshness_score = 20

        fixture_score = 20

        market_score = min(
            20,
            average_probability * 20
        )

        confidence = round(
            bookmaker_score
            + agreement_score
            + freshness_score
            + fixture_score
            + market_score
        )

        confidence = max(
            0,
            min(100, confidence)
        )

        candidates.append({

            "sport": sport,

            "sport_key": event.get(
                "sport_key"
            ),

            "event_id": event_id,

            "home": home,

            "away": away,

            "selection": selection,

            "odds": round(
                average_odds,
                2
            ),

            "market_probability": round(
                average_probability,
                5
            ),

            "confidence": confidence,

            "bookmakers": len(values),

            "start": commence

        })

    return candidates


# ============================================================
# DUPLICATE PROTECTION
# ============================================================

def ticket_identifier(ticket):

    parts = sorted(

        str(x["event_id"])
        + ":"
        + normalize(x["selection"])

        for x in ticket["legs"]

    )

    raw = "|".join(parts)

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()[:16]


# ============================================================
# TICKET GENERATION
# ============================================================

def build_ticket(candidates):

    if not candidates:
        return None

    # Une seule sélection par rencontre.
    unique = {}

    for candidate in candidates:

        event_id = candidate.get("event_id")

        if not event_id:
            continue

        current = unique.get(event_id)

        if current is None:

            unique[event_id] = candidate

        elif candidate["confidence"] > current["confidence"]:

            unique[event_id] = candidate

    candidates = list(
        unique.values()
    )

    candidates.sort(
        key=lambda x: (
            x["confidence"],
            x["market_probability"],
            x["bookmakers"]
        ),
        reverse=True
    )

    candidates = candidates[
        :MAX_CANDIDATES
    ]

    best_ticket = None

    best_score = -999999

    # Recherche de tickets simples et combinés.
    for number in range(
        MIN_SELECTIONS,
        min(
            MAX_SELECTIONS,
            len(candidates)
        ) + 1
    ):

        for selected in combinations(
            candidates,
            number
        ):

            total_odds = math.prod(
                x["odds"]
                for x in selected
            )

            if total_odds < MIN_TOTAL_ODDS:
                continue

            if total_odds > MAX_TOTAL_ODDS:
                continue

            average_confidence = sum(
                x["confidence"]
                for x in selected
            ) / len(selected)

            probability_score = sum(
                math.log(
                    max(
                        x["market_probability"],
                        0.000001
                    )
                )
                for x in selected
            )

            # Favoriser les tickets de bonne qualité
            # sans dépasser la cote maximale.
            score = (
                average_confidence
                + probability_score * 10
                - abs(total_odds - 2.30) * 5
            )

            if score > best_score:

                best_score = score

                best_ticket = {

                    "legs": list(selected),

                    "odds": round(
                        total_odds,
                        2
                    ),

                    "mode": (
                        "SIMPLE"
                        if len(selected) == 1
                        else "COMBINÉ"
                    )

                }

    return best_ticket


# ============================================================
# AI AUDIT
# ============================================================

def ai_review(ticket):

    prompt = (
        "You are a sports data consistency auditor. "
        "Check only duplicate matches, contradictory "
        "selections, missing information and obvious "
        "data inconsistencies. Do not invent statistics "
        "or probabilities. Do not claim that a bet is safe. "
        "Return a short advisory opinion.\n\n"
        + json.dumps(
            ticket,
            ensure_ascii=False
        )
    )

    opinions = []

    # GROQ
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

            answer = result[
                "choices"
            ][0][
                "message"
            ][
                "content"
            ]

            opinions.append(
                "Groq : " + answer[:500]
            )

        except Exception:

            logging.exception(
                "Erreur Groq"
            )

            opinions.append(
                "Groq : indisponible"
            )

    # GEMINI
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

            answer = result[
                "candidates"
            ][0][
                "content"
            ][
                "parts"
            ][0][
                "text"
            ]

            opinions.append(
                "Gemini : " + answer[:500]
            )

        except Exception:

            logging.exception(
                "Erreur Gemini"
            )

            opinions.append(
                "Gemini : indisponible"
            )

    return opinions


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def create_signal_message(
    ticket,
    confidence,
    identifier,
    opinions
):

    if confidence >= 85:

        classification = "🟢 TRÈS FORTE"

    elif confidence >= 75:

        classification = "🟢 FORTE"

    elif confidence >= 65:

        classification = "🟡 BONNE"

    elif confidence >= 50:

        classification = "🟠 MODÉRÉE"

    else:

        classification = (
            "🔴 SOUS LE SEUIL — NON VALIDÉ"
        )

    lines = [

        header("🎯 NOUVEAU PRONOSTIC"),

        f"🆔 <code>{identifier}</code>",

        f"📌 Mode : <b>{ticket['mode']}</b>",

        f"📊 Indice de qualité : "
        f"<b>{confidence}/100</b>",

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

            "🎯 Choix : <b>"
            + html.escape(leg["selection"])
            + "</b>",

            f"📈 Cote : <b>{leg['odds']:.2f}</b>",

            f"🏦 Bookmakers : {leg['bookmakers']}",

            f"📅 Début : {leg['start']}",

            f"📊 Qualité des données : "
            f"{leg['confidence']}/100",

            ""

        ])

    lines.extend([

        "━━━━━━━━━━━━━━━━━━━━",

        f"💎 <b>COTE TOTALE : {ticket['odds']:.2f}</b>",

        "━━━━━━━━━━━━━━━━━━━━",

        "",

        "🔎 CONTRÔLE :",

        "✅ Cote comprise entre 2.00 et 3.00",

        "✅ Événements distincts",

        "✅ Données bookmakers analysées",

        ""

    ])

    if opinions:

        lines.append("<b>🤖 AUDIT IA</b>")

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

        "ℹ️ L'indice représente la qualité des données,",

        "pas une probabilité de gagner.",

        "⚠️ Aucun gain n'est garanti."

    ])

    return "\n".join(lines)


# ============================================================
# PUBLISH SIGNAL
# ============================================================

def publish_signal(db, ticket):

    confidence = round(
        sum(
            x["confidence"]
            for x in ticket["legs"]
        ) / len(ticket["legs"])
    )

    identifier = ticket_identifier(ticket)

    if identifier in db["tickets"]:

        logging.info(
            "Ticket déjà enregistré : %s",
            identifier
        )

        return False

    # Enregistrer AVANT envoi pour réduire
    # les risques de doublons en cas de crash.
    db["tickets"][identifier] = {

        "mode": ticket["mode"],

        "legs": ticket["legs"],

        "odds": ticket["odds"],

        "confidence": confidence,

        "status": "sending",

        "created_at": iso_now(),

        "message_sent": False

    }

    save_db(db)

    opinions = ai_review(
        ticket["legs"]
    )

    message = create_signal_message(
        ticket,
        confidence,
        identifier,
        opinions
    )

    try:

        telegram(message)

    except Exception:

        db["tickets"][identifier]["status"] = "send_failed"

        save_db(db)

        raise

    db["tickets"][identifier]["status"] = "pending"

    db["tickets"][identifier]["message_sent"] = True

    db["statistics"]["signals"] += 1

    save_db(db)

    logging.info(
        "Signal publié : %s",
        identifier
    )

    return True


# ============================================================
# NO SIGNAL NOTIFICATION
# ============================================================

def no_signal_notification(reason):

    telegram(

        header("📭 AUCUN MATCH EXPLOITABLE")

        + html.escape(reason)

        + "\n\n"

        + "🎯 Cote minimale : 2.00\n"

        + "🎯 Cote maximale : 3.00\n"

        + "📌 Sélections : 1 à 10\n\n"

        + "Le système ne force pas de pronostic.\n"

        + "Prochaine analyse dans environ 2 heures."

    )


# ============================================================
# ANALYSIS ENGINE
# ============================================================

def run_analysis(db):

    logging.info(
        "Démarrage analyse TESLA V2"
    )

    sports = discover_sports()

    candidates = []

    successful_requests = 0

    failed_requests = 0

    for sport, keys in sports.items():

        for key in keys:

            try:

                events = get_odds(key)

                successful_requests += 1

                logging.info(
                    "%s : %s événements",
                    key,
                    len(events)
                )

                for event in events:

                    results = analyze_event(
                        event,
                        sport
                    )

                    candidates.extend(
                        results
                    )

            except Exception:

                failed_requests += 1

                logging.exception(
                    "Erreur API pour %s",
                    key
                )

    if successful_requests == 0:

        raise RuntimeError(
            "Aucune requête de cotes n'a réussi."
        )

    logging.info(
        "Candidats trouvés : %s",
        len(candidates)
    )

    ticket = build_ticket(candidates)

    if not ticket:

        no_signal_notification(

            "Aucun ticket ne respecte actuellement "
            "les critères de sélection et de cote."

        )

        db["statistics"]["analyses"] += 1

        db["last_analysis"] = iso_now()

        db["last_successful_analysis"] = iso_now()

        save_db(db)

        return True

    published = publish_signal(
        db,
        ticket
    )

    db["statistics"]["analyses"] += 1

    db["last_analysis"] = iso_now()

    db["last_successful_analysis"] = iso_now()

    save_db(db)

    return True


# ============================================================
# RESULTS API
# ============================================================

def get_scores(sport_key, event_ids):

    if not event_ids:
        return {}

    data = get_json(

        f"{ODDS_URL}/sports/{sport_key}/scores",

        {
            "apiKey": ODDS_KEY,

            "daysFrom": 3,

            "dateFormat": "iso",

            "eventIds": ",".join(
                event_ids
            )
        }

    )

    if not isinstance(data, list):
        return {}

    return {
        item.get("id"): item
        for item in data
        if item.get("id")
    }


# ============================================================
# SCORE EXTRACTION
# ============================================================

def extract_scores(event):

    scores = event.get("scores")

    if not isinstance(scores, list):
        return None

    result = {}

    for item in scores:

        if not isinstance(item, dict):
            continue

        name = item.get("name")

        value = item.get("score")

        if name is None or value is None:
            continue

        try:

            result[normalize(name)] = float(value)

        except (
            TypeError,
            ValueError
        ):

            continue

    if len(result) < 2:
        return None

    return result


# ============================================================
# RESULT DETERMINATION
# ============================================================

def determine_result(leg, event):

    if not event.get("completed"):
        return None

    scores = extract_scores(event)

    if not scores:
        return None

    home = normalize(
        leg["home"]
    )

    away = normalize(
        leg["away"]
    )

    # Identification exacte des deux participants.
    home_score = scores.get(home)

    away_score = scores.get(away)

    if home_score is None or away_score is None:
        return None

    if home_score > away_score:

        winner = leg["home"]

    elif away_score > home_score:

        winner = leg["away"]

    else:

        winner = "Draw"

    selection = normalize(
        leg["selection"]
    )

    if selection == normalize(winner):

        return "won"

    if selection == normalize("Draw"):

        return (
            "won"
            if winner == "Draw"
            else "lost"
        )

    # Si le match est nul et que le sport ne
    # possède pas de sélection Draw, rester prudent.
    if winner == "Draw":

        if leg["sport"] == "football":

            return "lost"

        return None

    return "lost"


# ============================================================
# RESULTS NOTIFICATIONS
# ============================================================

def report_ticket_result(
    ticket_id,
    ticket
):

    status = ticket["status"]

    if status == "won":

        title = "🏆 COMBINÉ GAGNÉ"

    elif status == "lost":

        title = "❌ COMBINÉ PERDU"

    else:

        title = "📊 RÉSULTAT"

    lines = [

        header(title),

        f"🆔 <code>{ticket_id}</code>",

        f"💎 Cote : <b>{ticket['odds']:.2f}</b>",

        f"📊 Qualité initiale : "
        f"{ticket['confidence']}/100",

        ""

    ]

    for leg in ticket["legs"]:

        result = leg.get(
            "result",
            "pending"
        )

        if result == "won":

            icon = "✅ GAGNÉ"

        elif result == "lost":

            icon = "❌ PERDU"

        else:

            icon = "⏳ EN ATTENTE"

        lines.append(

            f"{html.escape(leg['home'])} "
            f"vs {html.escape(leg['away'])}\n"

            f"Choix : {html.escape(leg['selection'])}\n"

            f"Résultat : {icon}\n"

        )

    lines.extend([

        "━━━━━━━━━━━━━━━━━━━━",

        "TESLA V2 — SUIVI AUTOMATIQUE"

    ])

    telegram(
        "\n".join(lines)
    )


# ============================================================
# RESULT TRACKING ENGINE
# ============================================================

def check_results(db):

    pending_tickets = {

        key: value

        for key, value in db["tickets"].items()

        if value["status"] == "pending"

    }

    if not pending_tickets:
        return

    sports_to_check = {}

    for ticket in pending_tickets.values():

        for leg in ticket["legs"]:

            if leg.get("result") in (
                "won",
                "lost"
            ):
                continue

            sport_key = leg.get("sport_key")

            event_id = leg.get("event_id")

            if not sport_key or not event_id:
                continue

            sports_to_check.setdefault(
                sport_key,
                set()
            ).add(event_id)

    score_cache = {}

    for sport_key, event_ids in sports_to_check.items():

        try:

            score_cache[sport_key] = get_scores(
                sport_key,
                list(event_ids)
            )

        except Exception:

            logging.exception(
                "Erreur résultats : %s",
                sport_key
            )

            score_cache[sport_key] = {}

    for ticket_id, ticket in pending_tickets.items():

        lost = False

        all_finished = True

        for leg in ticket["legs"]:

            if leg.get("result") == "won":
                continue

            if leg.get("result") == "lost":

                lost = True

                continue

            sport_key = leg.get("sport_key")

            event_id = leg.get("event_id")

            event = score_cache.get(
                sport_key,
                {}
            ).get(event_id)

            if not event:

                all_finished = False

                continue

            result = determine_result(
                leg,
                event
            )

            if result is None:

                all_finished = False

                continue

            leg["result"] = result

            if result == "lost":

                lost = True

        if lost:

            ticket["status"] = "lost"

        elif all_finished:

            ticket["status"] = "won"

        else:

            ticket["status"] = "pending"

        if ticket["status"] in (
            "won",
            "lost"
        ):

            if ticket_id not in db["reported_results"]:

                # Sauvegarde avant notification.
                db["reported_results"].append(
                    ticket_id
                )

                if ticket["status"] == "won":

                    db["statistics"]["won"] += 1

                else:

                    db["statistics"]["lost"] += 1

                save_db(db)

                try:

                    report_ticket_result(
                        ticket_id,
                        ticket
                    )

                except Exception:

                    logging.exception(
                        "Erreur notification résultat"
                    )

    save_db(db)


# ============================================================
# STATISTICS
# ============================================================

def update_statistics(db):

    tickets = db["tickets"].values()

    db["statistics"]["pending"] = sum(

        1 for x in tickets

        if x["status"] == "pending"

    )


# ============================================================
# MAIN ENGINE
# ============================================================

def main():

    db = load_db()

    logging.info(
        "TESLA V2 démarré"
    )

    # 1. Vérifier les résultats à chaque exécution.
    check_results(db)

    # 2. Vérifier si une nouvelle analyse est nécessaire.
    last = db.get(
        "last_successful_analysis"
    )

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
                now_utc() - previous
            ).total_seconds()

            if elapsed < ANALYSIS_INTERVAL:

                should_analyze = False

        except Exception:

            logging.exception(
                "Date d'analyse précédente invalide"
            )

    if should_analyze:

        logging.info(
            "Nouvelle analyse nécessaire"
        )

        run_analysis(db)

    else:

        logging.info(
            "Analyse non nécessaire pour le moment"
        )

    update_statistics(db)

    save_db(db)

    logging.info(
        "TESLA V2 terminé"
    )


# ============================================================
# EXECUTION
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        logging.exception(
            "ERREUR TESLA V2"
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
                "Notification Telegram impossible"
            )

        raise