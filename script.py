#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================
 TESLA V5 — UNIVERSAL MATHEMATICAL DISCOVERY ENGINE
============================================================

Modules:
  1. Tournament Parser
  2. Historical Statistics
  3. Score Frequency Engine
  4. Team Ranking and Form
  5. Score Fingerprints
  6. Sequence Detector
  7. RNG Diagnostics
  8. Monte Carlo
  9. BFS / DFS Arithmetic Discovery
 10. Mathematical Expression Hunter
 11. Blind Score Prediction
 12. Walk-Forward Backtest
 13. Cross-Tournament Analysis
 14. Compact JSON Reports
 15. Optional Telegram Notification

Input:
  data/tournaments/tournoi_001.txt

Format:
  Journée 1
  Arsenal 2-1 Chelsea
  Liverpool 3-0 Everton

  Journée 2
  ...

IMPORTANT:
  Discovery mode can use the observed score.
  Blind mode only uses information available before the match.
============================================================
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


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(
    BASE_DIR, "data", "tournaments"
)

OUTPUT_DIR = os.path.join(
    BASE_DIR, "output"
)

MAX_ROUNDS = 37
MAX_GOALS = 7

MONTE_CARLO_SIMULATIONS = int(
    os.getenv("MONTE_CARLO_SIMULATIONS", "100000")
)

# Recherche mathématique : limites de calcul.
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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

random.seed(RANDOM_SEED)

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# UTILITIES
# ============================================================

def safe_float(value):
    try:
        x = float(value)
        if math.isfinite(x):
            return x
    except (ValueError, TypeError):
        pass
    return None


def clean_number(value):
    if value is None:
        return None

    if abs(value) < 1e-10:
        return 0

    if abs(value - round(value)) < 1e-9:
        return int(round(value))

    return round(value, 8)


def safe_filename(name):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def write_json(filename, data):
    path = os.path.join(OUTPUT_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    return path


def data_hash(files):
    h = hashlib.sha256()

    for path in sorted(files):
        with open(path, "rb") as f:
            h.update(f.read())

    return h.hexdigest()


# ============================================================
# TOURNAMENT PARSER
# ============================================================

MATCH_PATTERN = re.compile(
    r"^(.*?)\s+(\d+)\s*[-:]\s*(\d+)\s+(.*?)$"
)

ROUND_PATTERN = re.compile(
    r"journ[eé]e\s*(\d+)",
    re.IGNORECASE
)


def parse_tournament(path):

    tournament = os.path.splitext(
        os.path.basename(path)
    )[0]

    matches = []
    current_round = None

    with open(path, "r", encoding="utf-8-sig") as f:

        for raw_line in f:

            line = raw_line.strip()

            if not line:
                continue

            round_match = ROUND_PATTERN.search(line)

            if round_match:
                current_round = int(round_match.group(1))
                continue

            match = MATCH_PATTERN.match(line)

            if not match or current_round is None:
                continue

            home = match.group(1).strip()
            home_goals = int(match.group(2))
            away_goals = int(match.group(3))
            away = match.group(4).strip()

            if not home or not away:
                continue

            if current_round < 1 or current_round > MAX_ROUNDS:
                continue

            matches.append({
                "tournament": tournament,
                "round": current_round,
                "home": home,
                "away": away,
                "hg": home_goals,
                "ag": away_goals,
                "score": f"{home_goals}-{away_goals}",
                "total": home_goals + away_goals,
                "difference": home_goals - away_goals,
                "btts": int(home_goals > 0 and away_goals > 0),
                "result": (
                    "H" if home_goals > away_goals
                    else "A" if home_goals < away_goals
                    else "D"
                )
            })

    matches.sort(key=lambda x: x["round"])

    return tournament, matches


# ============================================================
# HISTORICAL STATISTICS
# ============================================================

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


def historical_distribution(matches):

    scores = Counter(
        m["score"] for m in matches
    )

    if not matches:
        return {}

    home_avg = statistics.mean(
        m["hg"] for m in matches
    )

    away_avg = statistics.mean(
        m["ag"] for m in matches
    )

    btts = sum(
        m["btts"] for m in matches
    ) / len(matches)

    return {
        "matches": len(matches),
        "distinct_scores": len(scores),
        "score_frequencies": dict(scores.most_common()),
        "home_average": round(home_avg, 5),
        "away_average": round(away_avg, 5),
        "btts_percentage": round(btts * 100, 4)
    }


# ============================================================
# RNG DIAGNOSTICS
# ============================================================

def rng_diagnostics(matches):

    if len(matches) < 3:
        return {"status": "INSUFFICIENT_DATA"}

    hg = [m["hg"] for m in matches]
    ag = [m["ag"] for m in matches]

    totals = [m["total"] for m in matches]

    def autocorrelation(values):

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

    return {
        "home_mean": round(statistics.mean(hg), 5),
        "away_mean": round(statistics.mean(ag), 5),
        "total_mean": round(statistics.mean(totals), 5),

        "home_variance": round(
            statistics.pvariance(hg), 5
        ),

        "away_variance": round(
            statistics.pvariance(ag), 5
        ),

        "total_variance": round(
            statistics.pvariance(totals), 5
        ),

        "home_lag1": round(autocorrelation(hg), 5),
        "away_lag1": round(autocorrelation(ag), 5),
        "total_lag1": round(autocorrelation(totals), 5),

        "score_distribution": dict(
            Counter(m["score"] for m in matches)
        ),

        "note": (
            "Descriptive diagnostics only; "
            "not proof of a deterministic RNG."
        )
    }


# ============================================================
# SEQUENCE DETECTOR
# ============================================================

def sequence_analysis(matches):

    rounds = defaultdict(list)

    for m in matches:
        rounds[m["round"]].append(m)

    round_signatures = {}

    for rnd, games in rounds.items():

        score_counts = Counter(
            m["score"] for m in games
        )

        round_signatures[rnd] = {
            "score_counts": dict(score_counts),
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

    exact_repeats = defaultdict(list)

    for m in matches:

        exact_repeats[m["score"]].append({
            "round": m["round"],
            "home": m["home"],
            "away": m["away"]
        })

    repeat_lags = {}

    for score, occurrences in exact_repeats.items():

        rounds_found = sorted(
            x["round"] for x in occurrences
        )

        if len(rounds_found) > 1:

            repeat_lags[score] = [
                rounds_found[i] - rounds_found[i - 1]
                for i in range(1, len(rounds_found))
            ]

    return {
        "round_signatures": round_signatures,
        "exact_score_repetitions": {
            k: v for k, v in exact_repeats.items()
            if len(v) > 1
        },
        "repeat_lags": repeat_lags
    }


# ============================================================
# SCORE FINGERPRINTS
# ============================================================

def score_fingerprint(matches, target_round):

    previous = [
        m for m in matches
        if m["round"] < target_round
    ]

    teams, ranking = calculate_team_stats(previous)

    fingerprints = []

    for m in matches:

        if m["round"] != target_round:
            continue

        home_stats = teams.get(m["home"], {})
        away_stats = teams.get(m["away"], {})

        fingerprints.append({
            "home": m["home"],
            "away": m["away"],

            "home_played": home_stats.get("played", 0),
            "away_played": away_stats.get("played", 0),

            "home_points": home_stats.get("points", 0),
            "away_points": away_stats.get("points", 0),

            "home_gf": home_stats.get("gf", 0),
            "home_ga": home_stats.get("ga", 0),

            "away_gf": away_stats.get("gf", 0),
            "away_ga": away_stats.get("ga", 0),

            "home_form": home_stats.get("form", [])[-5:],
            "away_form": away_stats.get("form", [])[-5:]
        })

    return fingerprints


# ============================================================
# POISSON MODEL
# ============================================================

def poisson_probability(k, lam):

    if lam < 0:
        return 0

    try:
        return (
            math.exp(-lam) *
            (lam ** k) /
            math.factorial(k)
        )
    except (OverflowError, ValueError):
        return 0


def estimate_expected_goals(history, home, away):

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
        hs["home_gf"] / max(hs["home_played"], 1)
    )

    home_defence = (
        hs["home_ga"] / max(hs["home_played"], 1)
    )

    away_attack = (
        aws["away_gf"] / max(aws["away_played"], 1)
    )

    away_defence = (
        aws["away_ga"] / max(aws["away_played"], 1)
    )

    expected_home = (
        home_attack + away_defence
    ) / 2

    expected_away = (
        away_attack + home_defence
    ) / 2

    return (
        max(0.15, expected_home),
        max(0.15, expected_away)
    )


def poisson_score_distribution(history, home, away):

    lh, la = estimate_expected_goals(
        history, home, away
    )

    results = []

    for hg in range(MAX_GOALS + 1):

        for ag in range(MAX_GOALS + 1):

            p = (
                poisson_probability(hg, lh) *
                poisson_probability(ag, la)
            )

            results.append({
                "score": f"{hg}-{ag}",
                "hg": hg,
                "ag": ag,
                "probability": p
            })

    return sorted(
        results,
        key=lambda x: x["probability"],
        reverse=True
    )


# ============================================================
# MONTE CARLO ENGINE
# ============================================================

def monte_carlo(history, home, away):

    distribution = Counter()

    if not history:
        return []

    for _ in range(MONTE_CARLO_SIMULATIONS):

        sample = random.choice(history)

        # Empirical bootstrap:
        # score pairs are sampled from past matches.
        distribution[sample["score"]] += 1

    total = MONTE_CARLO_SIMULATIONS

    result = []

    for score, count in distribution.most_common(20):

        result.append({
            "score": score,
            "count": count,
            "probability": round(
                count / total * 100, 5
            )
        })

    return result


# ============================================================
# UNIVERSAL NUMBER EXTRACTION
# ============================================================

def extract_all_numbers(matches, ranking=None):

    numbers = []

    def add(value, source):

        x = safe_float(value)

        if x is None:
            return

        numbers.append({
            "value": x,
            "source": source
        })

    for m in matches:

        add(m["round"], "round")
        add(m["hg"], "home_goals")
        add(m["ag"], "away_goals")
        add(m["total"], "total_goals")
        add(m["difference"], "goal_difference")

        add(
            int(m["hg"] > m["ag"]),
            "home_win"
        )

        add(
            int(m["hg"] == m["ag"]),
            "draw"
        )

        add(
            int(m["hg"] < m["ag"]),
            "away_win"
        )

        add(m["btts"], "btts")

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

    # Statistical values derived from available history.
    if matches:

        add(len(matches), "match_count")

        add(
            statistics.mean(m["hg"] for m in matches),
            "average_home_goals"
        )

        add(
            statistics.mean(m["ag"] for m in matches),
            "average_away_goals"
        )

        add(
            statistics.mean(m["total"] for m in matches),
            "average_total_goals"
        )

    return numbers


# ============================================================
# MATHEMATICAL EXPRESSION ENGINE
# ============================================================

def apply_unary(x):

    results = []

    if x >= 0:
        results.append(
            (math.sqrt(x), f"√({x})")
        )

    if x >= 0 and x <= 100:
        results.append(
            (x * x, f"({x})²")
        )

    if abs(x) > 1e-12:
        results.append(
            (1 / x, f"1/({x})")
        )

    if x > 0:
        results.append(
            (math.log(x), f"ln({x})")
        )

        results.append(
            (math.log10(x), f"log10({x})")
        )

    if abs(x) <= 20:
        results.append(
            (math.sin(x), f"sin({x})")
        )

        results.append(
            (math.cos(x), f"cos({x})")
        )

    if x >= 0 and x <= 10 and x == int(x):
        results.append(
            (math.factorial(int(x)), f"({int(x)})!")
        )

    if abs(x) <= 10:
        results.append(
            (math.exp(x), f"exp({x})")
        )

    if abs(x) <= 100:
        results.append(
            (math.floor(x), f"floor({x})")
        )

        results.append(
            (math.ceil(x), f"ceil({x})")
        )

    results.append(
        (abs(x), f"|{x}|")
    )

    return [
        (v, e) for v, e in results
        if math.isfinite(v)
        and abs(v) <= MATH_MAX_ABS
    ]


def apply_binary(a, b):

    results = []

    results.append(
        (a + b, f"({a}+{b})")
    )

    results.append(
        (a - b, f"({a}-{b})")
    )

    results.append(
        (b - a, f"({b}-{a})")
    )

    results.append(
        (a * b, f"({a}*{b})")
    )

    if abs(b) > 1e-12:
        results.append(
            (a / b, f"({a}/{b})")
        )

    if abs(a) > 1e-12:
        results.append(
            (b / a, f"({b}/{a})")
        )

    if abs(b) <= 10 and b == int(b):
        try:
            results.append(
                (a ** int(b), f"({a}^{int(b)})")
            )
        except (OverflowError, ValueError):
            pass

    if abs(a) <= 10 and a == int(a):
        try:
            results.append(
                (b ** int(a), f"({b}^{int(a)})")
            )
        except (OverflowError, ValueError):
            pass

    if a >= 0 and b > 0:
        results.append(
            (a ** (1 / b), f"root({b},{a})")
        )

    return [
        (v, e) for v, e in results
        if math.isfinite(v)
        and abs(v) <= MATH_MAX_ABS
    ]


def make_number_atoms(numbers):

    atoms = []

    for item in numbers:

        value = item["value"]

        atoms.append({
            "value": value,
            "expression": str(clean_number(value)),
            "depth": 0
        })

        # Digit sum and reverse.
        text_value = str(abs(clean_number(value)))

        if (
            isinstance(clean_number(value), int)
            and len(text_value) > 1
        ):

            digit_sum = sum(
                int(c) for c in text_value
            )

            atoms.append({
                "value": digit_sum,
                "expression": f"digit_sum({text_value})",
                "depth": 1
            })

            reverse = int(text_value[::-1])

            atoms.append({
                "value": reverse,
                "expression": f"reverse({text_value})",
                "depth": 1
            })

    return atoms


def prune_states(states, target):

    best = {}

    for state in states:

        value = state["value"]

        key = round(value, 8)

        if key not in best:
            best[key] = state

        else:

            if len(state["expression"]) < len(
                best[key]["expression"]
            ):
                best[key] = state

    values = list(best.values())

    values.sort(
        key=lambda s: (
            abs(s["value"] - target),
            len(s["expression"])
        )
    )

    return values[:MATH_MAX_STATES]


def search_target(numbers, target):

    atoms = make_number_atoms(numbers)

    # Remove duplicate starting values.
    unique = {}

    for atom in atoms:

        key = round(atom["value"], 8)

        if key not in unique:
            unique[key] = atom

    atoms = list(unique.values())

    # Keep the most relevant numerical inputs.
    if len(atoms) > MATH_MAX_ATOMS:

        atoms.sort(
            key=lambda x: (
                abs(x["value"] - target),
                len(x["expression"])
            )
        )

        atoms = atoms[:MATH_MAX_ATOMS]

    states = atoms[:]
    frontier = atoms[:]

    found = []

    for state in states:

        if abs(state["value"] - target) < 1e-8:
            found.append(state)

    for depth in range(1, MATH_MAX_DEPTH + 1):

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

        # Binary operations between current states
        # and original numeric atoms.
        for state in frontier:

            for atom in atoms:

                for value, expression in apply_binary(
                    state["value"],
                    atom["value"]
                ):

                    candidates.append({
                        "value": value,
                        "expression": expression,
                        "depth": depth
                    })

        candidates = prune_states(
            candidates, target
        )

        frontier = candidates
        states.extend(candidates)

        for state in candidates:

            if abs(state["value"] - target) < 1e-8:

                found.append(state)

        if found:
            break

    # Deduplicate formulas.
    unique_found = {}

    for item in found:

        unique_found[item["expression"]] = {
            "expression": item["expression"],
            "result": clean_number(item["value"]),
            "target": target,
            "error": round(
                abs(item["value"] - target), 10
            )
        }

    return list(unique_found.values())[:50]


# ============================================================
# DISCOVERY MODE
# ============================================================

def discovery_mode(matches):

    numbers = extract_all_numbers(matches)

    results = []

    for m in matches:

        home_target = m["hg"]
        away_target = m["ag"]

        home_formulas = search_target(
            numbers, home_target
        )

        away_formulas = search_target(
            numbers, away_target
        )

        results.append({
            "round": m["round"],
            "home": m["home"],
            "away": m["away"],
            "observed_score": m["score"],

            "home_goal_formulas": home_formulas,
            "away_goal_formulas": away_formulas,

            "mode": "DISCOVERY"
        })

    return results


# ============================================================
# BLIND MATHEMATICAL PREDICTION
# ============================================================

def blind_math_prediction(history):

    if len(history) < 3:
        return []

    teams, ranking = calculate_team_stats(history)

    numbers = extract_all_numbers(
        history, ranking
    )

    # Candidate goals are found from expressions.
    candidates = []

    for goal in range(MAX_GOALS + 1):

        home_formulas = search_target(
            numbers, goal
        )

        away_formulas = search_target(
            numbers, goal
        )

        candidates.append({
            "goal": goal,
            "home_formula_count": len(home_formulas),
            "away_formula_count": len(away_formulas)
        })

    return candidates


# ============================================================
# MATCH PREDICTION
# ============================================================

def predict_match(history, match):

    poisson = poisson_score_distribution(
        history,
        match["home"],
        match["away"]
    )

    mc = monte_carlo(
        history,
        match["home"],
        match["away"]
    )

    # Blend Poisson and historical frequency.
    frequency = Counter(
        m["score"] for m in history
    )

    scores = {}

    for row in poisson:

        score = row["score"]

        p_poisson = row["probability"]

        p_frequency = (
            frequency[score] / max(len(history), 1)
        )

        scores[score] = (
            0.65 * p_poisson +
            0.35 * p_frequency
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
                    probability * 100, 5
                )
            }
            for score, probability in ranked[:10]
        ],

        "monte_carlo_top": mc[:10],

        "model": "POISSON_FREQUENCY_ENSEMBLE"
    }


# ============================================================
# WALK-FORWARD BACKTEST
# ============================================================

def walk_forward_backtest(matches):

    tested = 0
    top1 = 0
    top3 = 0
    top5 = 0

    rows = []

    for m in matches:

        history = [
            x for x in matches
            if x["round"] < m["round"]
        ]

        if not history:
            continue

        prediction = predict_match(
            history, m
        )

        predicted = [
            x["score"]
            for x in prediction["predictions"]
        ]

        tested += 1

        hit1 = (
            len(predicted) >= 1
            and predicted[0] == m["score"]
        )

        hit3 = m["score"] in predicted[:3]
        hit5 = m["score"] in predicted[:5]

        top1 += int(hit1)
        top3 += int(hit3)
        top5 += int(hit5)

        rows.append({
            "round": m["round"],
            "home": m["home"],
            "away": m["away"],
            "observed": m["score"],
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
            top1 / tested * 100, 4
        ) if tested else 0,

        "top3_percentage": round(
            top3 / tested * 100, 4
        ) if tested else 0,

        "top5_percentage": round(
            top5 / tested * 100, 4
        ) if tested else 0,

        "results": rows
    }


# ============================================================
# CROSS TOURNAMENT
# ============================================================

def cross_tournament_analysis(tournaments):

    if len(tournaments) < 2:

        return {
            "status": "NO_EXTERNAL_TOURNAMENT",
            "tournaments": len(tournaments),
            "message": (
                "Add at least one independent tournament "
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


# ============================================================
# TELEGRAM
# ============================================================

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
            request, timeout=20
        ) as response:

            return response.status == 200

    except Exception as e:

        print("Telegram error:", e)

        return False


def telegram_report(
    tournament,
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
        f"🏆 {tournament}",
        f"📅 J1 à J{latest_round}",
        f"⚽ Matchs : {len(matches)}",
        "",
        "🔬 MATHEMATICAL DISCOVERY",
        "Universal Number Hunter : ACTIVE",
        "BFS / DFS : ACTIVE",
        "Arithmetic Search : ACTIVE",
        "Blind Test : ACTIVE",
        "",
        "📊 BACKTEST",
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
        "⚠️ Analyse statistique historique.",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    for m in latest[:10]:

        lines.append(
            f"{m['home']} {m['score']} {m['away']}"
        )

    telegram_send("\n".join(lines))


# ============================================================
# MAIN TOURNAMENT ANALYSIS
# ============================================================

def analyze_tournament(name, matches):

    print("\n" + "=" * 60)
    print("TESLA V5:", name)
    print("=" * 60)

    if not matches:
        print("No matches found.")
        return None

    teams, ranking = calculate_team_stats(matches)

    distribution = historical_distribution(matches)

    rng = rng_diagnostics(matches)

    sequences = sequence_analysis(matches)

    fingerprints = {}

    for rnd in range(1, MAX_ROUNDS + 1):

        data = score_fingerprint(
            matches, rnd
        )

        if data:
            fingerprints[str(rnd)] = data

    print("Matches:", len(matches))
    print("Rounds:", len(set(
        m["round"] for m in matches
    )))

    print("\nRunning walk-forward backtest...")

    backtest = walk_forward_backtest(matches)

    print("Backtest tested:", backtest["tested_matches"])
    print("Top 1:", backtest["top1_percentage"], "%")
    print("Top 3:", backtest["top3_percentage"], "%")
    print("Top 5:", backtest["top5_percentage"], "%")

    print("\nRunning arithmetic discovery...")

    discovery = discovery_mode(matches)

    print("Discovery completed:", len(discovery))

    # Blind predictions for the latest round.
    latest_round = max(
        m["round"] for m in matches
    )

    latest_matches = [
        m for m in matches
        if m["round"] == latest_round
    ]

    blind_predictions = []

    for m in latest_matches:

        history = [
            x for x in matches
            if x["round"] < latest_round
        ]

        prediction = predict_match(
            history, m
        )

        prediction["round"] = latest_round
        prediction["observed_score"] = m["score"]
        prediction["mode"] = "HISTORICAL_REPLAY"

        blind_predictions.append(prediction)

    # Extract numbers from the complete historical dataset.
    all_numbers = extract_all_numbers(
        matches, ranking
    )

    result = {
        "tournament": name,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "matches": len(matches),

        "ranking": ranking,

        "distribution": distribution,

        "rng_diagnostics": rng,

        "sequences": sequences,

        "fingerprints": fingerprints,

        "arithmetic_discovery": discovery,

        "blind_predictions": blind_predictions,

        "backtest": backtest,

        "number_inventory": {
            "total_numeric_values": len(all_numbers),
            "unique_values": len(set(
                round(x["value"], 8)
                for x in all_numbers
            ))
        }
    }

    prefix = safe_filename(name)

    write_json(
        f"{prefix}_summary.json",
        {
            "tournament": name,
            "matches": len(matches),
            "distribution": distribution,
            "ranking": ranking
        }
    )

    write_json(
        f"{prefix}_predictions.json",
        blind_predictions
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
        f"{prefix}_number_inventory.json",
        result["number_inventory"]
    )

    telegram_report(
        name,
        matches,
        backtest,
        distribution
    )

    print("\nTESLA V5 ANALYSIS FINISHED.")

    return result


# ============================================================
# GLOBAL MAIN
# ============================================================

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

        print("No tournament files found.")
        print("Add files in data/tournaments/")
        return

    tournaments = {}
    reports = {}

    for path in files:

        name, matches = parse_tournament(path)

        if not matches:
            print("Skipped:", name)
            continue

        tournaments[name] = matches

    if not tournaments:

        print("No valid tournament data.")
        return

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

    # Compact global summary.
    global_summary = {
        "version": "TESLA_V5",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "tournaments": len(tournaments),

        "total_matches": sum(
            len(x) for x in tournaments.values()
        ),

        "cross_tournament": cross
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

    print("Tournaments:", len(tournaments))

    print(
        "Total matches:",
        global_summary["total_matches"]
    )

    print("Output:", OUTPUT_DIR)


if __name__ == "__main__":
    main()