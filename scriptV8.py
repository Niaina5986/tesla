#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TESLA V8 — MATHEMATICAL INVESTIGATION ENGINE

Analyse des résultats virtuels :
- Recherche mathématique massive
- Opérations unaires et binaires
- BFS / DFS de combinaisons mathématiques
- Monte Carlo
- Analyse statistique
- Analyse des transitions
- Recherche de cycles et répétitions
- Tests chronologiques BLIND
- Comparaison avec un modèle aléatoire
- Historique JSON persistant
- Rapport Telegram

Les correspondances mathématiques sont des candidats à examiner,
pas une preuve de reconstruction du RNG interne.
"""

import os
import re
import json
import math
import time
import random
import hashlib
import itertools
import statistics
import urllib.request
import urllib.parse

from collections import Counter
from datetime import datetime, timezone


# ============================================================
# CONFIGURATION
# ============================================================

BASE = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE, "data", "tournaments")
OUT_DIR = os.path.join(BASE, "output")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

STATE_FILE = os.path.join(BASE, "tesla_state.json")

MAX_ROUNDS = 37
MAX_GOALS = 7
MAX_ABS = 1_000_000

MAX_TESTS_PER_RUN = max(
    1,
    int(os.getenv("TESLA_MAX_TESTS_PER_RUN", "1000000"))
)

MAX_RUNTIME_SECONDS = max(
    10,
    int(os.getenv("TESLA_MAX_RUNTIME_SECONDS", "420"))
)

MAX_INVENTORY = max(
    20,
    int(os.getenv("TESLA_MAX_INVENTORY", "300"))
)

RANDOM_SEED = int(
    os.getenv("TESLA_RANDOM_SEED", "42")
)

MONTE_CARLO_TRIALS = max(
    100,
    int(os.getenv("TESLA_MC_TRIALS", "10000"))
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ROUND_RE = re.compile(
    r"journ[eé]e\s*(\d+)",
    re.IGNORECASE
)

MATCH_RE = re.compile(
    r"^(.*?)\s+(\d+)\s*[-:]\s*(\d+)\s+(.*?)$"
)

random.seed(RANDOM_SEED)


# ============================================================
# TEMPS ET JSON
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value):

    try:
        value = float(value)

        if not math.isfinite(value):
            return None

        if abs(value) > MAX_ABS:
            return None

        return value

    except (ValueError, TypeError, OverflowError):
        return None


def clean(value):

    if abs(value) < 1e-10:
        return 0

    if abs(value - round(value)) < 1e-9:
        return int(round(value))

    return round(float(value), 8)


def save_json(path, data):

    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    os.replace(temp, path)


def load_json(path, default):

    if not os.path.exists(path):
        return default

    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)

    except Exception as error:
        print("JSON illisible :", path, error)
        return default


def digest(data):

    raw = json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False
    ).encode("utf-8")

    return hashlib.sha256(raw).hexdigest()


# ============================================================
# ETAT PERSISTANT
# ============================================================

def default_state():

    return {
        "version": "TESLA_V8",
        "total_tests": 0,
        "total_runs": 0,
        "total_candidates": 0,
        "total_rejected": 0,
        "operation_counts": {},
        "last_run": None,
        "last_run_tests": 0,
        "last_run_status": None,
        "data_hash": None,
        "best_candidates": []
    }


def load_state():

    state = load_json(
        STATE_FILE,
        default_state()
    )

    if not isinstance(state, dict):
        state = default_state()

    for key, value in default_state().items():

        state.setdefault(key, value)

    return state


def save_state(state):
    save_json(STATE_FILE, state)


# ============================================================
# BUDGET GLOBAL
# ============================================================

class Budget:

    def __init__(self):

        self.start = time.monotonic()

        self.tests = 0

        self.limit = MAX_TESTS_PER_RUN

        self.deadline = (
            self.start + MAX_RUNTIME_SECONDS
        )

    def available(self):

        return (
            self.tests < self.limit
            and time.monotonic() < self.deadline
        )

    def consume(self, amount=1):

        self.tests += amount

    def elapsed(self):

        return round(
            time.monotonic() - self.start,
            3
        )

    def status(self):

        if self.tests >= self.limit:
            return "TEST_LIMIT_REACHED"

        if time.monotonic() >= self.deadline:
            return "TIME_LIMIT_REACHED"

        return "RUNNING"


# ============================================================
# LECTURE DES TOURNOIS
# ============================================================

def parse_tournament(path):

    name = os.path.splitext(
        os.path.basename(path)
    )[0]

    current_round = None

    matches = []

    with open(
        path,
        encoding="utf-8-sig"
    ) as file:

        for raw in file:

            line = raw.strip()

            if not line:
                continue

            round_match = ROUND_RE.search(line)

            if round_match:

                current_round = int(
                    round_match.group(1)
                )

                if not 1 <= current_round <= MAX_ROUNDS:
                    current_round = None

                continue

            match = MATCH_RE.match(line)

            if not match or current_round is None:
                continue

            home, hg, ag, away = match.groups()

            hg = int(hg)
            ag = int(ag)

            if hg < 0 or ag < 0:
                continue

            matches.append({

                "tournament": name,

                "round": current_round,

                "home": home.strip(),

                "away": away.strip(),

                "hg": hg,

                "ag": ag,

                "score": f"{hg}-{ag}",

                "total": hg + ag,

                "difference": hg - ag,

                "btts": int(hg > 0 and ag > 0)

            })

    # Conserve l'ordre du fichier à l'intérieur
    # de chaque journée. Ne trie pas par nom d'équipe.

    indexed = list(enumerate(matches))

    indexed.sort(
        key=lambda item: (
            item[1]["round"],
            item[0]
        )
    )

    matches = [
        item[1] for item in indexed
    ]

    return name, matches


def load_all_tournaments():

    tournaments = {}

    if not os.path.isdir(DATA_DIR):
        return tournaments

    for filename in sorted(os.listdir(DATA_DIR)):

        if not filename.lower().endswith(".txt"):
            continue

        path = os.path.join(
            DATA_DIR,
            filename
        )

        try:

            name, matches = parse_tournament(path)

            if matches:
                tournaments[name] = matches

            print(
                f"Chargé : {name} — {len(matches)} matchs"
            )

        except Exception as error:

            print(
                f"Erreur lecture {filename} : {error}"
            )

    return tournaments


# ============================================================
# INVENTAIRE NUMERIQUE
# ============================================================

def build_inventory(matches):

    values = []

    def add(value, label):

        value = safe_float(value)

        if value is None:
            return

        values.append({
            "value": value,
            "label": label
        })

    for index, match in enumerate(matches):

        add(index + 1, "match_index")
        add(match["round"], "round")

        add(match["hg"], "home_goals")
        add(match["ag"], "away_goals")

        add(match["total"], "total_goals")
        add(match["difference"], "goal_difference")

        add(match["btts"], "btts")

    if matches:

        for field in (
            "hg",
            "ag",
            "total",
            "difference"
        ):

            sequence = [
                m[field] for m in matches
            ]

            add(
                statistics.mean(sequence),
                field + "_mean"
            )

            add(
                statistics.median(sequence),
                field + "_median"
            )

            add(
                statistics.pvariance(sequence),
                field + "_variance"
            )

            add(
                min(sequence),
                field + "_min"
            )

            add(
                max(sequence),
                field + "_max"
            )

            for lag in (1, 2, 3, 5):

                if len(sequence) > lag:

                    add(
                        sequence[-lag - 1],
                        field + "_lag_" + str(lag)
                    )

    # Déduplication en conservant les différentes
    # étiquettes disponibles.

    unique = {}

    for item in values:

        key = round(item["value"], 8)

        if key not in unique:
            unique[key] = item

    result = list(unique.values())

    # Échantillonnage réparti dans l'inventaire.
    # Évite de ne conserver que les premières valeurs.

    if len(result) > MAX_INVENTORY:

        step = len(result) / MAX_INVENTORY

        result = [
            result[int(i * step)]
            for i in range(MAX_INVENTORY)
        ]

    return result


# ============================================================
# OPERATIONS MATHEMATIQUES
# ============================================================

def calculate_operations(a, b):

    results = {}

    def put(name, value):

        value = safe_float(value)

        if value is not None:
            results[name] = value

    put("ADD", a + b)

    put("SUB", a - b)

    put("REVERSE_SUB", b - a)

    put("MUL", a * b)

    if abs(b) > 1e-12:
        put("DIV", a / b)

    if abs(a) > 1e-12:
        put("REVERSE_DIV", b / a)

    if abs(b) > 1e-12:
        put("MOD", a % b)

    if abs(a) > 1e-12:
        put("REVERSE_MOD", b % a)

    if abs(b) <= 8:

        try:
            put("POWER", a ** b)
        except Exception:
            pass

    if abs(a) <= 8:

        try:
            put("REVERSE_POWER", b ** a)
        except Exception:
            pass

    if a == int(a) and b == int(b):

        if abs(a) < 1_000_000 and abs(b) < 1_000_000:

            ai = int(a)
            bi = int(b)

            put("XOR", ai ^ bi)
            put("AND", ai & bi)
            put("OR", ai | bi)

            put("SHIFT_LEFT_A", ai << 1)
            put("SHIFT_RIGHT_A", ai >> 1)

            put("SHIFT_LEFT_B", bi << 1)
            put("SHIFT_RIGHT_B", bi >> 1)

    put("MEAN", (a + b) / 2)

    put("ABS_DIFFERENCE", abs(a - b))

    put("DISTANCE", math.sqrt(a*a + b*b))

    put("FLOOR_SUM", math.floor(a + b))

    put("CEIL_SUM", math.ceil(a + b))

    put("ROUND_SUM", round(a + b))

    if a >= 0:
        put("SQRT_A", math.sqrt(a))

    if b >= 0:
        put("SQRT_B", math.sqrt(b))

    if a > 0:
        put("LOG_A", math.log(a))

    if b > 0:
        put("LOG_B", math.log(b))

    if a > 0 and b > 0 and b != 1:
        put("LOG_RATIO", math.log(a, b))

    return results


def unary_operations(x):

    results = {}

    def put(name, value):

        value = safe_float(value)

        if value is not None:
            results[name] = value

    put("ABS", abs(x))

    put("NEGATIVE", -x)

    put("SQUARE", x*x)

    put("CUBE", x*x*x)

    put("FLOOR", math.floor(x))

    put("CEIL", math.ceil(x))

    put("ROUND", round(x))

    put("SIN", math.sin(x))

    put("COS", math.cos(x))

    if x >= 0:
        put("SQRT", math.sqrt(x))

    if x > 0:

        put("LN", math.log(x))

        put("LOG10", math.log10(x))

    if abs(x) > 1e-12:
        put("INVERSE", 1 / x)

    if (
        x >= 0
        and x <= 10
        and x == int(x)
    ):

        put(
            "FACTORIAL",
            math.factorial(int(x))
        )

    if x >= 0 and x == int(x):

        text_value = str(int(x))

        if len(text_value) > 1:

            put(
                "DIGIT_SUM",
                sum(int(c) for c in text_value)
            )

            put(
                "REVERSE_DIGITS",
                int(text_value[::-1])
            )

    return results


# ============================================================
# RECHERCHE MATHEMATIQUE
# ============================================================

def nearest_goal(value):

    if value is None:
        return None

    rounded = round(value)

    if (
        0 <= rounded <= MAX_GOALS
        and abs(value - rounded) < 1e-8
    ):

        return int(rounded)

    return None


def massive_search(matches, budget, run_seed):

    inventory = build_inventory(matches)

    values = [
        item["value"]
        for item in inventory
    ]

    labels = [
        item["label"]
        for item in inventory
    ]

    targets = set()

    for match in matches:

        targets.add(match["hg"])
        targets.add(match["ag"])

    candidates = Counter()

    operation_counts = Counter()

    # --------------------------------------------------------
    # OPERATIONS UNAIRES
    # --------------------------------------------------------

    for index, value in enumerate(values):

        if not budget.available():
            break

        results = unary_operations(value)

        for operation, result in results.items():

            if not budget.available():
                break

            budget.consume()

            operation_counts[operation] += 1

            target = nearest_goal(result)

            if target in targets:

                candidates[
                    (
                        operation,
                        target,
                        labels[index]
                    )
                ] += 1

    # --------------------------------------------------------
    # OPERATIONS BINAIRES
    # --------------------------------------------------------

    for i in range(len(values)):

        if not budget.available():
            break

        for j in range(i + 1, len(values)):

            if not budget.available():
                break

            results = calculate_operations(
                values[i],
                values[j]
            )

            for operation, result in results.items():

                if not budget.available():
                    break

                budget.consume()

                operation_counts[operation] += 1

                target = nearest_goal(result)

                if target in targets:

                    expression = (
                        labels[i]
                        + " "
                        + operation
                        + " "
                        + labels[j]
                    )

                    candidates[
                        (
                            operation,
                            target,
                            expression
                        )
                    ] += 1

    # --------------------------------------------------------
    # MONTE CARLO
    # --------------------------------------------------------

    rng = random.Random(run_seed)

    if len(values) >= 2:

        while budget.available():

            i = rng.randrange(len(values))
            j = rng.randrange(len(values))

            results = calculate_operations(
                values[i],
                values[j]
            )

            if not results:
                budget.consume()
                continue

            operation = rng.choice(
                list(results.keys())
            )

            result = results[operation]

            budget.consume()

            operation_counts[
                "MC_" + operation
            ] += 1

            target = nearest_goal(result)

            if target in targets:

                expression = (
                    labels[i]
                    + " "
                    + operation
                    + " "
                    + labels[j]
                )

                candidates[
                    (
                        "MC_" + operation,
                        target,
                        expression
                    )
                ] += 1

    found = []

    for (
        operation,
        target,
        expression
    ), count in candidates.most_common(500):

        found.append({

            "operation": operation,

            "target": target,

            "expression": expression,

            "matches": count

        })

    return {

        "tests": budget.tests,

        "elapsed_seconds": budget.elapsed(),

        "budget_status": budget.status(),

        "inventory_size": len(inventory),

        "candidate_count": len(found),

        "operation_counts": dict(operation_counts),

        "candidates": found

    }


# ============================================================
# STATISTIQUES
# ============================================================

def entropy(sequence):

    counts = Counter(sequence)

    total = len(sequence)

    if total == 0:
        return 0

    result = 0

    for count in counts.values():

        p = count / total

        result -= p * math.log2(p)

    return result


def statistical_analysis(matches):

    if not matches:
        return {}

    home = [m["hg"] for m in matches]

    away = [m["ag"] for m in matches]

    total = [m["total"] for m in matches]

    scores = Counter(
        m["score"] for m in matches
    )

    return {

        "matches": len(matches),

        "home_average": statistics.mean(home),

        "away_average": statistics.mean(away),

        "total_average": statistics.mean(total),

        "home_variance": statistics.pvariance(home),

        "away_variance": statistics.pvariance(away),

        "total_variance": statistics.pvariance(total),

        "home_frequency": dict(Counter(home)),

        "away_frequency": dict(Counter(away)),

        "score_frequency": dict(scores),

        "most_common_scores": scores.most_common(20),

        "btts_percent": (
            sum(m["btts"] for m in matches)
            / len(matches)
        ) * 100

    }


# ============================================================
# TRANSITIONS
# ============================================================

def transition_analysis(matches):

    output = {}

    for field in ("hg", "ag", "total"):

        sequence = [
            m[field] for m in matches
        ]

        transitions = Counter()

        for a, b in zip(
            sequence[:-1],
            sequence[1:]
        ):

            transitions[
                f"{a}->{b}"
            ] += 1

        output[field] = {

            "transitions": dict(transitions),

            "frequency": dict(Counter(sequence))

        }

    return output


# ============================================================
# TESTS DE SEQUENCES
# ============================================================

def sequence_tests(matches):

    output = {}

    for field in ("hg", "ag", "total"):

        sequence = [
            m[field] for m in matches
        ]

        if len(sequence) < 3:
            continue

        mean = statistics.mean(sequence)

        variance = statistics.pvariance(sequence)

        left = sequence[:-1]

        right = sequence[1:]

        if variance > 0:

            covariance = sum(
                (a - mean) * (b - mean)
                for a, b in zip(left, right)
            ) / len(left)

            autocorrelation = covariance / variance

        else:

            autocorrelation = 0

        signs = [
            1 if value >= mean else 0
            for value in sequence
        ]

        runs = 1 + sum(
            signs[i] != signs[i-1]
            for i in range(1, len(signs))
        )

        output[field] = {

            "mean": mean,

            "variance": variance,

            "lag1_autocorrelation": autocorrelation,

            "runs_count": runs,

            "entropy_bits": entropy(sequence)

        }

    return output


# ============================================================
# CYCLES ET REPETITIONS
# ============================================================

def cycle_analysis(matches):

    output = {}

    for field in ("hg", "ag", "score"):

        sequence = [
            m[field] for m in matches
        ]

        cycles = {}

        max_period = min(
            30,
            len(sequence) // 2
        )

        for period in range(1, max_period + 1):

            repetitions = 0

            for i in range(
                period,
                len(sequence)
            ):

                if sequence[i] == sequence[i-period]:
                    repetitions += 1

            if repetitions:

                cycles[str(period)] = repetitions

        output[field] = cycles

    return output


# ============================================================
# BLIND BACKTEST CHRONOLOGIQUE
# ============================================================

def blind_backtest(matches):

    tested = 0

    home_top1 = 0
    away_top1 = 0

    home_top3 = 0
    away_top3 = 0

    home_top5 = 0
    away_top5 = 0

    predictions = []

    for index in range(5, len(matches)):

        history = matches[:index]

        target = matches[index]

        # Le match cible n'est pas inclus
        # dans le calcul des fréquences.

        home_counts = Counter(
            m["hg"] for m in history
        )

        away_counts = Counter(
            m["ag"] for m in history
        )

        home_ranking = [
            value
            for value, count
            in home_counts.most_common(5)
        ]

        away_ranking = [
            value
            for value, count
            in away_counts.most_common(5)
        ]

        if not home_ranking or not away_ranking:
            continue

        tested += 1

        hg = target["hg"]

        ag = target["ag"]

        if home_ranking[0] == hg:
            home_top1 += 1

        if away_ranking[0] == ag:
            away_top1 += 1

        if hg in home_ranking[:3]:
            home_top3 += 1

        if ag in away_ranking[:3]:
            away_top3 += 1

        if hg in home_ranking[:5]:
            home_top5 += 1

        if ag in away_ranking[:5]:
            away_top5 += 1

        predictions.append({

            "round": target["round"],

            "actual": target["score"],

            "home_candidates": home_ranking,

            "away_candidates": away_ranking

        })

    def rate(value):

        if tested == 0:
            return 0

        return round(
            value / tested * 100,
            3
        )

    return {

        "tested": tested,

        "home_top1": rate(home_top1),

        "away_top1": rate(away_top1),

        "home_top3": rate(home_top3),

        "away_top3": rate(away_top3),

        "home_top5": rate(home_top5),

        "away_top5": rate(away_top5),

        "predictions": predictions[-50:]

    }


# ============================================================
# ETUDE DES EMPREINTES RNG
# ============================================================

def rng_investigation(matches):

    output = {}

    for field in ("hg", "ag", "total"):

        sequence = [
            m[field] for m in matches
        ]

        if len(sequence) < 10:
            continue

        differences = [

            sequence[i] - sequence[i-1]

            for i in range(1, len(sequence))

        ]

        blocks = Counter()

        for size in range(2, 7):

            for i in range(
                len(sequence) - size + 1
            ):

                block = tuple(
                    sequence[i:i+size]
                )

                blocks[(size, block)] += 1

        repeated = []

        for (size, block), count in blocks.items():

            if count > 1:

                repeated.append({

                    "size": size,

                    "block": list(block),

                    "count": count

                })

        output[field] = {

            "sequence_length": len(sequence),

            "difference_frequency": dict(
                Counter(differences)
            ),

            "repeated_blocks": sorted(

                repeated,

                key=lambda item: item["count"],

                reverse=True

            )[:100]

        }

    output["interpretation"] = (
        "Statistical fingerprints only. "
        "Not proof of the internal RNG."
    )

    return output


# ============================================================
# MONTE CARLO DE CONTROLE
# ============================================================

def monte_carlo_control(
    matches,
    trials=MONTE_CARLO_TRIALS
):

    if not matches:
        return {}

    rng = random.Random(RANDOM_SEED)

    home = [
        m["hg"] for m in matches
    ]

    away = [
        m["ag"] for m in matches
    ]

    home_mean = statistics.mean(home)

    away_mean = statistics.mean(away)

    home_std = max(
        0.5,
        statistics.pstdev(home)
    )

    away_std = max(
        0.5,
        statistics.pstdev(away)
    )

    home_max = max(home)

    away_max = max(away)

    simulated_home = Counter()

    simulated_away = Counter()

    for _ in range(trials):

        h = min(
            home_max,
            max(
                0,
                round(
                    rng.gauss(
                        home_mean,
                        home_std
                    )
                )
            )
        )

        a = min(
            away_max,
            max(
                0,
                round(
                    rng.gauss(
                        away_mean,
                        away_std
                    )
                )
            )
        )

        simulated_home[h] += 1

        simulated_away[a] += 1

    return {

        "trials": trials,

        "observed_home": dict(Counter(home)),

        "observed_away": dict(Counter(away)),

        "simulated_home": dict(simulated_home),

        "simulated_away": dict(simulated_away),

        "note": (
            "Gaussian control model. "
            "Not a reconstruction of Bet261 RNG."
        )

    }


# ============================================================
# SAUVEGARDE DES RESULTATS
# ============================================================

def save_tournament_results(name, result):

    safe_name = re.sub(
        r"[^a-zA-Z0-9_-]",
        "_",
        name
    )

    files = {

        "summary": "summary",

        "search": "massive_search",

        "transitions": "transitions",

        "cycles": "cycles",

        "sequence": "sequence_tests",

        "blind": "blind_backtest",

        "rng": "rng_investigation",

        "monte_carlo": "monte_carlo"

    }

    for key, filename in files.items():

        save_json(

            os.path.join(
                OUT_DIR,
                safe_name + "_" + filename + ".json"
            ),

            result[key]

        )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if not TOKEN or not CHAT_ID:

        print("Telegram non configuré.")

        return False

    url = (
        "https://api.telegram.org/bot"
        + TOKEN
        + "/sendMessage"
    )

    payload = urllib.parse.urlencode({

        "chat_id": CHAT_ID,

        "text": message,

        "disable_web_page_preview": "true"

    }).encode("utf-8")

    try:

        request = urllib.request.Request(
            url,
            data=payload,
            method="POST"
        )

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

            return bool(result.get("ok"))

    except Exception as error:

        print("Telegram erreur :", error)

        return False


# ============================================================
# RAPPORT TELEGRAM
# ============================================================

def build_report(
    state,
    results,
    tests_this_run,
    elapsed,
    status
):

    lines = [

        "━━━━━━━━━━━━━━━━━━━━",

        "🧠 TESLA V8",

        "MASSIVE MATHEMATICAL INVESTIGATION",

        "━━━━━━━━━━━━━━━━━━━━",

        "",

        "📅 " + datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "",

        "⚙️ EXECUTION",

        f"Tests : {tests_this_run:,}",

        f"Temps : {elapsed} secondes",

        f"Statut : {status}",

        f"Total cumulé : {state['total_tests']:,}",

        f"Lancements : {state['total_runs']}",

        "",

        "📚 TOURNOIS : "
        + str(len(results))

    ]

    for name, result in results.items():

        stats = result["summary"]

        blind = result["blind"]

        search = result["search"]

        lines += [

            "",

            "━━━━━━━━━━━━━━━━━━━━",

            "🏆 " + name,

            "Matchs : "
            + str(stats["matches"]),

            "Moyenne domicile : "
            + str(round(stats["home_average"], 3)),

            "Moyenne extérieur : "
            + str(round(stats["away_average"], 3)),

            "Moyenne buts : "
            + str(round(stats["total_average"], 3)),

            "BTTS : "
            + str(round(stats["btts_percent"], 2))
            + "%",

            "Tests mathématiques : "
            + f"{search['tests']:,}",

            "Candidats : "
            + str(search["candidate_count"]),

            "BLIND testés : "
            + str(blind["tested"]),

            "BLIND domicile Top1 : "
            + str(blind["home_top1"])
            + "%",

            "BLIND extérieur Top1 : "
            + str(blind["away_top1"])
            + "%"

        ]

    lines += [

        "",

        "⚠️ Les candidats mathématiques doivent",

        "être validés sur des données futures.",

        "",

        "TESLA V8 — INVESTIGATION ACTIVE",

        "━━━━━━━━━━━━━━━━━━━━"

    ]

    return "\n".join(lines)


# ============================================================
# EXECUTION CENTRALE
# ============================================================

def main():

    print("===================================")

    print("TESLA V8 START")

    print("===================================")

    state = load_state()

    tournaments = load_all_tournaments()

    if not tournaments:

        print(
            "Aucun tournoi trouvé dans data/tournaments/"
        )

        telegram_send(
            "TESLA V8 : aucun tournoi trouvé."
        )

        return

    budget = Budget()

    run_results = {}

    total_candidates = 0

    operation_totals = Counter()

    current_hash = digest({

        name: [

            (
                m["round"],
                m["home"],
                m["away"],
                m["hg"],
                m["ag"]
            )

            for m in matches

        ]

        for name, matches in tournaments.items()

    })

    run_seed = (
        RANDOM_SEED
        + int(state.get("total_runs", 0))
    )

    # --------------------------------------------------------
    # ANALYSE DES TOURNOIS
    # --------------------------------------------------------

    for name, matches in tournaments.items():

        print("")
        print("ANALYSE :", name)
        print("MATCHS :", len(matches))

        if not budget.available():

            print(
                "Budget global atteint : arrêt des recherches."
            )

            break

        try:

            summary = statistical_analysis(matches)

            search = massive_search(
                matches,
                budget,
                run_seed
            )

            operation_totals.update(
                search["operation_counts"]
            )

            transitions = transition_analysis(matches)

            cycles = cycle_analysis(matches)

            sequence = sequence_tests(matches)

            blind = blind_backtest(matches)

            rng = rng_investigation(matches)

            mc = monte_carlo_control(matches)

            result = {

                "summary": summary,

                "search": search,

                "transitions": transitions,

                "cycles": cycles,

                "sequence": sequence,

                "blind": blind,

                "rng": rng,

                "monte_carlo": mc

            }

            run_results[name] = result

            total_candidates += search["candidate_count"]

            save_tournament_results(
                name,
                result
            )

            print(
                "Tests cumulés :",
                budget.tests
            )

            print(
                "Candidats :",
                search["candidate_count"]
            )

        except Exception as error:

            print(
                "ERREUR TOURNOI :",
                name,
                str(error)
            )

            save_json(

                os.path.join(
                    OUT_DIR,
                    "error_" + name + ".json"
                ),

                {

                    "tournament": name,

                    "error": str(error),

                    "timestamp": now_utc()

                }

            )

    # --------------------------------------------------------
    # ETAT CUMULATIF
    # --------------------------------------------------------

    state["total_tests"] += budget.tests

    state["total_runs"] += 1

    state["total_candidates"] += total_candidates

    state["operation_counts"] = dict(

        Counter(
            state.get("operation_counts", {})
        ) + operation_totals

    )

    state["last_run"] = now_utc()

    state["last_run_tests"] = budget.tests

    state["last_run_status"] = budget.status()

    state["data_hash"] = current_hash

    state["last_run_elapsed"] = budget.elapsed()

    save_state(state)

    # --------------------------------------------------------
    # RESUME GLOBAL
    # --------------------------------------------------------

    global_summary = {

        "version": "TESLA_V8",

        "generated_at": now_utc(),

        "total_tests_this_run": budget.tests,

        "total_tests_cumulative": state["total_tests"],

        "total_runs": state["total_runs"],

        "total_candidates_cumulative": state["total_candidates"],

        "elapsed_seconds": budget.elapsed(),

        "status": budget.status(),

        "operation_counts_cumulative": state["operation_counts"],

        "data_hash": current_hash,

        "tournaments": {

            name: {

                "matches": len(
                    tournaments[name]
                ),

                "tests": result["search"]["tests"],

                "candidates": result["search"]["candidate_count"],

                "blind": result["blind"]

            }

            for name, result in run_results.items()

        }

    }

    save_json(

        os.path.join(
            OUT_DIR,
            "global_summary.json"
        ),

        global_summary

    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    report = build_report(

        state,

        run_results,

        budget.tests,

        budget.elapsed(),

        budget.status()

    )

    print("")
    print(report)

    sent = telegram_send(report)

    print("")

    print(
        "TELEGRAM :",
        "ENVOYE" if sent else "NON ENVOYE"
    )

    print(
        "TESLA V8 FINISHED —",
        budget.status()
    )


# ============================================================
# POINT D'ENTREE
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print("ERREUR FATALE TESLA V8 :", error)

        raise