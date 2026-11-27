# ============================================================
# TESLA — REVERSE SCORE INTELLIGENCE V3
# Analyse inverse des résultats virtuels J1 à J37
# ============================================================

import os
import re
import json
import random
import argparse
import statistics
import urllib.request
import urllib.parse

from datetime import datetime, timezone
from collections import Counter, defaultdict, deque

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data", "tournaments")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

ROUNDS = 37
MATCHES_PER_ROUND = 10

DEFAULT_SIMULATIONS = int(
    os.getenv("TESLA_SIMULATIONS", "100000")
)

MAX_GRAPH_NODES = 40
MAX_BFS_DEPTH = 5
MAX_DFS_DEPTH = 7

RANDOM_SEED = 261
random.seed(RANDOM_SEED)

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Secrets non configurés.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }

    data = urllib.parse.urlencode(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("ok", False)

    except Exception as error:
        print("[TELEGRAM ERROR]", error)
        return False


def telegram_send_long(message):

    limit = 3800

    while len(message) > limit:

        position = message.rfind("\n", 0, limit)

        if position <= 0:
            position = limit

        telegram_send(message[:position])

        message = message[position:].lstrip()

    if message:
        telegram_send(message)


# ============================================================
# JSON
# ============================================================

def save_json(filename, data):

    path = os.path.join(OUTPUT_DIR, filename)

    temporary = path + ".tmp"

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    os.replace(temporary, path)

    print("[SAVED]", filename)


def safe_float(value, default=0):

    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# ============================================================
# INPUT PARSER
# ============================================================

ROUND_RE = re.compile(
    r"(?:JOURN(?:ÉE|EE)|J)\s*(\d+)",
    re.IGNORECASE
)

SCORE_RE = re.compile(
    r"^(.+?)\s+(\d{1,2})\s*[-–:]\s*"
    r"(\d{1,2})\s+(.+?)$"
)


def parse_text(text, tournament):

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

        if not 1 <= current_round <= ROUNDS:
            continue

        score_match = SCORE_RE.match(line)

        if not score_match:
            continue

        home = score_match.group(1).strip()
        hg = int(score_match.group(2))
        ag = int(score_match.group(3))
        away = score_match.group(4).strip()

        if not home or not away:
            continue

        if home.lower() == away.lower():
            continue

        if hg > 30 or ag > 30:
            continue

        matches.append({
            "tournament": tournament,
            "round": current_round,
            "home": home,
            "away": away,
            "home_goals": hg,
            "away_goals": ag,
            "score": f"{hg}-{ag}",
            "total_goals": hg + ag,
            "goal_difference": hg - ag
        })

    return matches


def read_input_file(path):

    extension = os.path.splitext(path)[1].lower()

    if extension == ".pdf":

        if PdfReader is None:
            raise RuntimeError(
                "pypdf absent. Ajoute pypdf dans requirements.txt."
            )

        reader = PdfReader(path)

        return "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )

    if extension in (".txt", ".csv"):

        with open(
            path,
            "r",
            encoding="utf-8-sig"
        ) as file:

            return file.read()

    return None


def load_tournaments():

    all_matches = []

    for filename in sorted(os.listdir(DATA_DIR)):

        path = os.path.join(DATA_DIR, filename)

        if not os.path.isfile(path):
            continue

        try:

            text = read_input_file(path)

            if text is None:
                continue

            tournament = os.path.splitext(filename)[0]

            matches = parse_text(text, tournament)

            print(
                f"[IMPORT] {filename}: "
                f"{len(matches)} matchs"
            )

            all_matches.extend(matches)

        except Exception as error:

            print("[IMPORT ERROR]", filename, error)

    return all_matches


# ============================================================
# VALIDATION
# ============================================================

def validate_data(matches):

    valid = []
    seen = set()

    tournaments = defaultdict(list)

    for match in matches:

        key = (
            match["tournament"],
            match["round"],
            match["home"].lower(),
            match["away"].lower()
        )

        if key in seen:
            print("[DUPLICATE]", key)
            continue

        seen.add(key)

        tournaments[match["tournament"]].append(match)
        valid.append(match)

    for name, games in tournaments.items():

        by_round = Counter(
            match["round"] for match in games
        )

        print("\n[VALIDATION]", name)
        print("Total:", len(games))

        for day in range(1, ROUNDS + 1):

            count = by_round.get(day, 0)

            if count != MATCHES_PER_ROUND:

                print(
                    f"[WARNING] J{day}: "
                    f"{count}/{MATCHES_PER_ROUND} matchs"
                )

    return valid


# ============================================================
# RESULT ENGINE
# ============================================================

def result_type(hg, ag):

    if hg > ag:
        return "HOME_WIN"

    if hg < ag:
        return "AWAY_WIN"

    return "DRAW"


def score_signature(hg, ag):

    return {
        "total": hg + ag,
        "difference": abs(hg - ag),
        "result": result_type(hg, ag),
        "home_parity": hg % 2,
        "away_parity": ag % 2,
        "both_scored": hg > 0 and ag > 0
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

    for match in previous_matches:

        home = table[match["home"]]
        away = table[match["away"]]

        hg = match["home_goals"]
        ag = match["away_goals"]

        home["played"] += 1
        away["played"] += 1

        home["gf"] += hg
        home["ga"] += ag

        away["gf"] += ag
        away["ga"] += hg

        if hg > ag:

            home["wins"] += 1
            home["points"] += 3
            away["losses"] += 1

        elif hg < ag:

            away["wins"] += 1
            away["points"] += 3
            home["losses"] += 1

        else:

            home["draws"] += 1
            away["draws"] += 1

            home["points"] += 1
            away["points"] += 1

    ordered = []

    for team, stats in table.items():

        stats["gd"] = stats["gf"] - stats["ga"]

        played = stats["played"]

        stats["goals_per_match"] = (
            stats["gf"] / played if played else 0
        )

        stats["conceded_per_match"] = (
            stats["ga"] / played if played else 0
        )

        ordered.append((team, dict(stats)))

    ordered.sort(
        key=lambda item: (
            item[1]["points"],
            item[1]["gd"],
            item[1]["gf"]
        ),
        reverse=True
    )

    ranking = {}

    for position, (team, stats) in enumerate(ordered, 1):

        stats["position"] = position
        ranking[team] = stats

    return ranking


# ============================================================
# TEAM HISTORY
# ============================================================

def team_history(team, previous_matches):

    history = []

    for match in previous_matches:

        if match["home"] == team:

            history.append({
                "round": match["round"],
                "opponent": match["away"],
                "gf": match["home_goals"],
                "ga": match["away_goals"],
                "venue": "HOME"
            })

        elif match["away"] == team:

            history.append({
                "round": match["round"],
                "opponent": match["home"],
                "gf": match["away_goals"],
                "ga": match["home_goals"],
                "venue": "AWAY"
            })

    return sorted(
        history,
        key=lambda item: item["round"]
    )


def recent_form(team, previous_matches, limit=5):

    history = team_history(
        team,
        previous_matches
    )[-limit:]

    points = 0
    gf = 0
    ga = 0

    for match in history:

        gf += match["gf"]
        ga += match["ga"]

        if match["gf"] > match["ga"]:
            points += 3

        elif match["gf"] == match["ga"]:
            points += 1

    count = len(history)

    return {
        "matches": count,
        "points": points,
        "gf": gf,
        "ga": ga,
        "average_gf": gf / count if count else 0,
        "average_ga": ga / count if count else 0
    }


# ============================================================
# GAP ENGINE
# ============================================================

def calculate_gap(team, current_round, previous_matches):

    rounds = [
        match["round"]
        for match in previous_matches
        if team in (match["home"], match["away"])
    ]

    if not rounds:
        return None

    return current_round - max(rounds)


# ============================================================
# PRE-MATCH FEATURES
# ============================================================

def match_features(match, previous_matches):

    ranking = build_ranking(previous_matches)

    home = match["home"]
    away = match["away"]

    hs = ranking.get(home, {})
    aws = ranking.get(away, {})

    hf = recent_form(home, previous_matches)
    af = recent_form(away, previous_matches)

    return {

        "home_position": hs.get("position", 20),
        "away_position": aws.get("position", 20),

        "points_difference": (
            hs.get("points", 0) - aws.get("points", 0)
        ),

        "goal_difference_difference": (
            hs.get("gd", 0) - aws.get("gd", 0)
        ),

        "home_attack": hs.get("goals_per_match", 0),
        "away_attack": aws.get("goals_per_match", 0),

        "home_defence": hs.get("conceded_per_match", 0),
        "away_defence": aws.get("conceded_per_match", 0),

        "home_form_points": hf["points"],
        "away_form_points": af["points"],

        "home_form_gf": hf["average_gf"],
        "away_form_gf": af["average_gf"],

        "home_form_ga": hf["average_ga"],
        "away_form_ga": af["average_ga"],

        "home_gap": calculate_gap(
            home, match["round"], previous_matches
        ),

        "away_gap": calculate_gap(
            away, match["round"], previous_matches
        )
    }


# ============================================================
# HISTORICAL FEATURE RECONSTRUCTION
# ============================================================

def enrich_historical_matches(previous_matches):

    enriched = []

    by_tournament = defaultdict(list)

    for match in previous_matches:
        by_tournament[match["tournament"]].append(match)

    for historical_match in previous_matches:

        same_tournament = by_tournament[
            historical_match["tournament"]
        ]

        before = [
            match for match in same_tournament
            if match["round"] < historical_match["round"]
        ]

        copy = dict(historical_match)

        copy["features"] = match_features(
            historical_match,
            before
        )

        enriched.append(copy)

    return enriched


# ============================================================
# DISTANCE ENGINE
# ============================================================

FEATURE_SCALES = {

    "home_position": 20,
    "away_position": 20,
    "points_difference": 100,
    "goal_difference_difference": 60,
    "home_attack": 5,
    "away_attack": 5,
    "home_defence": 5,
    "away_defence": 5,
    "home_form_points": 15,
    "away_form_points": 15,
    "home_form_gf": 5,
    "away_form_gf": 5,
    "home_form_ga": 5,
    "away_form_ga": 5,
    "home_gap": 10,
    "away_gap": 10
}


def feature_distance(a, b):

    fa = a.get("features", {})
    fb = b.get("features", {})

    distance = 0
    used = 0

    for key, scale in FEATURE_SCALES.items():

        va = fa.get(key)
        vb = fb.get(key)

        if va is None or vb is None:
            continue

        distance += abs(
            safe_float(va) - safe_float(vb)
        ) / scale

        used += 1

    return distance / used if used else 999


def score_distance(a, b):

    return (
        abs(a["home_goals"] - b["home_goals"])
        +
        abs(a["away_goals"] - b["away_goals"])
    )


# ============================================================
# RICOCHET ENGINE
# ============================================================

def ricochet_search(target, previous_matches):

    hg = target["home_goals"]
    ag = target["away_goals"]

    total = hg + ag
    difference = abs(hg - ag)

    exact = []
    inverted = []
    same_total = []
    same_difference = []
    same_result = []

    for match in previous_matches:

        x = match["home_goals"]
        y = match["away_goals"]

        if x == hg and y == ag:
            exact.append(match)

        if x == ag and y == hg and x != y:
            inverted.append(match)

        if x + y == total:
            same_total.append(match)

        if abs(x - y) == difference:
            same_difference.append(match)

        if result_type(x, y) == result_type(hg, ag):
            same_result.append(match)

    return {

        "target": target["score"],

        "exact": exact,
        "inverted": inverted,
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
# COMBINATION ENGINE
# ============================================================

def combination_analysis(target, previous_matches):

    target_signature = score_signature(
        target["home_goals"],
        target["away_goals"]
    )

    related = []

    for match in previous_matches:

        signature = score_signature(
            match["home_goals"],
            match["away_goals"]
        )

        similarities = []

        for key in (
            "total",
            "difference",
            "result",
            "both_scored"
        ):

            if signature[key] == target_signature[key]:
                similarities.append(key)

        if similarities:

            related.append({
                "match": match,
                "similarities": similarities,
                "similarity_count": len(similarities)
            })

    related.sort(
        key=lambda item: item["similarity_count"],
        reverse=True
    )

    return related


# ============================================================
# GRAPH ENGINE
# ============================================================

def build_similarity_graph(target, history):

    candidates = []

    for match in history:

        distance = feature_distance(target, match)
        score_diff = score_distance(target, match)

        weight = distance * 0.75 + score_diff * 0.25

        candidates.append({
            "match": match,
            "feature_distance": distance,
            "score_distance": score_diff,
            "weight": weight
        })

    candidates.sort(
        key=lambda item: item["weight"]
    )

    nodes = candidates[:MAX_GRAPH_NODES]

    graph = defaultdict(list)

    for i in range(len(nodes)):

        for j in range(i + 1, len(nodes)):

            a = nodes[i]["match"]
            b = nodes[j]["match"]

            fd = feature_distance(a, b)
            sd = score_distance(a, b)

            if fd <= 0.35 or sd <= 1:

                graph[i].append(j)
                graph[j].append(i)

    return nodes, graph


# ============================================================
# BFS
# ============================================================

def bfs_search(nodes, graph):

    if not nodes:
        return []

    queue = deque([(0, 0)])
    visited = set()
    results = []

    while queue:

        node, depth = queue.popleft()

        if node in visited:
            continue

        visited.add(node)

        results.append({
            "depth": depth,
            "match": nodes[node]["match"],
            "weight": nodes[node]["weight"]
        })

        if depth >= MAX_BFS_DEPTH:
            continue

        for neighbor in graph[node]:

            if neighbor not in visited:
                queue.append((neighbor, depth + 1))

    return results


# ============================================================
# DFS
# ============================================================

def dfs_search(nodes, graph):

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
            "depth": depth,
            "match": nodes[node]["match"],
            "weight": nodes[node]["weight"]
        })

        if depth >= MAX_DFS_DEPTH:
            continue

        for neighbor in graph[node]:

            if neighbor not in visited:
                stack.append((neighbor, depth + 1))

    return results


# ============================================================
# RNG DETECTOR
# ============================================================

def rng_analysis(matches):

    if not matches:
        return {}

    scores = Counter(
        match["score"] for match in matches
    )

    totals = Counter(
        match["total_goals"] for match in matches
    )

    results = Counter(
        result_type(
            match["home_goals"],
            match["away_goals"]
        )
        for match in matches
    )

    home_goals = [
        match["home_goals"] for match in matches
    ]

    away_goals = [
        match["away_goals"] for match in matches
    ]

    return {

        "sample_size": len(matches),

        "score_frequency": dict(scores),
        "total_frequency": dict(totals),
        "result_frequency": dict(results),

        "repeated_scores": {
            score: count
            for score, count in scores.items()
            if count > 1
        },

        "average_home_goals": statistics.mean(home_goals),
        "average_away_goals": statistics.mean(away_goals),

        "home_goals_variance": statistics.pvariance(home_goals),
        "away_goals_variance": statistics.pvariance(away_goals)
    }


# ============================================================
# MONTE CARLO
# ============================================================

def monte_carlo(target, historical_matches, simulations):

    if not historical_matches:

        return {
            "simulations": 0,
            "historical_sample": 0,
            "top_scores": []
        }

    weights = []
    scores = []

    for match in historical_matches:

        distance = feature_distance(target, match)

        weight = 1.0 / (0.05 + distance)

        weights.append(weight)
        scores.append(match["score"])

    frequency = Counter(
        random.choices(
            scores,
            weights=weights,
            k=simulations
        )
    )

    top = frequency.most_common(15)

    return {

        "simulations": simulations,
        "historical_sample": len(historical_matches),

        "top_scores": [

            {
                "score": score,
                "count": count,

                "frequency_percent": round(
                    count / simulations * 100,
                    4
                )
            }

            for score, count in top
        ],

        "method": "Weighted empirical bootstrap",
        "weighting": "Pre-match feature similarity only"
    }


# ============================================================
# EXACT SCORE ENGINE
# ============================================================

def exact_score_analysis(target, previous_matches):

    frequencies = Counter(
        match["score"] for match in previous_matches
    )

    total = len(previous_matches)
    count = frequencies.get(target["score"], 0)

    return {

        "target_score": target["score"],
        "occurrences": count,
        "sample_size": total,

        "frequency_percent": round(
            count / total * 100,
            3
        ) if total else 0,

        "top_scores": frequencies.most_common(15)
    }


# ============================================================
# REVERSE ANALYSIS
# ============================================================

def reverse_analysis(target, previous_matches):

    features = match_features(
        target,
        previous_matches
    )

    target_enriched = dict(target)
    target_enriched["features"] = features

    enriched_history = enrich_historical_matches(
        previous_matches
    )

    ranking = build_ranking(previous_matches)

    nodes, graph = build_similarity_graph(
        target_enriched,
        enriched_history
    )

    return {

        "match": target,
        "pre_match_features": features,
        "ranking_before": ranking,

        "home_history": team_history(
            target["home"],
            previous_matches
        ),

        "away_history": team_history(
            target["away"],
            previous_matches
        ),

        "ricochet": ricochet_search(
            target,
            previous_matches
        ),

        "combinations": combination_analysis(
            target,
            previous_matches
        ),

        "bfs": bfs_search(nodes, graph),
        "dfs": dfs_search(nodes, graph),

        "exact_score": exact_score_analysis(
            target,
            previous_matches
        ),

        "historical_comparisons": enriched_history
    }


# ============================================================
# BACKTEST
# ============================================================

def backtest(matches):

    records = []
    correct = 0
    tested = 0

    for tournament in sorted(
        set(match["tournament"] for match in matches)
    ):

        games = [
            match for match in matches
            if match["tournament"] == tournament
        ]

        for day in range(2, ROUNDS + 1):

            previous = [
                match for match in games
                if match["round"] < day
            ]

            current = [
                match for match in games
                if match["round"] == day
            ]

            if not previous:
                continue

            frequencies = Counter(
                match["score"] for match in previous
            )

            if not frequencies:
                continue

            predicted = frequencies.most_common(1)[0][0]

            for target in current:

                actual = target["score"]
                exact = predicted == actual

                if exact:
                    correct += 1

                tested += 1

                records.append({

                    "tournament": tournament,
                    "round": day,
                    "home": target["home"],
                    "away": target["away"],
                    "predicted": predicted,
                    "actual": actual,
                    "exact_correct": exact
                })

    return {

        "method": "Walk-forward historical majority baseline",
        "tested": tested,
        "exact_correct": correct,

        "accuracy_percent": round(
            correct / tested * 100,
            3
        ) if tested else 0,

        "records": records
    }


# ============================================================
# CROSS TOURNAMENT
# ============================================================

def cross_tournament_analysis(matches):

    tournaments = sorted(
        set(match["tournament"] for match in matches)
    )

    results = {}

    for test_tournament in tournaments:

        training = [
            match for match in matches
            if match["tournament"] != test_tournament
        ]

        testing = [
            match for match in matches
            if match["tournament"] == test_tournament
        ]

        training_scores = Counter(
            match["score"] for match in training
        )

        most_common = (
            training_scores.most_common(1)[0][0]
            if training_scores else None
        )

        correct = sum(
            1 for match in testing
            if match["score"] == most_common
        )

        results[test_tournament] = {

            "training_tournaments": len(tournaments) - 1,
            "testing_matches": len(testing),
            "training_most_common_score": most_common,
            "matches_equal_to_training_mode": correct,

            "frequency_percent": round(
                correct / len(testing) * 100,
                3
            ) if testing else 0
        }

    return results


# ============================================================
# GLOBAL LEARNING
# ============================================================

def learning_analysis(matches):

    scores = Counter(
        match["score"] for match in matches
    )

    totals = Counter(
        match["total_goals"] for match in matches
    )

    outcomes = Counter(
        result_type(
            match["home_goals"],
            match["away_goals"]
        )
        for match in matches
    )

    return {

        "training_matches": len(matches),
        "score_frequency": dict(scores),
        "total_frequency": dict(totals),
        "outcome_frequency": dict(outcomes),

        "most_common_score": (
            scores.most_common(1)[0][0]
            if scores else None
        )
    }


# ============================================================
# TELEGRAM REPORT
# ============================================================

def build_telegram_report(
    tournaments,
    total_matches,
    performance,
    rng,
    monte_carlo_results,
    simulations
):

    now = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [

        "━━━━━━━━━━━━━━━━━━━━",
        "🧠 TESLA REVERSE INTELLIGENCE",
        "━━━━━━━━━━━━━━━━━━━━",

        f"📅 {now}",
        "",
        f"🏆 Tournois : {tournaments}",
        f"⚽ Matchs analysés : {total_matches}",
        "🔢 Journées : J1 à J37",
        "",
        "🔬 MOTEURS ACTIVÉS",
        "✅ Historical Engine",
        "✅ Ranking Engine",
        "✅ Goal & Form Engine",
        "✅ Ricochet Engine",
        "✅ BFS / DFS",
        "✅ RNG Detector",
        "✅ Monte Carlo",
        "✅ Reverse Score Engine",
        "✅ Backtesting",
        "✅ Cross Tournament",
        "",
        "🎲 MONTE CARLO",
        f"Simulations par match : {simulations}",
        "",
        "📈 BACKTEST",
        f"Matchs testés : {performance['tested']}",
        f"Scores exacts : {performance['exact_correct']}",
        f"Baseline : {performance['accuracy_percent']}%",
        "",
        "🧪 DISTRIBUTION HISTORIQUE",
        f"Scores distincts : {len(rng.get('score_frequency', {}))}",
        f"Moyenne buts domicile : {rng.get('average_home_goals', 0):.3f}",
        f"Moyenne buts extérieur : {rng.get('average_away_goals', 0):.3f}",
        "",
        "📁 JSON : output/",
        "━━━━━━━━━━━━━━━━━━━━",
        "TESLA ANALYSIS FINISHED"
    ]

    if monte_carlo_results:

        lines.extend(["", "🎯 TOP MONTE CARLO"])

        for item in monte_carlo_results[:5]:

            match = item["match"]

            lines.append(
                f"{match['tournament']} J{match['round']} "
                f"{match['home']} vs {match['away']} "
                f"| score observé {match['score']}"
            )

            for prediction in item["monte_carlo"]["top_scores"][:3]:

                lines.append(
                    f"  • {prediction['score']} : "
                    f"{prediction['frequency_percent']}%"
                )

    return "\n".join(lines)


# ============================================================
# MAIN ANALYSIS ENGINE
# ============================================================

def run_analysis(simulations):

    print("=" * 60)
    print("TESLA REVERSE SCORE INTELLIGENCE V3")
    print("=" * 60)

    telegram_send(
        "🚀 TESLA REVERSE INTELLIGENCE\n"
        "Analyse démarrée.\n"
        "Chargement des tournois..."
    )

    matches = load_tournaments()

    if not matches:

        message = (
            "❌ TESLA ERROR\n"
            "Aucun résultat trouvé.\n"
            "Vérifie data/tournaments/."
        )

        print(message)
        telegram_send(message)
        return

    matches = validate_data(matches)

    if not matches:
        telegram_send("❌ Aucun match valide.")
        return

    matches.sort(
        key=lambda match: (
            match["tournament"],
            match["round"]
        )
    )

    tournaments = sorted(
        set(match["tournament"] for match in matches)
    )

    save_json("history.json", matches)

    reverse_results = []
    ricochet_results = []
    monte_carlo_results = []

    ranking_results = {}
    rng_results = {}

    # --------------------------------------------------------
    # WALK-FORWARD ANALYSIS
    # --------------------------------------------------------

    for tournament in tournaments:

        games = [
            match for match in matches
            if match["tournament"] == tournament
        ]

        print("\n[TOURNAMENT]", tournament)

        for day in range(1, ROUNDS + 1):

            # Les matchs de la journée en cours
            # ne sont jamais utilisés comme historique.

            previous = [
                match for match in games
                if match["round"] < day
            ]

            current = [
                match for match in games
                if match["round"] == day
            ]

            if not current:
                continue

            ranking_results[
                f"{tournament}_J{day}"
            ] = build_ranking(previous)

            for target in current:

                analysis = reverse_analysis(
                    target,
                    previous
                )

                reverse_results.append(analysis)

                ricochet_results.append({

                    "tournament": tournament,
                    "round": day,
                    "match": target,
                    "ricochet": analysis["ricochet"]

                })

                # Simulation uniquement sur J35, J36, J37.
                # Les caractéristiques utilisées sont celles
                # calculées à partir des journées précédentes.

                if day >= 35 and previous:

                    target_for_mc = {
                        **target,
                        "features": analysis["pre_match_features"]
                    }

                    mc = monte_carlo(
                        target_for_mc,
                        analysis["historical_comparisons"],
                        simulations
                    )

                    monte_carlo_results.append({

                        "match": target,
                        "monte_carlo": mc

                    })

            print(
                f"[DONE] {tournament} J{day}"
            )

        rng_results[tournament] = rng_analysis(games)

    # --------------------------------------------------------
    # GLOBAL ANALYSIS
    # --------------------------------------------------------

    global_rng = rng_analysis(matches)

    performance = backtest(matches)

    cross_results = cross_tournament_analysis(matches)

    learning = learning_analysis(matches)

    # --------------------------------------------------------
    # SAVE JSON DATABASE
    # --------------------------------------------------------

    save_json("reverse_analysis.json", reverse_results)

    save_json("ranking.json", ranking_results)

    save_json("ricochet.json", ricochet_results)

    save_json("predictions.json", monte_carlo_results)

    save_json("rng_database.json", rng_results)

    save_json("global_rng.json", global_rng)

    save_json("models.json", learning)

    save_json("performance.json", performance)

    save_json("cross_tournament.json", cross_results)

    # --------------------------------------------------------
    # TELEGRAM REPORT
    # --------------------------------------------------------

    report = build_telegram_report(
        len(tournaments),
        len(matches),
        performance,
        global_rng,
        monte_carlo_results,
        simulations
    )

    print(report)

    telegram_send_long(report)

    print("\nTESLA ANALYSIS COMPLETED.")


# ============================================================
# PROGRAM ENTRY POINT
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="TESLA Reverse Score Intelligence V3"
    )

    parser.add_argument(
        "--simulations",
        type=int,
        default=DEFAULT_SIMULATIONS,
        help="Nombre de simulations Monte Carlo"
    )

    args = parser.parse_args()

    if args.simulations < 1:
        parser.error("--simulations doit être supérieur à zéro")

    run_analysis(args.simulations)


if __name__ == "__main__":
    main()