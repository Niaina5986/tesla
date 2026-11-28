#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TESLA V8 — MASSIVE MATHEMATICAL INVESTIGATION ENGINE

Objectifs :
- Recherche massive de relations mathématiques.
- Exploration de plusieurs familles d'opérations.
- Analyse statistique et séquentielle.
- Recherche de candidats de mécanismes RNG.
- Tests chronologiques BLIND.
- Historique persistant des calculs.
- Rapport Telegram à chaque exécution.

IMPORTANT :
Un candidat mathématique n'est pas une preuve du RNG interne.
Les tests statistiques ne permettent pas, à eux seuls,
d'identifier avec certitude un générateur propriétaire.
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

from collections import Counter, defaultdict
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

# Nombre maximal de calculs par lancement.
# Ajustable dans GitHub Actions Variables.
MAX_TESTS_PER_RUN = int(
    os.getenv("TESLA_MAX_TESTS_PER_RUN", "1000000")
)

# Nombre de valeurs conservées dans l'inventaire.
MAX_INVENTORY = int(
    os.getenv("TESLA_MAX_INVENTORY", "300")
)

# Taille maximale des valeurs calculées.
MAX_ABS = 1_000_000

# Durée maximale du moteur.
MAX_RUNTIME_SECONDS = int(
    os.getenv("TESLA_MAX_RUNTIME_SECONDS", "420")
)

# Recherches supplémentaires.
RANDOM_SEED = int(os.getenv("TESLA_RANDOM_SEED", "42"))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ROUND_RE = re.compile(r"journ[eé]e\s*(\d+)", re.I)

MATCH_RE = re.compile(
    r"^(.*?)\s+(\d+)\s*[-:]\s*(\d+)\s+(.*?)$"
)

random.seed(RANDOM_SEED)


# ============================================================
# UTILITAIRES
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

    except Exception:
        return None


def clean(value):
    if abs(value) < 1e-10:
        return 0

    if abs(value - round(value)) < 1e-9:
        return int(round(value))

    return round(float(value), 8)


def save_json(path, data):
    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    os.replace(temp, path)


def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
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

def load_state():

    return load_json(
        STATE_FILE,
        {
            "version": "TESLA_V8",
            "total_tests": 0,
            "total_runs": 0,
            "total_candidates": 0,
            "total_rejected": 0,
            "operation_counts": {},
            "last_run": None,
            "data_hash": None,
            "best_candidates": []
        }
    )


def save_state(state):
    save_json(STATE_FILE, state)


# ============================================================
# LECTURE DES TOURNOIS
# ============================================================

def parse_tournament(path):

    name = os.path.splitext(
        os.path.basename(path)
    )[0]

    current_round = None
    matches = []

    with open(path, encoding="utf-8-sig") as f:

        for raw in f:

            line = raw.strip()

            if not line:
                continue

            rm = ROUND_RE.search(line)

            if rm:

                current_round = int(rm.group(1))

                if not 1 <= current_round <= MAX_ROUNDS:
                    current_round = None

                continue

            mm = MATCH_RE.match(line)

            if not mm or current_round is None:
                continue

            home, hg, ag, away = mm.groups()

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

    matches.sort(
        key=lambda x: (
            x["round"],
            x["home"],
            x["away"]
        )
    )

    return name, matches


def load_all_tournaments():

    tournaments = {}

    for filename in os.listdir(DATA_DIR):

        if not filename.lower().endswith(".txt"):
            continue

        path = os.path.join(DATA_DIR, filename)

        name, matches = parse_tournament(path)

        if matches:
            tournaments[name] = matches

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

        add(len(matches), "match_count")

        add(
            statistics.mean(m["hg"] for m in matches),
            "mean_home"
        )

        add(
            statistics.mean(m["ag"] for m in matches),
            "mean_away"
        )

        add(
            statistics.mean(m["total"] for m in matches),
            "mean_total"
        )

        add(
            statistics.pvariance(m["total"] for m in matches),
            "total_variance"
        )

    # Valeurs des séquences historiques.
    for field in ("hg", "ag", "total"):

        sequence = [m[field] for m in matches]

        if not sequence:
            continue

        add(max(sequence), field + "_max")
        add(min(sequence), field + "_min")

        add(
            statistics.median(sequence),
            field + "_median"
        )

        for lag in (1, 2, 3, 5):

            if len(sequence) > lag:

                add(
                    sequence[-lag - 1],
                    field + "_lag_" + str(lag)
                )

    # Déduplication.
    unique = {}

    for item in values:

        key = round(item["value"], 8)

        if key not in unique:
            unique[key] = item

    result = list(unique.values())

    if len(result) > MAX_INVENTORY:

        result = result[:MAX_INVENTORY]

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

    # ADDITION
    put("+", a + b)

    # SOUSTRACTION
    put("-", a - b)
    put("reverse_minus", b - a)

    # MULTIPLICATION
    put("*", a * b)

    # DIVISION
    if abs(b) > 1e-12:
        put("/", a / b)

    if abs(a) > 1e-12:
        put("reverse_division", b / a)

    # MODULO
    if abs(b) > 1e-12:
        put("%", a % b)

    if abs(a) > 1e-12:
        put("reverse_modulo", b % a)

    # PUISSANCE
    if abs(b) <= 8:

        try:
            put("^", a ** b)
        except Exception:
            pass

    if abs(a) <= 8:

        try:
            put("reverse_power", b ** a)
        except Exception:
            pass

    # XOR : uniquement entiers.
    if a == int(a) and b == int(b):

        if abs(a) < 1_000_000 and abs(b) < 1_000_000:

            put("XOR", int(a) ^ int(b))
            put("AND", int(a) & int(b))
            put("OR", int(a) | int(b))
            put("SHIFT_LEFT", int(a) << 1)
            put("SHIFT_RIGHT", int(a) >> 1)

    # MOYENNE
    put("mean", (a + b) / 2)

    # DIFFERENCE ABSOLUE
    put("abs_difference", abs(a - b))

    # DISTANCE
    put("distance", math.sqrt(a*a + b*b))

    # RACINES
    if a >= 0:
        put("sqrt_a", math.sqrt(a))

    if b >= 0:
        put("sqrt_b", math.sqrt(b))

    # LOGARITHMES
    if a > 0:
        put("ln_a", math.log(a))

    if b > 0:
        put("ln_b", math.log(b))

    if a > 0 and b > 0:
        put("log_ratio", math.log(a, b))

    # TRIGONOMETRIE
    put("sin_a", math.sin(a))
    put("cos_a", math.cos(a))

    put("sin_b", math.sin(b))
    put("cos_b", math.cos(b))

    put("tan_a", math.tan(a))
    put("tan_b", math.tan(b))

    # AUTRES
    put("floor_sum", math.floor(a + b))
    put("ceil_sum", math.ceil(a + b))

    put("round_sum", round(a + b))

    return results


# ============================================================
# OPERATIONS UNAIRES
# ============================================================

def unary_operations(x):

    results = {}

    def put(name, value):

        value = safe_float(value)

        if value is not None:
            results[name] = value

    put("abs", abs(x))
    put("negative", -x)

    put("square", x*x)
    put("cube", x*x*x)

    put("floor", math.floor(x))
    put("ceil", math.ceil(x))

    put("round", round(x))

    put("sin", math.sin(x))
    put("cos", math.cos(x))

    if x >= 0:
        put("sqrt", math.sqrt(x))

    if x > 0:
        put("ln", math.log(x))
        put("log10", math.log10(x))

    if abs(x) > 1e-12:
        put("inverse", 1/x)

    if x >= 0 and x <= 10 and x == int(x):
        put("factorial", math.factorial(int(x)))

    if x >= 0 and x == int(x):

        text = str(int(x))

        if len(text) > 1:

            put(
                "digit_sum",
                sum(int(c) for c in text)
            )

            put(
                "reverse_digits",
                int(text[::-1])
            )

    return results


# ============================================================
# DETECTION DES CORRESPONDANCES
# ============================================================

def nearest_goal(value):

    if value is None:
        return None

    rounded = round(value)

    if 0 <= rounded <= MAX_GOALS:

        if abs(value - rounded) < 1e-8:
            return int(rounded)

    return None


def register_candidate(
    candidates,
    operation,
    value,
    target,
    expression
):

    if nearest_goal(value) != target:
        return

    key = (
        operation,
        target,
        expression
    )

    candidates[key] += 1


# ============================================================
# MOTEUR MASSIF DE CALCUL
# ============================================================

def massive_search(matches, state):

    inventory = build_inventory(matches)

    candidates = Counter()
    operation_counts = Counter()

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

    start = time.time()

    tests = 0

    budget = MAX_TESTS_PER_RUN

    # --------------------------------------------------------
    # TESTS UNAIRES
    # --------------------------------------------------------

    for index, value in enumerate(values):

        if tests >= budget:
            break

        results = unary_operations(value)

        for operation, result in results.items():

            tests += 1
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

            if tests >= budget:
                break

    # --------------------------------------------------------
    # TESTS BINAIRES
    # --------------------------------------------------------

    if len(values) >= 2:

        for i in range(len(values)):

            if tests >= budget:
                break

            for j in range(i + 1, len(values)):

                if tests >= budget:
                    break

                a = values[i]
                b = values[j]

                results = calculate_operations(a, b)

                for operation, result in results.items():

                    tests += 1
                    operation_counts[operation] += 1

                    target = nearest_goal(result)

                    if target in targets:

                        expression = (
                            labels[i]
                            + operation
                            + labels[j]
                        )

                        candidates[
                            (
                                operation,
                                target,
                                expression
                            )
                        ] += 1

                    if tests >= budget:
                        break

    # --------------------------------------------------------
    # MONTE CARLO
    # --------------------------------------------------------

    rng = random.Random(
        RANDOM_SEED + int(state.get("total_runs", 0))
    )

    while tests < budget:

        if time.time() - start > MAX_RUNTIME_SECONDS:
            break

        if len(values) < 2:
            break

        i = rng.randrange(len(values))
        j = rng.randrange(len(values))

        a = values[i]
        b = values[j]

        results = calculate_operations(a, b)

        if not results:
            continue

        operation = rng.choice(list(results.keys()))
        result = results[operation]

        tests += 1
        operation_counts["MONTE_CARLO_" + operation] += 1

        target = nearest_goal(result)

        if target in targets:

            expression = (
                labels[i]
                + operation
                + labels[j]
            )

            candidates[
                (
                    "MC_" + operation,
                    target,
                    expression
                )
            ] += 1

    # --------------------------------------------------------
    # RESULTATS
    # --------------------------------------------------------

    found = []

    for (operation, target, expression), count in (
        candidates.most_common(500)
    ):

        found.append({
            "operation": operation,
            "target": target,
            "expression": expression,
            "matches": count
        })

    elapsed = round(time.time() - start, 3)

    return {
        "tests": tests,
        "elapsed_seconds": elapsed,
        "operation_counts": dict(operation_counts),
        "candidate_count": len(found),
        "candidates": found,
        "inventory_size": len(inventory)
    }


# ============================================================
# ANALYSE STATISTIQUE
# ============================================================

def statistical_analysis(matches):

    home = [m["hg"] for m in matches]
    away = [m["ag"] for m in matches]
    total = [m["total"] for m in matches]

    if not matches:
        return {}

    score_frequency = Counter(
        m["score"] for m in matches
    )

    home_frequency = Counter(home)
    away_frequency = Counter(away)

    return {

        "matches": len(matches),

        "home_average": statistics.mean(home),
        "away_average": statistics.mean(away),

        "total_average": statistics.mean(total),

        "home_variance": statistics.pvariance(home),
        "away_variance": statistics.pvariance(away),

        "btts_percent": (
            sum(m["btts"] for m in matches)
            / len(matches)
        ) * 100,

        "score_frequency": dict(score_frequency),

        "home_frequency": dict(home_frequency),

        "away_frequency": dict(away_frequency),

        "most_common_scores": (
            score_frequency.most_common(15)
        )
    }


# ============================================================
# ANALYSE DES TRANSITIONS
# ============================================================

def transition_analysis(matches):

    result = {}

    for field in ("hg", "ag"):

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

        result[field] = {
            "transitions": dict(transitions),
            "repeated_values": dict(Counter(sequence))
        }

    return result


# ============================================================
# TESTS STATISTIQUES DE SEQUENCES
# ============================================================

def sequence_tests(matches):

    output = {}

    for field in ("hg", "ag"):

        seq = [m[field] for m in matches]

        if len(seq) < 3:
            continue

        mean = statistics.mean(seq)

        variance = statistics.pvariance(seq)

        # Autocorrélation lag 1.
        left = seq[:-1]
        right = seq[1:]

        if variance > 0:

            covariance = sum(
                (a - mean) * (b - mean)
                for a, b in zip(left, right)
            ) / len(left)

            autocorrelation = covariance / variance

        else:

            autocorrelation = 0

        # Runs au-dessus / en-dessous de la moyenne.
        signs = [
            1 if x >= mean else 0
            for x in seq
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

            "entropy_bits": entropy(seq)
        }

    return output


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


# ============================================================
# ANALYSE DES CYCLES
# ============================================================

def cycle_analysis(matches):

    output = {}

    for field in ("hg", "ag", "score"):

        seq = [m[field] for m in matches]

        cycles = {}

        for period in range(1, min(30, len(seq)//2 + 1)):

            repetitions = 0

            for i in range(period, len(seq)):

                if seq[i] == seq[i-period]:
                    repetitions += 1

            if repetitions:

                cycles[str(period)] = repetitions

        output[field] = cycles

    return output


# ============================================================
# BACKTEST CHRONOLOGIQUE BLIND
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

        # Aucune donnée future utilisée.
        home_counts = Counter(
            m["hg"] for m in history
        )

        away_counts = Counter(
            m["ag"] for m in history
        )

        home_ranking = [
            x for x, _ in home_counts.most_common(5)
        ]

        away_ranking = [
            x for x, _ in away_counts.most_common(5)
        ]

        if not home_ranking:
            continue

        if not away_ranking:
            continue

        tested += 1

        hg = target["hg"]
        ag = target["ag"]

        if home_ranking[0] == hg:
            home_top1 += 1

        if ag == away_ranking[0]:
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

        return round(value / tested * 100, 3)

    return {

        "tested": tested,

        "home_top1": rate(home_top1),
        "away_top1": rate(away_top1),

        "home_top3": rate(home_top3),
        "away_top3": rate(away_top3),

        "home_top5": rate(home_top5),
        "away_top5": rate(away_top5),

        "predictions": predictions[-30:]
    }


# ============================================================
# RECHERCHE DE CANDIDATS RNG
# ============================================================

def rng_investigation(matches):

    output = {}

    for field in ("hg", "ag"):

        seq = [m[field] for m in matches]

        if len(seq) < 10:
            continue

        # Analyse des différences.
        differences = [
            seq[i] - seq[i-1]
            for i in range(1, len(seq))
        ]

        # Recherche de répétitions de blocs.
        blocks = Counter()

        for size in range(2, 7):

            for i in range(len(seq) - size + 1):

                block = tuple(seq[i:i+size])

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

            "sequence_length": len(seq),

            "difference_frequency": dict(
                Counter(differences)
            ),

            "repeated_blocks": sorted(
                repeated,
                key=lambda x: x["count"],
                reverse=True
            )[:100]
        }

    output["interpretation"] = (
        "Statistical fingerprints only. "
        "They do not identify the internal RNG."
    )

    return output


# ============================================================
# MONTE CARLO : CONTROLE DE HASARD
# ============================================================

def monte_carlo_control(matches, trials=10000):

    if not matches:
        return {}

    rng = random.Random(RANDOM_SEED)

    observed = Counter(
        m["hg"] for m in matches
    )

    observed_away = Counter(
        m["ag"] for m in matches
    )

    home_values = [m["hg"] for m in matches]
    away_values = [m["ag"] for m in matches]

    home_mean = statistics.mean(home_values)
    away_mean = statistics.mean(away_values)

    home_max = max(home_values)
    away_max = max(away_values)

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
                        max(0.5, statistics.pstdev(home_values))
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
                        max(0.5, statistics.pstdev(away_values))
                    )
                )
            )
        )

        simulated_home[h] += 1
        simulated_away[a] += 1

    return {

        "trials": trials,

        "observed_home": dict(observed),

        "observed_away": dict(observed_away),

        "simulated_home": dict(simulated_home),

        "simulated_away": dict(simulated_away),

        "note": (
            "Gaussian baseline control, not a reconstruction "
            "of Bet261's RNG."
        )
    }


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

    except Exception as exc:

        print("Telegram erreur:", str(exc))

        return False


# ============================================================
# RAPPORT
# ============================================================

def build_report(
    state,
    tournament_results,
    tests_this_run,
    operation_counts
):

    lines = [

        "━━━━━━━━━━━━━━━━━━━━",

        "🧠 TESLA V8 — MASSIVE INVESTIGATION",

        "━━━━━━━━━━━━━━━━━━━━",

        "📅 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

        "",

        "⚙️ CALCULS",

        "Tests de ce cycle : "
        + f"{tests_this_run:,}",

        "Tests cumulés : "
        + f"{state['total_tests']:,}",

        "Nombre de lancements : "
        + str(state["total_runs"]),

        "",

        "🔬 OPERATIONS"
    ]

    for operation, count in sorted(
        operation_counts.items(),
        key=lambda x: x[1],
        reverse=True
    )[:20]:

        lines.append(
            f"{operation} : {count:,}"
        )

    lines += [

        "",

        "🏆 TOURNOIS : "
        + str(len(tournament_results))
    ]

    for name, result in tournament_results.items():

        stats = result["statistics"]

        blind = result["blind"]

        search = result["search"]

        lines += [

            "",

            "📚 " + name,

            "Matchs : "
            + str(stats["matches"]),

            "Moyenne domicile : "
            + str(round(stats["home_average"], 3)),

            "Moyenne extérieur : "
            + str(round(stats["away_average"], 3)),

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

        "⚠️ Un candidat n'est pas une preuve du RNG.",

        "BLIND utilise uniquement les données antérieures.",

        "━━━━━━━━━━━━━━━━━━━━",

        "TESLA V8 — INVESTIGATION ACTIVE"
    ]

    return "\n".join(lines)


# ============================================================
# EXECUTION CENTRALE
# ============================================================

def main():

    print("TESLA V8 START")

    state = load_state()

    tournaments = load_all_tournaments()

    if not tournaments:

        print("Aucun tournoi trouvé.")

        telegram_send(
            "TESLA V8 : aucun fichier de tournoi trouvé "
            "dans data/tournaments/."
        )

        return

    tournament_results = {}

    tests_this_run = 0

    total_operations = Counter()

    current_hash = digest({

        name: [
            (m["round"], m["home"], m["away"], m["hg"], m["ag"])
            for m in matches
        ]

        for name, matches in tournaments.items()

    })

    for name, matches in tournaments.items():

        print("Analyse :", name)

        # 1. Statistiques.
        stats = statistical_analysis(matches)

        # 2. Recherche massive.
        search = massive_search(matches, state)

        tests_this_run += search["tests"]

        total_operations.update(
            search["operation_counts"]
        )

        # 3. Transitions.
        transitions = transition_analysis(matches)

        # 4. Cycles.
        cycles = cycle_analysis(matches)

        # 5. Tests statistiques.
        sequence = sequence_tests(matches)

        # 6. BLIND.
        blind = blind_backtest(matches)

        # 7. Recherche RNG.
        rng = rng_investigation(matches)

        # 8. Monte Carlo.
        mc = monte_carlo_control(matches)

        prefix = name

        save_json(
            os.path.join(
                OUT_DIR,
                prefix + "_summary.json"
            ),
            stats
        )

        save_json(
            os.path.join(
                OUT_DIR,
                prefix + "_massive_search.json"
            ),
            search
        )

        save_json(
            os.path.join(
                OUT_DIR,
                prefix + "_transitions.json"
            ),
            transitions
        )

        save_json(
            os.path.join(
                OUT_DIR,
                prefix + "_cycles.json"
            ),
            cycles
        )

        save_json(
            os.path.join(
                OUT_DIR,
                prefix + "_sequence_tests.json"
            ),
            sequence
        )

        save_json(
            os.path.join(
                OUT_DIR,
                prefix + "_blind_backtest.json"
            ),
            blind
        )

        save_json(
            os.path.join(
                OUT_DIR,
                prefix + "_rng_investigation.json"
            ),
            rng
        )

        save_json(
            os.path.join(
                OUT_DIR,
                prefix + "_monte_carlo.json"
            ),
            mc
        )

        tournament_results[name] = {

            "statistics": stats,

            "search": search,

            "blind": blind,

            "rng": rng

        }

    # --------------------------------------------------------
    # ETAT CUMULATIF
    # --------------------------------------------------------

    state["total_tests"] += tests_this_run

    state["total_runs"] += 1

    state["operation_counts"] = dict(
        Counter(state.get("operation_counts", {}))
        + total_operations
    )

    state["last_run"] = now_utc()

    state["data_hash"] = current_hash

    state["total_candidates"] += sum(
        r["search"]["candidate_count"]
        for r in tournament_results.values()
    )

    state["last_run_tests"] = tests_this_run

    state["last_run_operations"] = dict(
        total_operations
    )

    save_state(state)

    # --------------------------------------------------------
    # RESUME / GLOBAL SUMMARY
    # --------------------------------------------------------

    global_summary = {

        "version": "TESLA_V8",

        "generated_at": now_utc(),

        "total_tests_this_run": tests_this_run,

        "total_tests_cumulative": state["total_tests"],

        "total_runs": state["total_runs"],

        "operation_counts_cumulative": state["operation_counts"],

        "data_hash": current_hash,

        "tournaments": {

            name: {

                "matches": len(tournaments[name]),

                "tests": result["search"]["tests"],

                "candidates": result["search"]["candidate_count"],

                "blind": result["blind"]

            }

            for name, result in tournament_results.items()

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

        tournament_results,

        tests_this_run,

        total_operations

    )

    print(report)

    sent = telegram_send(report)

    print(
        "Telegram :",
        "ENVOYE" if sent else "NON ENVOYE"
    )

    print("TESLA V8 FINISHED")


if __name__ == "__main__":

    main()