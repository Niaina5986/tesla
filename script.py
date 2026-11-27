# ============================================================
# TESLA V4 — REVERSE RNG INVESTIGATION
# Historical analysis | BFS | DFS | Monte Carlo
# Score fingerprints | Sequence detection | RNG diagnostics
# ============================================================

import os
import re
import json
import math
import random
import hashlib
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
    os.getenv("TESLA_SIMULATIONS", "50000")
)

MIN_TRAINING_ROUND = 6
MAX_GOALS = 6

MAX_GRAPH_NODES = 40
MAX_BFS_DEPTH = 5
MAX_DFS_DEPTH = 7

MAX_TELEGRAM_HISTORY = 100
TELEGRAM_ENABLED = True

RANDOM_SEED = 261
random.seed(RANDOM_SEED)

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SCORE_GRID = [
    f"{h}-{a}"
    for h in range(MAX_GOALS + 1)
    for a in range(MAX_GOALS + 1)
]


# ============================================================
# UTILITIES
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def stable_hash(data):
    raw = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True
    ).encode("utf-8")

    return hashlib.sha256(raw).hexdigest()


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


def load_json(filename, default):
    path = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_ENABLED:
        return False

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Secrets non configurés.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
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
            result = json.loads(
                response.read().decode("utf-8")
            )
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
# TELEGRAM NOTIFICATION STATE
# ============================================================

def notification_state():
    return load_json(
        "telegram_state.json",
        {
            "last_hash": "",
            "sent": [],
            "last_notification": None
        }
    )


def register_notification(state, notification_id):
    if notification_id in state["sent"]:
        return False

    state["sent"].append(notification_id)

    state["sent"] = state["sent"][-MAX_TELEGRAM_HISTORY:]

    state["last_notification"] = now_utc()

    return True


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
                "pypdf absent. Ajouter pypdf dans requirements.txt."
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
                f"[IMPORT] {filename}: {len(matches)} matchs"
            )

            all_matches.extend(matches)

        except Exception as error:
            print("[IMPORT ERROR]", filename, error)

    return all_matches


# ============================================================
# DATA VALIDATION
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
        valid.append(match)
        tournaments[match["tournament"]].append(match)

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


def score_family(hg, ag):
    total = hg + ag
    difference = abs(hg - ag)

    if hg == ag:
        return "DRAW"

    if total <= 2:
        return "LOW_TOTAL"

    if difference >= 3:
        return "LARGE_MARGIN"

    if total >= 5:
        return "HIGH_TOTAL"

    return "NORMAL"


def score_signature(hg, ag):
    return {
        "total": hg + ag,
        "difference": abs(hg - ag),
        "result": result_type(hg, ag),
        "family": score_family(hg, ag),
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

    return sorted(history, key=lambda item: item["round"])


def recent_form(team, previous_matches, limit=5):
    history = team_history(team, previous_matches)[-limit:]

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
# FEATURE DISTANCE
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
        + abs(a["away_goals"] - b["away_goals"])
    )


# ============================================================
# HISTORICAL FEATURE RECONSTRUCTION
# ============================================================

def enrich_historical_matches(previous_matches):
    enriched = []

    by_round = defaultdict(list)

    for match in previous_matches:
        by_round[match["round"]].append(match)

    for historical_match in previous_matches:
        before = [
            match
            for match in previous_matches
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
        "counts": {
            "exact": len(exact),
            "inverted": len(inverted),
            "same_total": len(same_total),
            "same_difference": len(same_difference),
            "same_result": len(same_result)
        },
        "exact_examples": exact[:10],
        "inverted_examples": inverted[:10],
        "same_total_examples": same_total[:10]
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
            "both_scored",
            "family"
        ):
            if signature[key] == target_signature[key]:
                similarities.append(key)

        if similarities:
            related.append({
                "tournament": match["tournament"],
                "round": match["round"],
                "home": match["home"],
                "away": match["away"],
                "score": match["score"],
                "similarities": similarities,
                "similarity_count": len(similarities)
            })

    related.sort(
        key=lambda item: item["similarity_count"],
        reverse=True
    )

    return related[:30]


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

    candidates.sort(key=lambda item: item["weight"])

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

        match = nodes[node]["match"]

        results.append({
            "depth": depth,
            "tournament": match["tournament"],
            "round": match["round"],
            "home": match["home"],
            "away": match["away"],
            "score": match["score"],
            "weight": round(nodes[node]["weight"], 5)
        })

        if depth >= MAX_BFS_DEPTH:
            continue

        for neighbor in graph[node]:
            if neighbor not in visited:
                queue.append((neighbor, depth + 1))

    return results


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

        match = nodes[node]["match"]

        results.append({
            "depth": depth,
            "tournament": match["tournament"],
            "round": match["round"],
            "home": match["home"],
            "away": match["away"],
            "score": match["score"],
            "weight": round(nodes[node]["weight"], 5)
        })

        if depth >= MAX_DFS_DEPTH:
            continue

        for neighbor in graph[node]:
            if neighbor not in visited:
                stack.append((neighbor, depth + 1))

    return results


# ============================================================
# SCORE FINGERPRINT ENGINE
# ============================================================

def score_fingerprints(enriched_matches):
    groups = defaultdict(list)

    for match in enriched_matches:
        groups[match["score"]].append(match)

    output = {}

    for score, games in groups.items():
        feature_values = defaultdict(list)

        for match in games:
            for key, value in match.get("features", {}).items():
                if value is not None:
                    feature_values[key].append(
                        safe_float(value)
                    )

        averages = {}

        for key, values in feature_values.items():
            if values:
                averages[key] = round(
                    statistics.mean(values), 4
                )

        output[score] = {
            "occurrences": len(games),
            "percentage": round(
                len(games) / len(enriched_matches) * 100,
                3
            ) if enriched_matches else 0,
            "average_pre_match_features": averages,
            "examples": [
                {
                    "tournament": m["tournament"],
                    "round": m["round"],
                    "home": m["home"],
                    "away": m["away"]
                }
                for m in games[:5]
            ]
        }

    return output


# ============================================================
# SEQUENCE ENGINE
# ============================================================

def sequence_analysis(matches):
    by_tournament = defaultdict(list)

    for match in matches:
        by_tournament[match["tournament"]].append(match)

    output = {}

    for tournament, games in by_tournament.items():
        games.sort(
            key=lambda m: (
                m["round"],
                m["home"],
                m["away"]
            )
        )

        round_families = defaultdict(Counter)
        team_sequences = defaultdict(list)

        score_counts = Counter()
        family_counts = Counter()
        transitions = Counter()

        previous_round_family = {}

        for match in games:
            day = match["round"]
            family = score_family(
                match["home_goals"],
                match["away_goals"]
            )

            round_families[day][family] += 1
            family_counts[family] += 1
            score_counts[match["score"]] += 1

            team_sequences[match["home"]].append({
                "round": day,
                "score": match["score"],
                "side": "HOME"
            })

            team_sequences[match["away"]].append({
                "round": day,
                "score": match["score"],
                "side": "AWAY"
            })

        for day in range(2, ROUNDS + 1):
            before = round_families.get(day - 1, Counter())
            current = round_families.get(day, Counter())

            for a, count_a in before.items():
                for b, count_b in current.items():
                    transitions[(a, b)] += min(
                        count_a, count_b
                    )

        repeated = {
            score: count
            for score, count in score_counts.items()
            if count > 1
        }

        round_output = {
            str(day): dict(counter)
            for day, counter in round_families.items()
        }

        transition_output = {
            f"{a} -> {b}": count
            for (a, b), count in transitions.items()
        }

        team_output = {}

        for team, sequence in team_sequences.items():
            team_output[team] = {
                "matches": len(sequence),
                "sequence": sequence[-37:]
            }

        output[tournament] = {
            "family_frequency": dict(family_counts),
            "repeated_scores": repeated,
            "round_families": round_output,
            "transitions": transition_output,
            "team_sequences": team_output
        }

    return output


# ============================================================
# RNG STATISTICAL DIAGNOSTICS
# ============================================================

def autocorrelation(values, lag=1):
    if len(values) <= lag:
        return None

    mean = statistics.mean(values)

    numerator = sum(
        (values[i] - mean) * (values[i - lag] - mean)
        for i in range(lag, len(values))
    )

    denominator = sum(
        (value - mean) ** 2
        for value in values
    )

    if denominator == 0:
        return 0

    return round(numerator / denominator, 5)


def runs_test(values):
    if len(values) < 3:
        return {
            "runs": None,
            "expected_runs": None,
            "interpretation": "INSUFFICIENT_DATA"
        }

    median = statistics.median(values)

    binary = [
        1 if value >= median else 0
        for value in values
    ]

    n1 = sum(binary)
    n0 = len(binary) - n1

    runs = 1

    for i in range(1, len(binary)):
        if binary[i] != binary[i - 1]:
            runs += 1

    if n0 == 0 or n1 == 0:
        expected = None
    else:
        expected = (
            1 + (2 * n0 * n1) / (n0 + n1)
        )

    return {
        "runs": runs,
        "expected_runs": round(expected, 4)
        if expected is not None else None,
        "interpretation": (
            "DESCRIPTIVE_ONLY"
        )
    }


def rng_analysis(matches):
    if not matches:
        return {}

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

    families = Counter(
        score_family(
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

    total_goals = [
        match["total_goals"] for match in matches
    ]

    btts = sum(
        1 for match in matches
        if match["home_goals"] > 0
        and match["away_goals"] > 0
    )

    return {
        "sample_size": len(matches),
        "score_frequency": dict(scores),
        "total_frequency": dict(totals),
        "outcome_frequency": dict(outcomes),
        "family_frequency": dict(families),

        "repeated_scores": {
            score: count
            for score, count in scores.items()
            if count > 1
        },

        "average_home_goals": round(
            statistics.mean(home_goals), 4
        ),

        "average_away_goals": round(
            statistics.mean(away_goals), 4
        ),

        "average_total_goals": round(
            statistics.mean(total_goals), 4
        ),

        "home_goals_variance": round(
            statistics.pvariance(home_goals), 4
        ),

        "away_goals_variance": round(
            statistics.pvariance(away_goals), 4
        ),

        "btts_percent": round(
            btts / len(matches) * 100, 3
        ),

        "home_goal_autocorrelation": autocorrelation(
            home_goals
        ),

        "away_goal_autocorrelation": autocorrelation(
            away_goals
        ),

        "total_goal_autocorrelation": autocorrelation(
            total_goals
        ),

        "home_goal_runs_test": runs_test(home_goals),
        "away_goal_runs_test": runs_test(away_goals)
    }


# ============================================================
# MONTE CARLO ENGINE
# ============================================================

def parse_score(score):
    try:
        h, a = score.split("-", 1)
        return int(h), int(a)
    except Exception:
        return 0, 0


def monte_carlo(target, historical_matches, simulations):
    if not historical_matches:
        return {
            "simulations": 0,
            "historical_sample": 0,
            "top_scores": [],
            "actual_score_probability": 0
        }

    weighted_scores = []
    weights = []

    for match in historical_matches:
        distance = feature_distance(target, match)

        weight = 1.0 / (0.05 + distance)

        weighted_scores.append(match["score"])
        weights.append(weight)

    sampled = random.choices(
        weighted_scores,
        weights=weights,
        k=simulations
    )

    frequency = Counter(sampled)

    # Distribution lissée sur une grille 0-0 à 6-6.
    # Les simulations individuelles ne sont jamais sauvegardées.
    smoothing = 0.5
    denominator = simulations + smoothing * len(SCORE_GRID)

    probabilities = {}

    for score in SCORE_GRID:
        count = frequency.get(score, 0)

        probabilities[score] = (
            count + smoothing
        ) / denominator

    ranked = sorted(
        probabilities.items(),
        key=lambda item: item[1],
        reverse=True
    )

    top = [
        {
            "score": score,
            "count": frequency.get(score, 0),
            "frequency_percent": round(
                probability * 100, 4
            )
        }
        for score, probability in ranked[:10]
    ]

    actual_probability = probabilities.get(
        target["score"], 0
    )

    actual_rank = next(
        (
            index
            for index, (score, _) in enumerate(ranked, 1)
            if score == target["score"]
        ),
        None
    )

    return {
        "simulations": simulations,
        "historical_sample": len(historical_matches),
        "top_scores": top,
        "actual_score": target["score"],
        "actual_score_probability_percent": round(
            actual_probability * 100, 4
        ),
        "actual_score_rank": actual_rank,
        "method": "Weighted empirical bootstrap with smoothing",
        "note": (
            "Les probabilités décrivent le modèle historique, "
            "pas la mécanique interne du générateur RNG."
        )
    }


# ============================================================
# EXACT SCORE ANALYSIS
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
            count / total * 100, 3
        ) if total else 0,
        "top_scores": frequencies.most_common(10)
    }


# ============================================================
# REVERSE INVESTIGATION
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
# WALK-FORWARD MONTE CARLO BACKTEST
# ============================================================

def monte_carlo_backtest(matches, simulations):
    records = []

    top1 = 0
    top3 = 0
    tested = 0
    actual_ranks = []

    for tournament in sorted(
        set(m["tournament"] for m in matches)
    ):
        games = [
            m for m in matches
            if m["tournament"] == tournament
        ]

        for day in range(MIN_TRAINING_ROUND, ROUNDS + 1):
            previous = [
                m for m in games
                if m["round"] < day
            ]

            current = [
                m for m in games
                if m["round"] == day
            ]

            if len(previous) < 10:
                continue

            history = enrich_historical_matches(previous)

            for target in current:
                features = match_features(
                    target,
                    previous
                )

                target_for_mc = {
                    **target,
                    "features": features
                }

                mc = monte_carlo(
                    target_for_mc,
                    history,
                    simulations
                )

                top_scores = mc["top_scores"]

                ranked_scores = [
                    item["score"]
                    for item in top_scores
                ]

                actual = target["score"]

                rank = (
                    ranked_scores.index(actual) + 1
                    if actual in ranked_scores
                    else None
                )

                hit1 = bool(
                    ranked_scores
                    and ranked_scores[0] == actual
                )

                hit3 = actual in ranked_scores[:3]

                top1 += int(hit1)
                top3 += int(hit3)
                tested += 1

                if rank is not None:
                    actual_ranks.append(rank)

                records.append({
                    "tournament": tournament,
                    "round": day,
                    "home": target["home"],
                    "away": target["away"],
                    "actual": actual,
                    "top3": ranked_scores[:3],
                    "actual_rank_in_top10": rank,
                    "top1_hit": hit1,
                    "top3_hit": hit3,
                    "actual_probability_percent":
                        mc["actual_score_probability_percent"]
                })

    return {
        "method": "Chronological walk-forward Monte Carlo",
        "minimum_training_round": MIN_TRAINING_ROUND,
        "simulations_per_match": simulations,
        "tested_matches": tested,
        "top1_hits": top1,
        "top3_hits": top3,
        "top1_percent": round(
            top1 / tested * 100, 3
        ) if tested else 0,
        "top3_percent": round(
            top3 / tested * 100, 3
        ) if tested else 0,
        "mean_actual_rank_when_top10": round(
            statistics.mean(actual_ranks), 3
        ) if actual_ranks else None,
        "records": records
    }


# ============================================================
# BASELINE BACKTEST
# ============================================================

def backtest(matches):
    records = []

    correct = 0
    tested = 0

    for tournament in sorted(
        set(m["tournament"] for m in matches)
    ):
        games = [
            m for m in matches
            if m["tournament"] == tournament
        ]

        for day in range(2, ROUNDS + 1):
            previous = [
                m for m in games
                if m["round"] < day
            ]

            current = [
                m for m in games
                if m["round"] == day
            ]

            frequencies = Counter(
                m["score"] for m in previous
            )

            if not frequencies:
                continue

            predicted = frequencies.most_common(1)[0][0]

            for target in current:
                actual = target["score"]
                exact = predicted == actual

                correct += int(exact)
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
            correct / tested * 100, 3
        ) if tested else 0,
        "records": records
    }


# ============================================================
# CROSS TOURNAMENT
# ============================================================

def cross_tournament_analysis(matches):
    tournaments = sorted(
        set(m["tournament"] for m in matches)
    )

    results = {}

    for test_tournament in tournaments:
        training = [
            m for m in matches
            if m["tournament"] != test_tournament
        ]

        testing = [
            m for m in matches
            if m["tournament"] == test_tournament
        ]

        training_scores = Counter(
            m["score"] for m in training
        )

        most_common = (
            training_scores.most_common(1)[0][0]
            if training_scores else None
        )

        correct = sum(
            1 for m in testing
            if m["score"] == most_common
        )

        results[test_tournament] = {
            "training_tournaments": len(tournaments) - 1,
            "testing_matches": len(testing),
            "training_most_common_score": most_common,
            "matches_equal_to_training_mode": correct,
            "frequency_percent": round(
                correct / len(testing) * 100, 3
            ) if testing else 0
        }

    return results


# ============================================================
# GLOBAL MODEL
# ============================================================

def learning_analysis(matches):
    scores = Counter(
        m["score"] for m in matches
    )

    totals = Counter(
        m["total_goals"] for m in matches
    )

    outcomes = Counter(
        result_type(
            m["home_goals"],
            m["away_goals"]
        )
        for m in matches
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
# COMPACT OUTPUT
# ============================================================

def compact_reverse_result(analysis):
    match = analysis["match"]

    return {
        "tournament": match["tournament"],
        "round": match["round"],
        "home": match["home"],
        "away": match["away"],
        "observed_score": match["score"],
        "features": analysis["pre_match_features"],
        "ricochet": analysis["ricochet"]["counts"],
        "exact_score": analysis["exact_score"],
        "similar_matches": analysis["combinations"][:10],
        "bfs": analysis["bfs"][:10],
        "dfs": analysis["dfs"][:10]
    }


# ============================================================
# TELEGRAM REPORTS
# ============================================================

def build_match_report(match, mc):
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "🧠 TESLA V4 — MATCH INVESTIGATION",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🏆 {match['tournament']}",
        f"📅 Journée J{match['round']}",
        f"⚽ {match['home']} vs {match['away']}",
        f"🎯 Score observé : {match['score']}",
        "",
        f"🎲 Monte Carlo : {mc['simulations']:,} simulations",
        f"📚 Historique : {mc['historical_sample']} matchs",
        "",
        "TOP SCORES SIMULÉS"
    ]

    for index, item in enumerate(mc["top_scores"][:5], 1):
        lines.append(
            f"{index}. {item['score']} — "
            f"{item['frequency_percent']}%"
        )

    lines.extend([
        "",
        "🔍 SCORE OBSERVÉ",
        f"Probabilité estimée : "
        f"{mc['actual_score_probability_percent']}%",
        f"Rang : {mc['actual_score_rank']}",
        "",
        "📌 Analyse statistique historique.",
        "━━━━━━━━━━━━━━━━━━━━"
    ])

    return "\n".join(lines)


def build_global_report(
    tournaments,
    matches,
    rng,
    baseline,
    mc_backtest,
    simulations,
    sequences
):
    now = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "🧠 TESLA V4 — GLOBAL REPORT",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📅 {now}",
        "",
        f"🏆 Tournois : {len(tournaments)}",
        f"⚽ Matchs : {len(matches)}",
        "🔢 Journées : J1 à J37",
        "",
        "🔬 MOTEURS",
        "✅ Historical Engine",
        "✅ Ranking Engine",
        "✅ Goal & Form Engine",
        "✅ Ricochet Engine",
        "✅ BFS / DFS",
        "✅ Score Fingerprints",
        "✅ Sequence Detector",
        "✅ RNG Diagnostics",
        "✅ Monte Carlo",
        "✅ Walk-forward Backtest",
        "✅ Cross Tournament",
        "",
        "🎲 MONTE CARLO",
        f"Simulations par match : {simulations:,}",
        "",
        "📈 BASELINE",
        f"Matchs testés : {baseline['tested']}",
        f"Scores exacts : {baseline['exact_correct']}",
        f"Précision exacte : {baseline['accuracy_percent']}%",
        "",
        "🧪 MONTE CARLO BACKTEST",
        f"Matchs testés : {mc_backtest['tested_matches']}",
        f"Top 1 : {mc_backtest['top1_percent']}%",
        f"Top 3 : {mc_backtest['top3_percent']}%",
        "",
        "📊 DISTRIBUTION",
        f"Scores distincts : {len(rng.get('score_frequency', {}))}",
        f"Moyenne domicile : {rng.get('average_home_goals', 0)}",
        f"Moyenne extérieur : {rng.get('average_away_goals', 0)}",
        f"BTTS : {rng.get('btts_percent', 0)}%",
        "",
        f"🔁 Tournois séquencés : {len(sequences)}",
        "",
        "📁 Résultats détaillés : output/",
        "━━━━━━━━━━━━━━━━━━━━",
        "TESLA V4 ANALYSIS FINISHED"
    ]

    return "\n".join(lines)


# ============================================================
# MAIN ENGINE
# ============================================================

def run_analysis(simulations):
    print("=" * 60)
    print("TESLA V4 — REVERSE RNG INVESTIGATION")
    print("=" * 60)

    telegram_send(
        "🚀 TESLA V4\n"
        "Nouvelle analyse démarrée.\n"
        "Chargement des données..."
    )

    matches = load_tournaments()

    if not matches:
        message = (
            "❌ TESLA ERROR\n"
            "Aucun résultat trouvé.\n"
            "Vérifier data/tournaments/."
        )

        print(message)
        telegram_send(message)
        return

    matches = validate_data(matches)

    if not matches:
        telegram_send("❌ Aucun match valide.")
        return

    matches.sort(
        key=lambda m: (
            m["tournament"],
            m["round"],
            m["home"],
            m["away"]
        )
    )

    tournaments = sorted(
        set(m["tournament"] for m in matches)
    )

    data_hash = stable_hash(matches)

    state = notification_state()

    data_changed = data_hash != state.get("last_hash", "")

    if not data_changed:
        print("[INFO] Données inchangées.")

    # --------------------------------------------------------
    # GLOBAL HISTORICAL ANALYSIS
    # --------------------------------------------------------

    global_rng = rng_analysis(matches)

    baseline = backtest(matches)

    sequences = sequence_analysis(matches)

    cross_results = cross_tournament_analysis(matches)

    learning = learning_analysis(matches)

    enriched_all = enrich_historical_matches(matches)

    fingerprints = score_fingerprints(enriched_all)

    # --------------------------------------------------------
    # TRANSITION MATRIX
    # --------------------------------------------------------

    transition_matrix = {}

    for tournament, data in sequences.items():
        transition_matrix[tournament] = data["transitions"]

    # --------------------------------------------------------
    # WALK-FORWARD MATCH ANALYSIS
    # --------------------------------------------------------

    reverse_results = []
    monte_carlo_records = []
    ranking_results = {}

    latest_round = {}

    for tournament in tournaments:
        games = [
            m for m in matches
            if m["tournament"] == tournament
        ]

        for day in range(1, ROUNDS + 1):
            previous = [
                m for m in games
                if m["round"] < day
            ]

            current = [
                m for m in games
                if m["round"] == day
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

                reverse_results.append(
                    compact_reverse_result(analysis)
                )

                # Monte Carlo sur les matchs ayant
                # suffisamment d'historique.
                if day >= MIN_TRAINING_ROUND and len(previous) >= 10:
                    features = analysis["pre_match_features"]

                    target_for_mc = {
                        **target,
                        "features": features
                    }

                    history = enrich_historical_matches(
                        previous
                    )

                    mc = monte_carlo(
                        target_for_mc,
                        history,
                        simulations
                    )

                    record = {
                        "match": target,
                        "monte_carlo": mc
                    }

                    monte_carlo_records.append(record)

                    if tournament not in latest_round:
                        latest_round[tournament] = day
                    else:
                        latest_round[tournament] = max(
                            latest_round[tournament],
                            day
                        )

        print("[DONE]", tournament)

    # --------------------------------------------------------
    # MONTE CARLO WALK-FORWARD VALIDATION
    # --------------------------------------------------------

    print("[BACKTEST] Monte Carlo walk-forward...")

    mc_backtest = monte_carlo_backtest(
        matches,
        simulations
    )

    # --------------------------------------------------------
    # SAVE COMPACT JSON
    # --------------------------------------------------------

    save_json("summary.json", {
        "version": "TESLA V4",
        "generated_at": now_utc(),
        "data_hash": data_hash,
        "tournaments": len(tournaments),
        "matches": len(matches),
        "rounds": ROUNDS,
        "simulations": simulations,
        "data_changed": data_changed
    })

    save_json("predictions.json", monte_carlo_records)

    save_json("fingerprints.json", fingerprints)

    save_json("sequences.json", sequences)

    save_json("transition_matrix.json", transition_matrix)

    save_json("rng_analysis.json", global_rng)

    save_json("backtest.json", baseline)

    save_json("monte_carlo_backtest.json", mc_backtest)

    save_json("ranking.json", ranking_results)

    save_json("cross_tournament.json", cross_results)

    save_json("models.json", learning)

    # Les données brutes ne sont pas dupliquées dans output/.
    # Les fichiers sources restent dans data/tournaments/.

    # --------------------------------------------------------
    # TELEGRAM NOTIFICATIONS
    # --------------------------------------------------------

    if data_changed:
        print("[TELEGRAM] Nouvelles données détectées.")

        # On envoie les matchs de la dernière journée
        # de chaque tournoi, pas tous les anciens matchs.
        for tournament in tournaments:
            latest = latest_round.get(tournament)

            if latest is None:
                continue

            latest_matches = [
                item
                for item in monte_carlo_records
                if item["match"]["tournament"] == tournament
                and item["match"]["round"] == latest
            ]

            for item in latest_matches:
                match = item["match"]

                notification_id = stable_hash({
                    "tournament": tournament,
                    "round": latest,
                    "home": match["home"],
                    "away": match["away"],
                    "data_hash": data_hash
                })

                if register_notification(
                    state,
                    notification_id
                ):
                    report = build_match_report(
                        match,
                        item["monte_carlo"]
                    )

                    telegram_send_long(report)

        global_report = build_global_report(
            tournaments,
            matches,
            global_rng,
            baseline,
            mc_backtest,
            simulations,
            sequences
        )

        telegram_send_long(global_report)

        state["last_hash"] = data_hash

    else:
        print(
            "[TELEGRAM] Pas de nouvelle donnée : "
            "pas de rapport répété."
        )

    save_json("telegram_state.json", state)

    print("=" * 60)
    print("TESLA V4 ANALYSIS COMPLETED")
    print("Tournois :", len(tournaments))
    print("Matchs :", len(matches))
    print("Simulations :", simulations)
    print("Données modifiées :", data_changed)
    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="TESLA V4 Reverse RNG Investigation"
    )

    parser.add_argument(
        "--simulations",
        type=int,
        default=DEFAULT_SIMULATIONS,
        help="Nombre de simulations Monte Carlo par match"
    )

    args = parser.parse_args()

    if args.simulations < 1000:
        parser.error(
            "--simulations doit être au minimum 1000"
        )

    run_analysis(args.simulations)


if __name__ == "__main__":
    main()