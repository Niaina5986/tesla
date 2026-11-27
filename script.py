# ============================================================
# TESLA — REVERSE SCORE INTELLIGENCE
# Version 1.0
# Analyse inversée des scores de tournois virtuels
#
# MOTEURS :
# 1. Historical Engine
# 2. Ranking Engine
# 3. Goal Engine
# 4. Form Engine
# 5. Day Gap Engine
# 6. Ricochet Engine
# 7. BFS Engine
# 8. DFS Engine
# 9. RNG Pattern Detector
# 10. Combination Engine
# 11. Monte Carlo Engine
# 12. Exact Score Engine
# 13. Reverse Score Engine
# 14. Backtesting Engine
# 15. AI Learning Engine
#
# IMPORTANT :
# Chaque tournoi contient 37 journées.
# Les résultats d'une journée ne servent jamais à calculer
# les informations disponibles AVANT cette même journée.
# ============================================================

import os
import re
import json
import math
import random
import argparse
import statistics
from collections import Counter, defaultdict
from datetime import datetime

try:
    import numpy as np
except ImportError:
    np = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


# ============================================================
# CONFIGURATION
# ============================================================

ROUNDS = 37
MATCHES_PER_ROUND = 10

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data", "tournaments")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

SIMULATIONS = int(os.getenv("TESLA_SIMULATIONS", "100000"))

MAX_GRAPH_NODES = 40
MAX_BFS_DEPTH = 5
MAX_DFS_DEPTH = 7

RANDOM_SEED = 261

random.seed(RANDOM_SEED)

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# JSON UTILITIES
# ============================================================

def save_json(filename, data):

    path = os.path.join(OUTPUT_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )

    print(f"[SAVED] {filename}")


def safe_float(value, default=0):

    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def clamp(value, minimum, maximum):

    return max(minimum, min(maximum, value))


def normalize(value):

    return str(value).strip()


# ============================================================
# INPUT PARSER
# ============================================================

ROUND_RE = re.compile(
    r"JOURN(?:ÉE|EE)\s*(\d+)",
    re.IGNORECASE
)

SCORE_RE = re.compile(
    r"^(.*?)\s+(\d+)\s*[-–:]\s*(\d+)\s+(.*?)$"
)


def parse_text(text, tournament_name):

    matches = []

    current_round = None

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        round_match = ROUND_RE.search(line)

        if round_match:

            current_round = int(round_match.group(1))
            continue

        if current_round is None:
            continue

        score_match = SCORE_RE.match(line)

        if not score_match:
            continue

        home = normalize(score_match.group(1))
        home_goals = int(score_match.group(2))
        away_goals = int(score_match.group(3))
        away = normalize(score_match.group(4))

        if not home or not away:
            continue

        if home_goals > 30 or away_goals > 30:
            continue

        matches.append({

            "tournament": tournament_name,

            "round": current_round,

            "home": home,

            "away": away,

            "home_goals": home_goals,

            "away_goals": away_goals,

            "score": f"{home_goals}-{away_goals}",

            "total_goals": home_goals + away_goals,

            "goal_difference": home_goals - away_goals

        })

    return matches


def load_pdf(path):

    if PdfReader is None:

        raise RuntimeError(
            "pypdf absent. Installe-le avec : pip install pypdf"
        )

    reader = PdfReader(path)

    text = "\n".join(
        page.extract_text() or ""
        for page in reader.pages
    )

    return text


def load_text_file(path):

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_tournaments():

    all_matches = []

    if not os.path.exists(DATA_DIR):
        return all_matches

    files = sorted(os.listdir(DATA_DIR))

    for filename in files:

        path = os.path.join(DATA_DIR, filename)

        if not os.path.isfile(path):
            continue

        ext = os.path.splitext(filename)[1].lower()

        try:

            if ext == ".pdf":
                text = load_pdf(path)

            elif ext in [".txt", ".csv"]:
                text = load_text_file(path)

            else:
                continue

            tournament_name = os.path.splitext(filename)[0]

            matches = parse_text(
                text,
                tournament_name
            )

            print(
                f"[IMPORT] {filename}: {len(matches)} matchs"
            )

            all_matches.extend(matches)

        except Exception as e:

            print(f"[ERROR] {filename}: {e}")

    return all_matches


# ============================================================
# DATA VALIDATION
# ============================================================

def validate_tournaments(matches):

    tournaments = defaultdict(list)

    for match in matches:

        tournaments[match["tournament"]].append(match)

    valid = []

    for name, games in tournaments.items():

        rounds_found = Counter(
            m["round"] for m in games
        )

        print(f"\n[VALIDATION] {name}")

        print("Nombre de matchs :", len(games))

        print("Journées trouvées :", len(rounds_found))

        for day in range(1, ROUNDS + 1):

            count = rounds_found.get(day, 0)

            if count != MATCHES_PER_ROUND:

                print(
                    f"[WARNING] J{day}: {count}/10 matchs"
                )

        valid.extend(games)

    return valid


# ============================================================
# BASIC MATCH FEATURES
# ============================================================

def result_type(home_goals, away_goals):

    if home_goals > away_goals:
        return "HOME_WIN"

    if home_goals < away_goals:
        return "AWAY_WIN"

    return "DRAW"


def score_signature(home_goals, away_goals):

    total = home_goals + away_goals

    difference = abs(home_goals - away_goals)

    return {

        "total": total,

        "difference": difference,

        "result": result_type(
            home_goals,
            away_goals
        ),

        "home_parity": home_goals % 2,

        "away_parity": away_goals % 2,

        "both_scored": (
            home_goals > 0 and away_goals > 0
        )

    }


# ============================================================
# RANKING ENGINE
# ============================================================

def build_ranking(previous_matches):

    table = defaultdict(lambda: {

        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "gf": 0,
        "ga": 0,
        "points": 0

    })

    for m in previous_matches:

        home = m["home"]
        away = m["away"]

        hg = m["home_goals"]
        ag = m["away_goals"]

        h = table[home]
        a = table[away]

        h["played"] += 1
        a["played"] += 1

        h["gf"] += hg
        h["ga"] += ag

        a["gf"] += ag
        a["ga"] += hg

        if hg > ag:

            h["wins"] += 1
            h["points"] += 3

            a["losses"] += 1

        elif hg < ag:

            a["wins"] += 1
            a["points"] += 3

            h["losses"] += 1

        else:

            h["draws"] += 1
            a["draws"] += 1

            h["points"] += 1
            a["points"] += 1

    ranking = {}

    for team, stats in table.items():

        stats["gd"] = stats["gf"] - stats["ga"]

        stats["goals_per_match"] = (
            stats["gf"] / stats["played"]
            if stats["played"] else 0
        )

        stats["conceded_per_match"] = (
            stats["ga"] / stats["played"]
            if stats["played"] else 0
        )

        ranking[team] = dict(stats)

    ordered = sorted(

        ranking.items(),

        key=lambda x: (

            x[1]["points"],
            x[1]["gd"],
            x[1]["gf"]

        ),

        reverse=True

    )

    for position, (team, stats) in enumerate(
        ordered,
        start=1
    ):

        ranking[team]["position"] = position

    return ranking


# ============================================================
# HISTORICAL ENGINE
# ============================================================

def team_history(team, previous_matches):

    history = []

    for m in previous_matches:

        if m["home"] == team:

            history.append({

                "opponent": m["away"],
                "gf": m["home_goals"],
                "ga": m["away_goals"],
                "round": m["round"],
                "venue": "HOME"

            })

        elif m["away"] == team:

            history.append({

                "opponent": m["home"],
                "gf": m["away_goals"],
                "ga": m["home_goals"],
                "round": m["round"],
                "venue": "AWAY"

            })

    return history


def recent_form(team, previous_matches, limit=5):

    history = team_history(
        team,
        previous_matches
    )

    history = history[-limit:]

    points = 0
    gf = 0
    ga = 0

    for m in history:

        gf += m["gf"]
        ga += m["ga"]

        if m["gf"] > m["ga"]:
            points += 3

        elif m["gf"] == m["ga"]:
            points += 1

    return {

        "matches": len(history),

        "points": points,

        "gf": gf,

        "ga": ga,

        "average_gf": gf / len(history) if history else 0,

        "average_ga": ga / len(history) if history else 0

    }


# ============================================================
# DAY GAP ENGINE
# ============================================================

def last_match_round(team, previous_matches):

    rounds = [

        m["round"]

        for m in previous_matches

        if team in (m["home"], m["away"])

    ]

    return max(rounds) if rounds else None


def calculate_gap(team, current_round, previous_matches):

    last_round = last_match_round(
        team,
        previous_matches
    )

    if last_round is None:
        return None

    return current_round - last_round


# ============================================================
# FEATURE ENGINE
# ============================================================

def match_features(match, previous_matches):

    home = match["home"]
    away = match["away"]

    ranking = build_ranking(
        previous_matches
    )

    home_stats = ranking.get(home, {})
    away_stats = ranking.get(away, {})

    home_form = recent_form(
        home,
        previous_matches
    )

    away_form = recent_form(
        away,
        previous_matches
    )

    return {

        "home_position": home_stats.get("position", 20),

        "away_position": away_stats.get("position", 20),

        "points_difference": (
            home_stats.get("points", 0)
            - away_stats.get("points", 0)
        ),

        "goal_difference_difference": (
            home_stats.get("gd", 0)
            - away_stats.get("gd", 0)
        ),

        "home_attack": home_stats.get(
            "goals_per_match", 0
        ),

        "away_attack": away_stats.get(
            "goals_per_match", 0
        ),

        "home_defence": home_stats.get(
            "conceded_per_match", 0
        ),

        "away_defence": away_stats.get(
            "conceded_per_match", 0
        ),

        "home_form_points": home_form["points"],

        "away_form_points": away_form["points"],

        "home_form_gf": home_form["average_gf"],

        "away_form_gf": away_form["average_gf"],

        "home_gap": calculate_gap(
            home,
            match["round"],
            previous_matches
        ),

        "away_gap": calculate_gap(
            away,
            match["round"],
            previous_matches
        )

    }


# ============================================================
# HISTORICAL SCORE DATABASE
# ============================================================

def build_history_database(matches):

    database = defaultdict(list)

    for m in matches:

        key = (
            m["home"],
            m["away"]
        )

        database[key].append(m)

    return dict(database)


# ============================================================
# RICOCHET ENGINE
# ============================================================

def ricochet_search(target, previous_matches):

    hg = target["home_goals"]
    ag = target["away_goals"]

    total = hg + ag
    difference = hg - ag

    exact = []
    inverted = []
    same_total = []
    same_difference = []
    same_result = []

    for m in previous_matches:

        x = m["home_goals"]
        y = m["away_goals"]

        if x == hg and y == ag:
            exact.append(m)

        if x == ag and y == hg and x != y:
            inverted.append(m)

        if x + y == total:
            same_total.append(m)

        if abs(x - y) == abs(difference):
            same_difference.append(m)

        if result_type(x, y) == result_type(hg, ag):
            same_result.append(m)

    return {

        "target_score": target["score"],

        "exact_matches": exact,

        "inverted_matches": inverted,

        "same_total": same_total,

        "same_difference": same_difference,

        "same_result": same_result,

        "counts": {

            "exact": len(exact),

            "inverted": len(inverted),

            "same_total": len(same_total),

            "same_difference": len(same_difference),

            "same_result": len(same_result)

        }

    }


# ============================================================
# GRAPH SIMILARITY ENGINE
# ============================================================

def score_distance(a, b):

    return (

        abs(a["home_goals"] - b["home_goals"])

        +

        abs(a["away_goals"] - b["away_goals"])

    )


def feature_distance(a, b):

    fa = a.get("features", {})
    fb = b.get("features", {})

    keys = [

        "home_position",
        "away_position",
        "points_difference",
        "goal_difference_difference",
        "home_attack",
        "away_attack",
        "home_defence",
        "away_defence",
        "home_form_points",
        "away_form_points"

    ]

    distance = 0

    for key in keys:

        distance += abs(
            safe_float(fa.get(key))
            - safe_float(fb.get(key))
        )

    return distance


def build_similarity_graph(target, previous_matches):

    candidates = []

    for m in previous_matches:

        distance = score_distance(
            target,
            m
        )

        feature_diff = feature_distance(
            target,
            m
        )

        candidates.append({

            "match": m,

            "score_distance": distance,

            "feature_distance": feature_diff,

            "weight": (
                distance * 1.0
                + feature_diff * 0.25
            )

        })

    candidates.sort(
        key=lambda x: x["weight"]
    )

    selected = candidates[:MAX_GRAPH_NODES]

    graph = defaultdict(list)

    for i in range(len(selected)):

        for j in range(i + 1, len(selected)):

            a = selected[i]["match"]
            b = selected[j]["match"]

            d = score_distance(a, b)

            if d <= 2:

                graph[i].append(j)
                graph[j].append(i)

    return selected, graph


# ============================================================
# BFS ENGINE
# ============================================================

def bfs_search(nodes, graph, max_depth=MAX_BFS_DEPTH):

    if not nodes:
        return []

    queue = [(0, 0)]

    visited = set()

    results = []

    while queue:

        node, depth = queue.pop(0)

        if node in visited:
            continue

        visited.add(node)

        results.append({

            "node": node,

            "depth": depth,

            "match": nodes[node]["match"],

            "weight": nodes[node]["weight"]

        })

        if depth >= max_depth:
            continue

        for neighbor in graph[node]:

            if neighbor not in visited:

                queue.append(
                    (neighbor, depth + 1)
                )

    return results


# ============================================================
# DFS ENGINE
# ============================================================

def dfs_search(nodes, graph, max_depth=MAX_DFS_DEPTH):

    if not nodes:
        return []

    stack = [(0, 0)]

    visited = set()

    results = []

    while stack:

        node, depth = stack.pop()

        if node in visited:
            continue

        visited.add(node)

        results.append({

            "node": node,

            "depth": depth,

            "match": nodes[node]["match"],

            "weight": nodes[node]["weight"]

        })

        if depth >= max_depth:
            continue

        for neighbor in reversed(graph[node]):

            if neighbor not in visited:

                stack.append(
                    (neighbor, depth + 1)
                )

    return results


# ============================================================
# RNG PATTERN DETECTOR
# ============================================================

def rng_analysis(matches):

    if not matches:

        return {}

    scores = Counter(
        m["score"] for m in matches
    )

    totals = Counter(
        m["total_goals"] for m in matches
    )

    results = Counter(
        result_type(
            m["home_goals"],
            m["away_goals"]
        )
        for m in matches
    )

    exact_repetitions = {

        score: count

        for score, count in scores.items()

        if count > 1

    }

    repeated_totals = {

        total: count

        for total, count in totals.items()

        if count > 1

    }

    home_scores = [
        m["home_goals"] for m in matches
    ]

    away_scores = [
        m["away_goals"] for m in matches
    ]

    return {

        "sample_size": len(matches),

        "score_frequency": dict(scores),

        "total_frequency": dict(totals),

        "result_frequency": dict(results),

        "repeated_exact_scores": exact_repetitions,

        "repeated_goal_totals": repeated_totals,

        "average_home_goals": statistics.mean(
            home_scores
        ),

        "average_away_goals": statistics.mean(
            away_scores
        ),

        "home_goals_variance": statistics.pvariance(
            home_scores
        ),

        "away_goals_variance": statistics.pvariance(
            away_scores
        )

    }


# ============================================================
# COMBINATION ENGINE
# ============================================================

def combination_analysis(target, previous_matches):

    signature = score_signature(

        target["home_goals"],
        target["away_goals"]

    )

    related = []

    for m in previous_matches:

        s = score_signature(

            m["home_goals"],
            m["away_goals"]

        )

        similarities = []

        if s["total"] == signature["total"]:
            similarities.append("SAME_TOTAL")

        if s["difference"] == signature["difference"]:
            similarities.append("SAME_DIFFERENCE")

        if s["result"] == signature["result"]:
            similarities.append("SAME_RESULT")

        if s["both_scored"] == signature["both_scored"]:
            similarities.append("BOTH_SCORED_PATTERN")

        if similarities:

            related.append({

                "match": m,

                "similarities": similarities,

                "similarity_count": len(similarities)

            })

    related.sort(

        key=lambda x: x["similarity_count"],

        reverse=True

    )

    return related


# ============================================================
# MONTE CARLO ENGINE
# ============================================================

def monte_carlo(target, previous_matches, simulations):

    if not previous_matches:

        return {
            "simulations": 0,
            "score_frequency": {},
            "message": "Insufficient history"
        }

    # Les scores historiques servent de distribution empirique.
    # Le poids est basé sur la proximité des caractéristiques
    # pré-match et non sur le résultat futur du match cible.

    candidates = []

    for m in previous_matches:

        score_diff = score_distance(
            target,
            m
        )

        feature_diff = feature_distance(
            target,
            m
        )

        weight = 1.0 / (
            1.0
            + score_diff
            + feature_diff * 0.10
        )

        candidates.append((m, weight))

    weights = [
        item[1] for item in candidates
    ]

    total_weight = sum(weights)

    if total_weight <= 0:

        weights = [1.0] * len(candidates)
        total_weight = len(candidates)

    probabilities = [
        w / total_weight for w in weights
    ]

    scores = [
        m["score"] for m, _ in candidates
    ]

    if np is not None:

        sampled = np.random.default_rng().choice(

            scores,

            size=simulations,

            p=probabilities

        )

        frequency = Counter(
            sampled.tolist()
        )

    else:

        frequency = Counter(
            random.choices(
                scores,
                weights=probabilities,
                k=simulations
            )
        )

    ranked = frequency.most_common(20)

    return {

        "simulations": simulations,

        "historical_sample": len(previous_matches),

        "score_frequency": dict(frequency),

        "top_scores": [

            {

                "score": score,

                "count": count,

                "frequency_percent": (
                    count / simulations * 100
                )

            }

            for score, count in ranked

        ],

        "method": "Weighted empirical bootstrap",

        "interpretation": (
            "Frequencies of simulated historical analogues; "
            "not probabilities of a hidden RNG outcome."
        )

    }


# ============================================================
# EXACT SCORE ENGINE
# ============================================================

def exact_score_analysis(target, previous_matches):

    scores = Counter(
        m["score"] for m in previous_matches
    )

    total = len(previous_matches)

    ranked = scores.most_common(20)

    return {

        "target_score": target["score"],

        "historical_occurrences": scores.get(
            target["score"], 0
        ),

        "historical_sample": total,

        "historical_frequency_percent": (

            scores.get(target["score"], 0)
            / total * 100

            if total else 0

        ),

        "most_common_scores": [

            {

                "score": score,

                "count": count,

                "frequency_percent": (
                    count / total * 100
                ) if total else 0

            }

            for score, count in ranked

        ]

    }


# ============================================================
# REVERSE SCORE ENGINE
# ============================================================

def reverse_analysis(target, previous_matches):

    print(
        f"\n[REVERSE] J{target['round']} "
        f"{target['home']} {target['score']} "
        f"{target['away']}"
    )

    features = match_features(
        target,
        previous_matches
    )

    target_with_features = dict(target)

    target_with_features["features"] = features

    historical = team_history(
        target["home"],
        previous_matches
    )

    away_historical = team_history(
        target["away"],
        previous_matches
    )

    ricochet = ricochet_search(
        target,
        previous_matches
    )

    combinations = combination_analysis(
        target,
        previous_matches
    )

    nodes, graph = build_similarity_graph(
        target_with_features,
        previous_matches
    )

    bfs = bfs_search(
        nodes,
        graph
    )

    dfs = dfs_search(
        nodes,
        graph
    )

    exact = exact_score_analysis(
        target,
        previous_matches
    )

    return {

        "match": target,

        "pre_match_features": features,

        "home_history": historical,

        "away_history": away_historical,

        "ranking_before_match": build_ranking(
            previous_matches
        ),

        "ricochet": ricochet,

        "combinations": combinations,

        "bfs": bfs,

        "dfs": dfs,

        "exact_score": exact

    }


# ============================================================
# BACKTESTING ENGINE
# ============================================================

def backtest(matches):

    correct_exact = 0

    total = 0

    score_frequency = Counter()

    records = []

    for tournament in sorted(
        set(m["tournament"] for m in matches)
    ):

        tournament_matches = [

            m for m in matches

            if m["tournament"] == tournament

        ]

        for day in range(1, ROUNDS + 1):

            previous = [

                m for m in tournament_matches

                if m["round"] < day

            ]

            current = [

                m for m in tournament_matches

                if m["round"] == day

            ]

            for target in current:

                if not previous:
                    continue

                historical_scores = Counter(
                    m["score"] for m in previous
                )

                if not historical_scores:
                    continue

                predicted_score = (
                    historical_scores.most_common(1)[0][0]
                )

                actual_score = target["score"]

                correct = (
                    predicted_score == actual_score
                )

                if correct:
                    correct_exact += 1

                total += 1

                score_frequency[
                    predicted_score
                ] += 1

                records.append({

                    "tournament": tournament,

                    "round": day,

                    "match": (
                        target["home"]
                        + " vs "
                        + target["away"]
                    ),

                    "predicted": predicted_score,

                    "actual": actual_score,

                    "exact_correct": correct

                })

    return {

        "method": "Walk-forward historical majority baseline",

        "tested_matches": total,

        "exact_correct": correct_exact,

        "exact_accuracy_percent": (

            correct_exact / total * 100

            if total else 0

        ),

        "records": records

    }


# ============================================================
# AI LEARNING ENGINE
# ============================================================

def learning_analysis(matches):

    score_counts = Counter(
        m["score"] for m in matches
    )

    total_counts = Counter(
        m["total_goals"] for m in matches
    )

    result_counts = Counter(

        result_type(
            m["home_goals"],
            m["away_goals"]
        )

        for m in matches

    )

    return {

        "training_matches": len(matches),

        "score_patterns": dict(score_counts),

        "goal_total_patterns": dict(total_counts),

        "result_patterns": dict(result_counts),

        "most_frequent_score": (

            score_counts.most_common(1)[0][0]

            if score_counts else None

        ),

        "most_frequent_total": (

            total_counts.most_common(1)[0][0]

            if total_counts else None

        )

    }


# ============================================================
# MAIN ANALYSIS
# ============================================================

def run_analysis(simulations=SIMULATIONS):

    print("\n")
    print("=" * 60)
    print("TESLA — REVERSE SCORE INTELLIGENCE")
    print("=" * 60)

    matches = load_tournaments()

    if not matches:

        print(
            "\nAucun résultat trouvé dans data/tournaments/"
        )

        return

    matches = validate_tournaments(matches)

    if not matches:
        return

    # Trier chronologiquement
    matches.sort(

        key=lambda m: (

            m["tournament"],
            m["round"]

        )

    )

    save_json(
        "history.json",
        matches
    )

    reverse_results = []

    ricochet_database = []

    prediction_database = []

    ranking_database = {}

    rng_database = {}

    # --------------------------------------------------------
    # WALK-FORWARD ANALYSIS
    # --------------------------------------------------------

    for tournament in sorted(
        set(m["tournament"] for m in matches)
    ):

        tournament_matches = [

            m for m in matches

            if m["tournament"] == tournament

        ]

        print(
            f"\n[TOURNAMENT] {tournament}"
        )

        for day in range(1, ROUNDS + 1):

            previous = [

                m for m in tournament_matches

                if m["round"] < day

            ]

            current = [

                m for m in tournament_matches

                if m["round"] == day

            ]

            if not current:
                continue

            ranking = build_ranking(
                previous
            )

            ranking_database[
                f"{tournament}_J{day}"
            ] = ranking

            # Tous les matchs d'une journée sont traités
            # avec les mêmes informations préalables.

            for target in current:

                analysis = reverse_analysis(
                    target,
                    previous
                )

                reverse_results.append(
                    analysis
                )

                ricochet_database.append({

                    "tournament": tournament,

                    "round": day,

                    "match": target,

                    "ricochet": analysis["ricochet"]

                })

                # Monte Carlo uniquement sur les trois
                # dernières journées pour limiter le coût.

                if day >= 35 and previous:

                    mc = monte_carlo(

                        analysis["match"],

                        previous,

                        simulations

                    )

                    prediction_database.append({

                        "tournament": tournament,

                        "round": day,

                        "match": target,

                        "monte_carlo": mc

                    })

            print(
                f"[DONE] {tournament} J{day} "
                f"| {len(current)} matchs"
            )

    # --------------------------------------------------------
    # GLOBAL ANALYSIS
    # --------------------------------------------------------

    global_rng = rng_analysis(matches)

    learning = learning_analysis(matches)

    performance = backtest(matches)

    models = {

        "created_at": datetime.utcnow().isoformat(),

        "tournaments": len(
            set(m["tournament"] for m in matches)
        ),

        "rounds_per_tournament": ROUNDS,

        "total_matches": len(matches),

        "learning": learning,

        "rng_analysis": global_rng

    }

    # --------------------------------------------------------
    # SAVE EVERYTHING
    # --------------------------------------------------------

    save_json(
        "reverse_analysis.json",
        reverse_results
    )

    save_json(
        "ranking.json",
        ranking_database
    )

    save_json(
        "ricochet.json",
        ricochet_database
    )

    save_json(
        "predictions.json",
        prediction_database
    )

    save_json(
        "rng_database.json",
        global_rng
    )

    save_json(
        "models.json",
        models
    )

    save_json(
        "performance.json",
        performance
    )

    # --------------------------------------------------------
    # FINAL REPORT
    # --------------------------------------------------------

    print("\n")
    print("=" * 60)
    print("TESLA — ANALYSIS TERMINÉE")
    print("=" * 60)

    print("Tournois :", models["tournaments"])

    print("Matchs :", len(matches))

    print(
        "Simulations Monte Carlo :",
        simulations
    )

    print(
        "Backtests :",
        performance["tested_matches"]
    )

    print(
        "Exact score baseline :",
        round(
            performance["exact_accuracy_percent"],
            2
        ),
        "%"
    )

    print("\nFichiers générés dans :", OUTPUT_DIR)

    print("=" * 60)


# ============================================================
# COMMAND LINE
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(

        "--simulations",

        type=int,

        default=SIMULATIONS,

        help="Nombre de simulations Monte Carlo"

    )

    args = parser.parse_args()

    run_analysis(
        simulations=args.simulations
    )