#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
===========================================================
 TESLA V5 — UNIVERSAL MATHEMATICAL DISCOVERY ENGINE
===========================================================

MOTEURS:
1. Tournament Parser
2. Historical Statistics
3. Ranking Engine
4. Goal & Form Engine
5. Score Fingerprints
6. Sequence Detector
7. RNG Diagnostics
8. Poisson Engine
9. Monte Carlo
10. BFS / DFS Mathematical Search
11. Universal Number Hunter
12. Discovery Mode
13. Blind Prediction
14. Walk-Forward Backtest
15. Cross-Tournament Analysis
16. Telegram Reports

DONNEES:
data/tournaments/tournoi_001.txt

FORMAT:
Journée 1
Arsenal 2-1 Chelsea
Liverpool 3-0 Everton

Journée 2
...

Jusqu'à J37.
===========================================================
"""

import os
import re
import json
import math
import random
import hashlib
import statistics
import itertools

from collections import Counter, defaultdict
from datetime import datetime, timezone


# ===========================================================
# CONFIGURATION
# ===========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(
    BASE_DIR, "data", "tournaments"
)

OUTPUT_DIR = os.path.join(
    BASE_DIR, "output"
)

MAX_ROUNDS = 37
MAX_GOALS = 7

MC_SIMULATIONS = int(
    os.getenv("MONTE_CARLO_SIMULATIONS", "100000")
)

MATH_MAX_ATOMS = int(
    os.getenv("MATH_MAX_ATOMS", "30")
)

MATH_MAX_STATES = int(
    os.getenv("MATH_MAX_STATES", "3500")
)

MATH_MAX_DEPTH = int(
    os.getenv("MATH_MAX_DEPTH", "4")
)

MATH_MAX_ABS = 1000000

RANDOM_SEED = 42

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
)

random.seed(RANDOM_SEED)

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ===========================================================
# UTILITIES
# ===========================================================

def clean_number(value):

    if value is None:
        return None

    if abs(value) < 1e-10:
        return 0

    if abs(value - round(value)) < 1e-9:
        return int(round(value))

    return round(value, 8)


def safe_number(value):

    try:
        result = float(value)

        if math.isfinite(result):
            return result

    except (ValueError, TypeError, OverflowError):
        pass

    return None


def safe_filename(name):

    return re.sub(
        r"[^a-zA-Z0-9_-]",
        "_",
        name
    )


def write_json(filename, data):

    path = os.path.join(
        OUTPUT_DIR,
        filename
    )

    with open(path, "w", encoding="utf-8") as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    return path


def calculate_hash(files):

    h = hashlib.sha256()

    for path in sorted(files):

        with open(path, "rb") as f:
            h.update(f.read())

    return h.hexdigest()


# ===========================================================
# TOURNAMENT PARSER
# ===========================================================

ROUND_PATTERN = re.compile(
    r"journ[eé]e\s*(\d+)",
    re.IGNORECASE
)

MATCH_PATTERN = re.compile(
    r"^(.*?)\s+(\d+)\s*[-:]\s*(\d+)\s+(.*?)$"
)


def parse_tournament(path):

    name = os.path.splitext(
        os.path.basename(path)
    )[0]

    matches = []
    current_round = None

    with open(
        path,
        "r",
        encoding="utf-8-sig"
    ) as f:

        for raw_line in f:

            line = raw_line.strip()

            if not line:
                continue

            round_match = ROUND_PATTERN.search(line)

            if round_match:

                current_round = int(
                    round_match.group(1)
                )

                continue

            match = MATCH_PATTERN.match(line)

            if not match:
                continue

            if current_round is None:
                continue

            if not 1 <= current_round <= MAX_ROUNDS:
                continue

            home = match.group(1).strip()
            hg = int(match.group(2))
            ag = int(match.group(3))
            away = match.group(4).strip()

            if not home or not away:
                continue

            result = (
                "H" if hg > ag
                else "A" if hg < ag
                else "D"
            )

            matches.append({

                "tournament": name,
                "round": current_round,

                "home": home,
                "away": away,

                "hg": hg,
                "ag": ag,

                "score": f"{hg}-{ag}",

                "total": hg + ag,

                "difference": hg - ag,

                "btts": int(hg > 0 and ag > 0),

                "result": result
            })

    matches.sort(
        key=lambda x: (
            x["round"],
            x["home"],
            x["away"]
        )
    )

    return name, matches


# ===========================================================
# TEAM STATISTICS
# ===========================================================

def calculate_team_stats(matches):

    teams = defaultdict(lambda: {

        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,

        "gf": 0,
        "ga": 0,

        "points": 0,

        "home_played": 0,
        "away_played": 0,

        "home_gf": 0,
        "home_ga": 0,

        "away_gf": 0,
        "away_ga": 0,

        "form": []

    })

    for m in matches:

        h = teams[m["home"]]
        a = teams[m["away"]]

        hg = m["hg"]
        ag = m["ag"]

        h["played"] += 1
        a["played"] += 1

        h["gf"] += hg
        h["ga"] += ag

        a["gf"] += ag
        a["ga"] += hg

        h["home_played"] += 1
        a["away_played"] += 1

        h["home_gf"] += hg
        h["home_ga"] += ag

        a["away_gf"] += ag
        a["away_ga"] += hg

        if hg > ag:

            h["wins"] += 1
            a["losses"] += 1

            h["points"] += 3

            h["form"].append("W")
            a["form"].append("L")

        elif hg < ag:

            a["wins"] += 1
            h["losses"] += 1

            a["points"] += 3

            h["form"].append("L")
            a["form"].append("W")

        else:

            h["draws"] += 1
            a["draws"] += 1

            h["points"] += 1
            a["points"] += 1

            h["form"].append("D")
            a["form"].append("D")

    ranking = []

    for name, s in teams.items():

        ranking.append({

            "team": name,

            "played": s["played"],
            "points": s["points"],

            "wins": s["wins"],
            "draws": s["draws"],
            "losses": s["losses"],

            "gf": s["gf"],
            "ga": s["ga"],

            "gd": s["gf"] - s["ga"],

            "form": "".join(s["form"][-5:])

        })

    ranking.sort(
        key=lambda x: (
            x["points"],
            x["gd"],
            x["gf"]
        ),
        reverse=True
    )

    return teams, ranking


# ===========================================================
# HISTORICAL DISTRIBUTION
# ===========================================================

def historical_distribution(matches):

    if not matches:
        return {}

    scores = Counter(
        m["score"] for m in matches
    )

    return {

        "matches": len(matches),

        "distinct_scores": len(scores),

        "score_frequencies": dict(
            scores.most_common()
        ),

        "home_average": round(
            statistics.mean(
                m["hg"] for m in matches
            ), 5
        ),

        "away_average": round(
            statistics.mean(
                m["ag"] for m in matches
            ), 5
        ),

        "btts_percentage": round(
            100 * statistics.mean(
                m["btts"] for m in matches
            ), 4
        )

    }


# ===========================================================
# RNG DIAGNOSTICS
# ===========================================================

def autocorrelation(values):

    if len(values) < 3:
        return 0

    mean = statistics.mean(values)

    denominator = sum(
        (x - mean) ** 2 for x in values
    )

    if denominator == 0:
        return 0

    numerator = sum(
        (values[i] - mean) *
        (values[i - 1] - mean)
        for i in range(1, len(values))
    )

    return numerator / denominator


def rng_diagnostics(matches):

    if len(matches) < 3:

        return {
            "status": "INSUFFICIENT_DATA"
        }

    hg = [m["hg"] for m in matches]
    ag = [m["ag"] for m in matches]

    totals = [m["total"] for m in matches]

    return {

        "matches": len(matches),

        "home_mean": round(
            statistics.mean(hg), 5
        ),

        "away_mean": round(
            statistics.mean(ag), 5
        ),

        "total_mean": round(
            statistics.mean(totals), 5
        ),

        "home_variance": round(
            statistics.pvariance(hg), 5
        ),

        "away_variance": round(
            statistics.pvariance(ag), 5
        ),

        "total_variance": round(
            statistics.pvariance(totals), 5
        ),

        "home_lag1": round(
            autocorrelation(hg), 5
        ),

        "away_lag1": round(
            autocorrelation(ag), 5
        ),

        "total_lag1": round(
            autocorrelation(totals), 5
        ),

        "score_distribution": dict(
            Counter(
                m["score"] for m in matches
            )
        ),

        "note": (
            "Descriptive diagnostics. "
            "Not proof of deterministic RNG."
        )

    }


# ===========================================================
# SEQUENCE DETECTOR
# ===========================================================

def sequence_analysis(matches):

    rounds = defaultdict(list)

    for m in matches:
        rounds[m["round"]].append(m)

    signatures = {}

    for rnd, games in rounds.items():

        signatures[str(rnd)] = {

            "score_counts": dict(
                Counter(
                    m["score"] for m in games
                )
            ),

            "total_goals": sum(
                m["total"] for m in games
            ),

            "home_goals": sum(
                m["hg"] for m in games
            ),

            "away_goals": sum(
                m["ag"] for m in games
            )

        }

    repetitions = defaultdict(list)

    for m in matches:

        repetitions[m["score"]].append(
            m["round"]
        )

    repeat_lags = {}

    for score, rounds_found in repetitions.items():

        unique_rounds = sorted(
            set(rounds_found)
        )

        if len(unique_rounds) > 1:

            repeat_lags[score] = [

                unique_rounds[i] -
                unique_rounds[i - 1]

                for i in range(
                    1, len(unique_rounds)
                )

            ]

    return {

        "round_signatures": signatures,

        "repeated_scores": {
            k: v
            for k, v in repetitions.items()
            if len(v) > 1
        },

        "repeat_lags": repeat_lags

    }


# ===========================================================
# SCORE FINGERPRINTS
# ===========================================================

def score_fingerprints(matches):

    rounds = sorted(
        set(m["round"] for m in matches)
    )

    output = {}

    for rnd in rounds:

        history = [
            m for m in matches
            if m["round"] < rnd
        ]

        teams, _ = calculate_team_stats(history)

        games = []

        for m in matches:

            if m["round"] != rnd:
                continue

            hs = teams.get(m["home"], {})
            aws = teams.get(m["away"], {})

            games.append({

                "home": m["home"],
                "away": m["away"],

                "home_points": hs.get("points", 0),
                "away_points": aws.get("points", 0),

                "home_gf": hs.get("gf", 0),
                "home_ga": hs.get("ga", 0),

                "away_gf": aws.get("gf", 0),
                "away_ga": aws.get("ga", 0),

                "home_form": hs.get("form", [])[-5:],
                "away_form": aws.get("form", [])[-5:]

            })

        output[str(rnd)] = games

    return output


# ===========================================================
# POISSON
# ===========================================================

def poisson_probability(k, lam):

    try:

        if lam < 0:
            return 0

        value = (
            math.exp(-lam) *
            (lam ** k) /
            math.factorial(k)
        )

        return value if math.isfinite(value) else 0

    except (
        OverflowError,
        ValueError,
        ZeroDivisionError
    ):
        return 0


def expected_goals(history, home, away):

    if not history:
        return 1.3, 1.1

    teams, _ = calculate_team_stats(history)

    global_home = statistics.mean(
        m["hg"] for m in history
    )

    global_away = statistics.mean(
        m["ag"] for m in history
    )

    hs = teams.get(home)
    aws = teams.get(away)

    if not hs or not aws:
        return global_home, global_away

    home_attack = (
        hs["home_gf"] /
        max(hs["home_played"], 1)
    )

    away_defence = (
        aws["away_ga"] /
        max(aws["away_played"], 1)
    )

    away_attack = (
        aws["away_gf"] /
        max(aws["away_played"], 1)
    )

    home_defence = (
        hs["home_ga"] /
        max(hs["home_played"], 1)
    )

    lh = (home_attack + away_defence) / 2
    la = (away_attack + home_defence) / 2

    return (
        max(0.05, lh),
        max(0.05, la)
    )


def poisson_distribution(history, home, away):

    lh, la = expected_goals(
        history, home, away
    )

    results = []

    for hg in range(MAX_GOALS + 1):

        for ag in range(MAX_GOALS + 1):

            probability = (
                poisson_probability(hg, lh) *
                poisson_probability(ag, la)
            )

            results.append({

                "score": f"{hg}-{ag}",
                "hg": hg,
                "ag": ag,
                "probability": probability

            })

    results.sort(
        key=lambda x: x["probability"],
        reverse=True
    )

    return results


# ===========================================================
# MONTE CARLO
# ===========================================================

def monte_carlo(history, home, away):

    lh, la = expected_goals(
        history, home, away
    )

    distribution = Counter()

    for _ in range(MC_SIMULATIONS):

        hg = random.poisson(lh) if hasattr(
            random, "poisson"
        ) else poisson_sample(lh)

        ag = random.poisson(la) if hasattr(
            random, "poisson"
        ) else poisson_sample(la)

        distribution[f"{hg}-{ag}"] += 1

    output = []

    for score, count in distribution.most_common(20):

        output.append({

            "score": score,

            "count": count,

            "probability": round(
                count / MC_SIMULATIONS * 100,
                5
            )

        })

    return output


def poisson_sample(lam):

    # Knuth algorithm for Poisson sampling.
    if lam <= 0:
        return 0

    limit = math.exp(-lam)

    product = 1.0
    count = 0

    while product > limit:

        count += 1
        product *= random.random()

    return count - 1


# ===========================================================
# UNIVERSAL NUMBER EXTRACTION
# ===========================================================

def extract_all_numbers(matches, ranking=None):

    numbers = []

    def add(value, source):

        value = safe_number(value)

        if value is not None:

            numbers.append({

                "value": value,
                "source": source

            })

    for m in matches:

        for key in (
            "round",
            "hg",
            "ag",
            "total",
            "difference",
            "btts"
        ):

            add(
                m[key],
                key
            )

    if ranking:

        for team in ranking:

            for key in (
                "played",
                "points",
                "wins",
                "draws",
                "losses",
                "gf",
                "ga",
                "gd"
            ):

                add(
                    team.get(key),
                    "ranking_" + key
                )

    if matches:

        add(
            len(matches),
            "match_count"
        )

        add(
            statistics.mean(
                m["hg"] for m in matches
            ),
            "home_average"
        )

        add(
            statistics.mean(
                m["ag"] for m in matches
            ),
            "away_average"
        )

        add(
            statistics.mean(
                m["total"] for m in matches
            ),
            "total_average"
        )

        add(
            statistics.mean(
                m["btts"] for m in matches
            ) * 100,
            "btts_percentage"
        )

    return numbers


# ===========================================================
# MATHEMATICAL ENGINE
# ===========================================================

def apply_unary(x):

    results = []

    def add(value, expression):

        try:

            value = float(value)

            if (
                math.isfinite(value)
                and abs(value) <= MATH_MAX_ABS
            ):

                results.append(
                    (value, expression)
                )

        except (
            ValueError,
            TypeError,
            OverflowError
        ):
            pass

    # Square root
    if x >= 0:
        add(
            math.sqrt(x),
            f"sqrt({x})"
        )

    # Cube root
    add(
        math.copysign(
            abs(x) ** (1 / 3),
            x
        ),
        f"cuberoot({x})"
    )

    # Square
    add(
        x * x,
        f"({x})^2"
    )

    # Absolute value
    add(
        abs(x),
        f"abs({x})"
    )

    # Reciprocal
    if abs(x) > 1e-12:

        add(
            1 / x,
            f"1/({x})"
        )

    # Logarithms
    if x > 0:

        add(
            math.log(x),
            f"ln({x})"
        )

        add(
            math.log10(x),
            f"log10({x})"
        )

    # Trigonometry
    if abs(x) <= 100:

        add(
            math.sin(x),
            f"sin({x})"
        )

        add(
            math.cos(x),
            f"cos({x})"
        )

        add(
            math.tan(x),
            f"tan({x})"
        )

    # Exponential
    if abs(x) <= 10:

        try:
            add(
                math.exp(x),
                f"exp({x})"
            )
        except OverflowError:
            pass

    # Factorial
    if (
        x >= 0
        and x <= 10
        and x == int(x)
    ):

        add(
            math.factorial(int(x)),
            f"({int(x)})!"
        )

    # Floor / ceil
    add(
        math.floor(x),
        f"floor({x})"
    )

    add(
        math.ceil(x),
        f"ceil({x})"
    )

    # Percentage
    add(
        x / 100,
        f"({x})%"
    )

    return results


# ===========================================================
# CORRECTED BINARY OPERATIONS
# ===========================================================

def apply_binary(a, b):

    results = []

    def add(value, expression):

        try:

            value = float(value)

            if (
                math.isfinite(value)
                and abs(value) <= MATH_MAX_ABS
            ):

                results.append(
                    (value, expression)
                )

        except (
            ValueError,
            TypeError,
            OverflowError,
            ZeroDivisionError
        ):
            pass

    # Addition
    add(a + b, f"({a}+{b})")

    # Subtraction
    add(a - b, f"({a}-{b})")
    add(b - a, f"({b}-{a})")

    # Multiplication
    add(a * b, f"({a}*{b})")

    # Division
    if abs(b) > 1e-12:
        add(a / b, f"({a}/{b})")

    if abs(a) > 1e-12:
        add(b / a, f"({b}/{a})")

    # Powers: a^b
    if abs(b) <= 10 and b == int(b):

        exponent = int(b)

        # FIX: zero cannot be raised to a negative power.
        if not (
            abs(a) < 1e-12
            and exponent < 0
        ):

            try:

                add(
                    a ** exponent,
                    f"({a}^{exponent})"
                )

            except (
                OverflowError,
                ValueError,
                ZeroDivisionError
            ):
                pass

    # Powers: b^a
    if abs(a) <= 10 and a == int(a):

        exponent = int(a)

        if not (
            abs(b) < 1e-12
            and exponent < 0
        ):

            try:

                add(
                    b ** exponent,
                    f"({b}^{exponent})"
                )

            except (
                OverflowError,
                ValueError,
                ZeroDivisionError
            ):
                pass

    # Roots
    if a >= 0 and b > 0:

        try:

            add(
                a ** (1 / b),
                f"root({b},{a})"
            )

        except (
            OverflowError,
            ValueError,
            ZeroDivisionError
        ):
            pass

    if b >= 0 and a > 0:

        try:

            add(
                b ** (1 / a),
                f"root({a},{b})"
            )

        except (
            OverflowError,
            ValueError,
            ZeroDivisionError
        ):
            pass

    return results


# ===========================================================
# NUMBER ATOMS
# ===========================================================

def make_number_atoms(numbers):

    atoms = []

    for item in numbers:

        value = item["value"]

        atoms.append({

            "value": value,

            "expression": str(
                clean_number(value)
            ),

            "depth": 0

        })

        # Digit transformations
        if (
            value >= 0
            and value == int(value)
            and len(str(int(value))) > 1
        ):

            text_value = str(int(value))

            digit_sum = sum(
                int(c) for c in text_value
            )

            atoms.append({

                "value": digit_sum,

                "expression": (
                    f"digit_sum({text_value})"
                ),

                "depth": 1

            })

            reverse = int(
                text_value[::-1]
            )

            atoms.append({

                "value": reverse,

                "expression": (
                    f"reverse({text_value})"
                ),

                "depth": 1

            })

    # Remove duplicate numeric atoms.
    unique = {}

    for atom in atoms:

        key = round(
            atom["value"],
            8
        )

        if key not in unique:

            unique[key] = atom

    atoms = list(unique.values())

    # Bounded search for performance.
    if len(atoms) > MATH_MAX_ATOMS:

        atoms.sort(
            key=lambda x: abs(x["value"])
        )

        atoms = atoms[:MATH_MAX_ATOMS]

    return atoms


# ===========================================================
# BFS / DFS STATE SEARCH
# ===========================================================

def prune_states(states, target):

    unique = {}

    for state in states:

        key = round(
            state["value"],
            8
        )

        if key not in unique:

            unique[key] = state

        elif len(state["expression"]) < len(
            unique[key]["expression"]
        ):

            unique[key] = state

    result = list(unique.values())

    result.sort(
        key=lambda x: (
            abs(x["value"] - target),
            len(x["expression"])
        )
    )

    return result[:MATH_MAX_STATES]


def search_target(numbers, target):

    atoms = make_number_atoms(numbers)

    if not atoms:
        return []

    states = atoms[:]
    frontier = atoms[:]

    found = []

    for state in states:

        if abs(
            state["value"] - target
        ) < 1e-8:

            found.append(state)

    # Breadth-first expansion.
    for depth in range(
        1,
        MATH_MAX_DEPTH + 1
    ):

        candidates = []

        # Unary transformations.
        for state in frontier:

            for value, expression in apply_unary(
                state["value"]
            ):

                candidates.append({

                    "value": value,
                    "expression": expression,
                    "depth": depth

                })

        # Binary transformations.
        for state in frontier:

            for atom in atoms:

                for value, expression in apply_binary(
                    state["value"],
                    atom["value"]
                ):

                    candidates.append({

                        "value": value,
                        "expression": (
                            expression
                            + " ["
                            + state["expression"]
                            + "]"
                        ),

                        "depth": depth

                    })

        frontier = prune_states(
            candidates,
            target
        )

        states.extend(frontier)

        for state in frontier:

            if abs(
                state["value"] - target
            ) < 1e-8:

                found.append(state)

        if found:
            break

    # Deduplicate formulas.
    unique_found = {}

    for item in found:

        expression = item["expression"]

        unique_found[expression] = {

            "expression": expression,

            "result": clean_number(
                item["value"]
            ),

            "target": target,

            "error": round(
                abs(
                    item["value"] - target
                ),
                10
            )

        }

    return list(
        unique_found.values()
    )[:50]


# ===========================================================
# DISCOVERY MODE
# ===========================================================

def discovery_mode(matches):

    if not matches:
        return []

    teams, ranking = calculate_team_stats(matches)

    numbers = extract_all_numbers(
        matches,
        ranking
    )

    # Search each distinct goal only once.
    # This avoids repeating the same calculation
    # hundreds of times.
    unique_goals = sorted(
        set(
            goal
            for m in matches
            for goal in (m["hg"], m["ag"])
        )
    )

    formula_cache = {}

    for goal in unique_goals:

        formula_cache[goal] = search_target(
            numbers,
            goal
        )

    output = []

    for m in matches:

        output.append({

            "round": m["round"],

            "home": m["home"],
            "away": m["away"],

            "observed_score": m["score"],

            "home_goal_formulas": (
                formula_cache[m["hg"]]
            ),

            "away_goal_formulas": (
                formula_cache[m["ag"]]
            ),

            "mode": "DISCOVERY"

        })

    return output


# ===========================================================
# BLIND MODE
# ===========================================================

def blind_mode(history):

    if len(history) < 3:
        return []

    teams, ranking = calculate_team_stats(history)

    numbers = extract_all_numbers(
        history,
        ranking
    )

    results = []

    for goal in range(MAX_GOALS + 1):

        formulas = search_target(
            numbers,
            goal
        )

        results.append({

            "goal_candidate": goal,

            "formula_count": len(formulas),

            "formulas": formulas[:10]

        })

    return results


# ===========================================================
# MATCH PREDICTION
# ===========================================================

def predict_match(history, match):

    poisson = poisson_distribution(
        history,
        match["home"],
        match["away"]
    )

    mc = monte_carlo(
        history,
        match["home"],
        match["away"]
    )

    frequencies = Counter(
        m["score"] for m in history
    )

    total = max(
        len(history),
        1
    )

    scores = {}

    for row in poisson:

        score = row["score"]

        p_poisson = row["probability"]

        p_frequency = (
            frequencies[score] / total
        )

        scores[score] = (
            0.65 * p_poisson
            + 0.35 * p_frequency
        )

    ranked = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return {

        "home": match["home"],
        "away": match["away"],

        "predictions": [

            {

                "score": score,

                "probability": round(
                    probability * 100,
                    5
                )

            }

            for score, probability in ranked[:10]

        ],

        "monte_carlo_top": mc[:10],

        "model": "POISSON_FREQUENCY_ENSEMBLE"

    }


# ===========================================================
# WALK-FORWARD BACKTEST
# ===========================================================

def walk_forward_backtest(matches):

    tested = 0

    top1 = 0
    top3 = 0
    top5 = 0

    rows = []

    rounds = sorted(
        set(
            m["round"] for m in matches
        )
    )

    for rnd in rounds:

        history = [
            m for m in matches
            if m["round"] < rnd
        ]

        targets = [
            m for m in matches
            if m["round"] == rnd
        ]

        if not history:
            continue

        for match in targets:

            prediction = predict_match(
                history,
                match
            )

            predicted = [
                x["score"]
                for x in prediction["predictions"]
            ]

            tested += 1

            hit1 = (
                len(predicted) >= 1
                and predicted[0] == match["score"]
            )

            hit3 = (
                match["score"] in predicted[:3]
            )

            hit5 = (
                match["score"] in predicted[:5]
            )

            top1 += int(hit1)
            top3 += int(hit3)
            top5 += int(hit5)

            rows.append({

                "round": rnd,

                "home": match["home"],
                "away": match["away"],

                "observed": match["score"],

                "predicted_top5": predicted[:5],

                "top1_hit": hit1,
                "top3_hit": hit3,
                "top5_hit": hit5

            })

    return {

        "tested_matches": tested,

        "top1_hits": top1,
        "top3_hits": top3,
        "top5_hits": top5,

        "top1_percentage": round(
            top1 / tested * 100,
            4
        ) if tested else 0,

        "top3_percentage": round(
            top3 / tested * 100,
            4
        ) if tested else 0,

        "top5_percentage": round(
            top5 / tested * 100,
            4
        ) if tested else 0,

        "results": rows

    }


# ===========================================================
# CROSS TOURNAMENT
# ===========================================================

def cross_tournament_analysis(tournaments):

    if len(tournaments) < 2:

        return {

            "status": "NO_EXTERNAL_TOURNAMENT",

            "tournaments": len(tournaments),

            "message": (
                "Add another independent tournament "
                "to perform cross-validation."
            )

        }

    results = {}

    for name, matches in tournaments.items():

        results[name] = {

            "matches": len(matches),

            "distribution": historical_distribution(
                matches
            )

        }

    return {

        "status": "COMPARISON_AVAILABLE",

        "tournaments": results

    }


# ===========================================================
# TELEGRAM
# ===========================================================

def telegram_send(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:

        import urllib.request
        import urllib.parse

        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_TOKEN
            + "/sendMessage"
        )

        data = urllib.parse.urlencode({

            "chat_id": TELEGRAM_CHAT_ID,
            "text": message

        }).encode()

        request = urllib.request.Request(
            url,
            data=data
        )

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            return response.status == 200

    except Exception as error:

        print(
            "Telegram error:",
            error
        )

        return False


def telegram_report(
    name,
    matches,
    backtest,
    distribution
):

    latest_round = max(
        m["round"] for m in matches
    )

    latest = [
        m for m in matches
        if m["round"] == latest_round
    ]

    lines = [

        "━━━━━━━━━━━━━━━━━━━━",

        "🧠 TESLA V5 — GLOBAL REPORT",

        "━━━━━━━━━━━━━━━━━━━━",

        f"🏆 {name}",

        f"📅 J1 à J{latest_round}",

        f"⚽ Matchs : {len(matches)}",

        "",

        "🔬 MATHEMATICAL ENGINE",

        "Universal Number Hunter : ACTIVE",

        "BFS / DFS : ACTIVE",

        "Arithmetic Search : ACTIVE",

        "Discovery Mode : ACTIVE",

        "Blind Mode : ACTIVE",

        "",

        "📊 WALK-FORWARD BACKTEST",

        f"Testés : {backtest['tested_matches']}",

        f"Top 1 : {backtest['top1_percentage']}%",

        f"Top 3 : {backtest['top3_percentage']}%",

        f"Top 5 : {backtest['top5_percentage']}%",

        "",

        "📈 HISTORIQUE",

        f"Scores distincts : {distribution['distinct_scores']}",

        f"Moyenne domicile : {distribution['home_average']}",

        f"Moyenne extérieur : {distribution['away_average']}",

        f"BTTS : {distribution['btts_percentage']}%",

        "",

        "⚠️ HISTORICAL REPLAY",

        "━━━━━━━━━━━━━━━━━━━━"

    ]

    for m in latest[:10]:

        lines.append(
            f"{m['home']} {m['score']} {m['away']}"
        )

    telegram_send(
        "\n".join(lines)
    )


# ===========================================================
# TOURNAMENT ANALYSIS
# ===========================================================

def analyze_tournament(name, matches):

    print("\n" + "=" * 55)

    print(
        "🧠 TESLA V5:",
        name
    )

    print("=" * 55)

    if not matches:
        return None

    teams, ranking = calculate_team_stats(
        matches
    )

    distribution = historical_distribution(
        matches
    )

    rng = rng_diagnostics(
        matches
    )

    sequences = sequence_analysis(
        matches
    )

    fingerprints = score_fingerprints(
        matches
    )

    print(
        "Matches:",
        len(matches)
    )

    print(
        "Rounds:",
        len(set(m["round"] for m in matches))
    )

    print(
        "Distinct scores:",
        distribution["distinct_scores"]
    )

    print("\nRunning walk-forward backtest...")

    backtest = walk_forward_backtest(
        matches
    )

    print(
        "Backtest tested:",
        backtest["tested_matches"]
    )

    print(
        "Top 1:",
        backtest["top1_percentage"],
        "%"
    )

    print(
        "Top 3:",
        backtest["top3_percentage"],
        "%"
    )

    print(
        "Top 5:",
        backtest["top5_percentage"],
        "%"
    )

    print("\nRunning mathematical discovery...")

    discovery = discovery_mode(
        matches
    )

    print(
        "Discovery matches:",
        len(discovery)
    )

    # Latest round replay.
    latest_round = max(
        m["round"] for m in matches
    )

    latest_matches = [
        m for m in matches
        if m["round"] == latest_round
    ]

    latest_history = [
        m for m in matches
        if m["round"] < latest_round
    ]

    predictions = []

    for m in latest_matches:

        prediction = predict_match(
            latest_history,
            m
        )

        prediction["round"] = latest_round

        prediction["observed_score"] = m["score"]

        prediction["mode"] = "HISTORICAL_REPLAY"

        predictions.append(
            prediction
        )

    # Blind mathematical analysis using only
    # data before the latest round.
    blind = blind_mode(
        latest_history
    )

    numbers = extract_all_numbers(
        matches,
        ranking
    )

    inventory = {

        "total_numeric_values": len(numbers),

        "unique_numeric_values": len(
            set(
                round(x["value"], 8)
                for x in numbers
            )
        )

    }

    prefix = safe_filename(name)

    # Compact output files.
    write_json(
        f"{prefix}_summary.json",
        {

            "tournament": name,

            "matches": len(matches),

            "rounds": sorted(
                set(m["round"] for m in matches)
            ),

            "distribution": distribution,

            "ranking": ranking

        }
    )

    write_json(
        f"{prefix}_predictions.json",
        predictions
    )

    write_json(
        f"{prefix}_fingerprints.json",
        fingerprints
    )

    write_json(
        f"{prefix}_sequences.json",
        sequences
    )

    write_json(
        f"{prefix}_rng_analysis.json",
        rng
    )

    write_json(
        f"{prefix}_backtest.json",
        backtest
    )

    write_json(
        f"{prefix}_discovery.json",
        discovery
    )

    write_json(
        f"{prefix}_blind_math.json",
        blind
    )

    write_json(
        f"{prefix}_number_inventory.json",
        inventory
    )

    telegram_report(
        name,
        matches,
        backtest,
        distribution
    )

    print("\nTESLA V5 ANALYSIS FINISHED.")

    return {

        "tournament": name,

        "matches": len(matches),

        "distribution": distribution,

        "backtest": backtest,

        "inventory": inventory

    }


# ===========================================================
# MAIN
# ===========================================================

def main():

    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 TESLA V5
UNIVERSAL MATHEMATICAL DISCOVERY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

    files = [

        os.path.join(DATA_DIR, f)

        for f in os.listdir(DATA_DIR)

        if f.lower().endswith(".txt")

    ]

    files.sort()

    if not files:

        print(
            "No tournament files found."
        )

        print(
            "Add files to data/tournaments/"
        )

        return

    tournaments = {}

    for path in files:

        name, matches = parse_tournament(
            path
        )

        if not matches:

            print(
                "Skipped:",
                name
            )

            continue

        tournaments[name] = matches

    if not tournaments:

        print(
            "No valid tournament data."
        )

        return

    reports = {}

    for name, matches in tournaments.items():

        reports[name] = analyze_tournament(
            name,
            matches
        )

    cross = cross_tournament_analysis(
        tournaments
    )

    write_json(
        "cross_tournament.json",
        cross
    )

    total_matches = sum(
        len(matches)
        for matches in tournaments.values()
    )

    global_summary = {

        "version": "TESLA_V5",

        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "tournaments": len(tournaments),

        "total_matches": total_matches,

        "monte_carlo_simulations": MC_SIMULATIONS,

        "mathematical_search": {

            "max_atoms": MATH_MAX_ATOMS,

            "max_states": MATH_MAX_STATES,

            "max_depth": MATH_MAX_DEPTH

        },

        "cross_tournament": cross,

        "reports": reports

    }

    write_json(
        "global_summary.json",
        global_summary
    )

    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ TESLA V5 ANALYSIS FINISHED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

    print(
        "Tournaments:",
        len(tournaments)
    )

    print(
        "Total matches:",
        total_matches
    )

    print(
        "Monte Carlo simulations:",
        MC_SIMULATIONS
    )

    print(
        "Output:",
        OUTPUT_DIR
    )


if __name__ == "__main__":

    main()