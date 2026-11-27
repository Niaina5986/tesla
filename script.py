#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TESLA V6 — MASSIVE EXACT SCORE DISCOVERY
----------------------------------------
Analyse les relations numériques associées aux scores exacts.
- Discovery rétrospective : recherche des formules qui reconstruisent les buts.
- Blind : utilise exclusivement les matchs antérieurs au match cible.
- BFS borné + DFS borné + transformations numériques + recherche de paires.
- Monte Carlo de formules comme contrôle de hasard (pas comme accès au RNG réel).

Format des fichiers :
data/tournaments/tournoi_001.txt
Journée 1
Arsenal 2-1 Chelsea
...
Journée 37
...
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
from collections import Counter, defaultdict
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data", "tournaments")
OUT_DIR = os.path.join(BASE, "output")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

MAX_ROUNDS = 37
MAX_GOALS = 7
EPS = 1e-8
MAX_ABS = 1_000_000

# Ajustables via GitHub Actions Variables
BFS_STATE_LIMIT = int(os.getenv("TESLA_BFS_STATE_LIMIT", "12000"))
DFS_NODE_LIMIT = int(os.getenv("TESLA_DFS_NODE_LIMIT", "30000"))
MAX_ATOMS = int(os.getenv("TESLA_MAX_ATOMS", "35"))
MAX_DEPTH = int(os.getenv("TESLA_MAX_DEPTH", "4"))
MC_FORMULA_TRIALS = int(os.getenv("TESLA_MC_FORMULA_TRIALS", "100000"))
MAX_FORMULAS_PER_TARGET = int(os.getenv("TESLA_MAX_FORMULAS", "40"))
MAX_DISCOVERY_MATCHES = int(os.getenv("TESLA_MAX_DISCOVERY_MATCHES", "370"))
RANDOM_SEED = int(os.getenv("TESLA_RANDOM_SEED", "42"))
random.seed(RANDOM_SEED)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ROUND_RE = re.compile(r"journ[eé]e\s*(\d+)", re.I)
MATCH_RE = re.compile(r"^(.*?)\s+(\d+)\s*[-:]\s*(\d+)\s+(.*?)$")


def clean_num(x):
    if abs(x) < 1e-10:
        return 0
    if abs(x - round(x)) < 1e-9:
        return int(round(x))
    return round(float(x), 8)


def finite(x):
    try:
        x = float(x)
        return x if math.isfinite(x) and abs(x) <= MAX_ABS else None
    except (TypeError, ValueError, OverflowError):
        return None


def write_json(name, obj):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
    return path


def parse_file(path):
    tournament = os.path.splitext(os.path.basename(path))[0]
    current_round = None
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            rm = ROUND_RE.search(line)
            if rm:
                current_round = int(rm.group(1))
                continue
            mm = MATCH_RE.match(line)
            if not mm or current_round is None:
                continue
            if not 1 <= current_round <= MAX_ROUNDS:
                continue
            home, hg, ag, away = mm.groups()
            hg, ag = int(hg), int(ag)
            rows.append({
                "tournament": tournament, "round": current_round,
                "home": home.strip(), "away": away.strip(),
                "hg": hg, "ag": ag, "score": f"{hg}-{ag}",
                "total": hg + ag, "difference": hg - ag,
                "btts": int(hg > 0 and ag > 0),
                "result": "H" if hg > ag else "A" if hg < ag else "D"
            })
    return tournament, sorted(rows, key=lambda x: (x["round"], x["home"], x["away"]))


def team_table(matches):
    t = defaultdict(lambda: {
        "played": 0, "points": 0, "gf": 0, "ga": 0,
        "home_p": 0, "away_p": 0, "home_gf": 0, "home_ga": 0,
        "away_gf": 0, "away_ga": 0, "form": []
    })
    for m in matches:
        h, a = t[m["home"]], t[m["away"]]
        hg, ag = m["hg"], m["ag"]
        h["played"] += 1; a["played"] += 1
        h["gf"] += hg; h["ga"] += ag
        a["gf"] += ag; a["ga"] += hg
        h["home_p"] += 1; a["away_p"] += 1
        h["home_gf"] += hg; h["home_ga"] += ag
        a["away_gf"] += ag; a["away_ga"] += hg
        if hg > ag:
            h["points"] += 3; h["form"].append("W"); a["form"].append("L")
        elif hg < ag:
            a["points"] += 3; h["form"].append("L"); a["form"].append("W")
        else:
            h["points"] += 1; a["points"] += 1
            h["form"].append("D"); a["form"].append("D")
    ranking = []
    for name, s in t.items():
        ranking.append({
            "team": name, "played": s["played"], "points": s["points"],
            "gf": s["gf"], "ga": s["ga"], "gd": s["gf"] - s["ga"],
            "form": "".join(s["form"][-5:])
        })
    ranking.sort(key=lambda z: (z["points"], z["gd"], z["gf"]), reverse=True)
    return t, ranking


def numeric_inventory(history):
    """Toutes les variables numériques disponibles avant la cible."""
    vals = []
    def put(v, label):
        v = finite(v)
        if v is not None:
            vals.append((v, label))
    for m in history:
        for k in ("round", "hg", "ag", "total", "difference", "btts"):
            put(m[k], k)
    teams, ranking = team_table(history)
    for pos, row in enumerate(ranking, 1):
        put(pos, "rank")
        for k in ("played", "points", "gf", "ga", "gd"):
            put(row[k], "team_" + k)
    if history:
        put(len(history), "match_count")
        put(statistics.mean(x["hg"] for x in history), "mean_home_goals")
        put(statistics.mean(x["ag"] for x in history), "mean_away_goals")
        put(statistics.mean(x["total"] for x in history), "mean_total")
        put(statistics.pvariance(x["total"] for x in history), "total_variance")
        put(100 * statistics.mean(x["btts"] for x in history), "btts_percent")
    # Ajoute les métriques de forme/attaque/défense par équipe.
    for name, s in teams.items():
        put(s["points"], name + "_points")
        put(s["gf"], name + "_gf")
        put(s["ga"], name + "_ga")
        put(s["gf"] / max(s["played"], 1), name + "_gf_per_game")
        put(s["ga"] / max(s["played"], 1), name + "_ga_per_game")
        put(s["home_gf"] / max(s["home_p"], 1), name + "_home_attack")
        put(s["away_gf"] / max(s["away_p"], 1), name + "_away_attack")
    return vals


def atomize(inventory):
    """Réduit les doublons tout en gardant les sources explicatives."""
    by_value = {}
    for value, label in inventory:
        key = round(value, 8)
        if key not in by_value:
            by_value[key] = {"v": float(value), "expr": label, "sources": [label]}
        else:
            by_value[key]["sources"].append(label)
    atoms = list(by_value.values())
    # Ajoute transformations numériques utiles.
    extra = []
    for a in atoms:
        x = a["v"]
        if x >= 0 and x == int(x):
            s = str(int(x))
            if len(s) > 1:
                extra.append({"v": sum(map(int, s)), "expr": f"digit_sum({s})", "sources": ["digit_sum"]})
                extra.append({"v": int(s[::-1]), "expr": f"reverse({s})", "sources": ["reverse_digits"]})
        if x > 0:
            extra.append({"v": math.log(x), "expr": f"ln({a['expr']})", "sources": ["log_transform"]})
            extra.append({"v": math.sqrt(x), "expr": f"sqrt({a['expr']})", "sources": ["sqrt_transform"]})
        if x >= 0 and x <= 9 and x == int(x):
            extra.append({"v": math.factorial(int(x)), "expr": f"{int(x)}!", "sources": ["factorial_transform"]})
    atoms.extend(extra)
    # Déduplication
    uniq = {}
    for a in atoms:
        v = finite(a["v"])
        if v is not None:
            k = round(v, 8)
            if k not in uniq or len(a["expr"]) < len(uniq[k]["expr"]):
                uniq[k] = {"v": v, "expr": a["expr"], "sources": a["sources"]}
    result = list(uniq.values())
    # Garder des sources diverses, plutôt que seulement les petits nombres.
    if len(result) > MAX_ATOMS:
        result.sort(key=lambda z: (len(z["sources"]) == 0, len(z["expr"]), abs(z["v"])))
        result = result[:MAX_ATOMS]
    return result


def unary_ops(x, expr):
    out = []
    def add(v, e):
        v = finite(v)
        if v is not None:
            out.append((v, e))
    if x >= 0:
        add(math.sqrt(x), f"sqrt({expr})")
    add(math.copysign(abs(x) ** (1/3), x), f"cuberoot({expr})")
    add(abs(x), f"abs({expr})")
    add(math.floor(x), f"floor({expr})")
    add(math.ceil(x), f"ceil({expr})")
    add(x / 100, f"percent({expr})")
    if abs(x) > EPS:
        add(1/x, f"1/({expr})")
    if x > 0:
        add(math.log(x), f"ln({expr})")
        add(math.log10(x), f"log10({expr})")
    if abs(x) <= 20:
        add(math.sin(x), f"sin({expr})")
        add(math.cos(x), f"cos({expr})")
    if x >= 0 and x <= 10 and x == int(x):
        add(math.factorial(int(x)), f"({int(x)})!")
    if abs(x) <= 8:
        try: add(math.exp(x), f"exp({expr})")
        except OverflowError: pass
    return out


def binary_ops(a, ea, b, eb):
    out = []
    def add(v, e):
        v = finite(v)
        if v is not None:
            out.append((v, e))
    add(a+b, f"({ea}+{eb})")
    add(a-b, f"({ea}-{eb})")
    add(b-a, f"({eb}-{ea})")
    add(a*b, f"({ea}*{eb})")
    if abs(b) > EPS: add(a/b, f"({ea}/{eb})")
    if abs(a) > EPS: add(b/a, f"({eb}/{ea})")
    # Exposants bornés, avec garde contre 0 puissance négative.
    if b == int(b) and abs(b) <= 6 and not (abs(a) < EPS and b < 0):
        try: add(a ** int(b), f"({ea}^{int(b)})")
        except (OverflowError, ValueError, ZeroDivisionError): pass
    if a == int(a) and abs(a) <= 6 and not (abs(b) < EPS and a < 0):
        try: add(b ** int(a), f"({eb}^{int(a)})")
        except (OverflowError, ValueError, ZeroDivisionError): pass
    if a >= 0 and b > 0:
        try: add(a ** (1/b), f"root({eb},{ea})")
        except (OverflowError, ValueError, ZeroDivisionError): pass
    if b >= 0 and a > 0:
        try: add(b ** (1/a), f"root({ea},{eb})")
        except (OverflowError, ValueError, ZeroDivisionError): pass
    return out


def formula_score(expr, depth, sources):
    # Favorise les formules simples et pénalise les expressions très longues.
    return round(1.0 / (1 + depth * 0.7 + len(expr) * 0.015), 6)


def search_target(inventory, target, seed_tag=""):
    """BFS progressif + DFS borné. Compte les opérations réellement testées."""
    start = time.perf_counter()
    atoms = atomize(inventory)
    if not atoms:
        return {"target": target, "formulas": [], "bfs_operations": 0, "dfs_nodes": 0}

    found = {}
    bfs_ops = 0
    frontier = [{"v": a["v"], "expr": a["expr"], "depth": 0, "sources": a["sources"]} for a in atoms]
    visited = set()

    def record(v, expr, depth, sources):
        if abs(v - target) <= EPS:
            key = expr
            found[key] = {
                "expression": expr, "result": clean_num(v),
                "target": target, "depth": depth,
                "complexity_score": formula_score(expr, depth, sources),
                "sources": sources[:8]
            }

    for st in frontier:
        record(st["v"], st["expr"], 0, st["sources"])

    # BFS: expansion par niveaux.
    for depth in range(1, MAX_DEPTH + 1):
        candidates = []
        # Unaires
        for st in frontier:
            for v, e in unary_ops(st["v"], st["expr"]):
                bfs_ops += 1
                record(v, e, depth, st["sources"])
                key = (round(v, 8), e)
                if key not in visited:
                    visited.add(key)
                    candidates.append({"v": v, "expr": e, "depth": depth, "sources": st["sources"]})
                if bfs_ops >= BFS_STATE_LIMIT:
                    break
            if bfs_ops >= BFS_STATE_LIMIT: break
        # Binaires contre les atomes historiques.
        if bfs_ops < BFS_STATE_LIMIT:
            for st in frontier:
                for atom in atoms:
                    for v, e in binary_ops(st["v"], st["expr"], atom["v"], atom["expr"]):
                        bfs_ops += 1
                        record(v, e, depth, list(dict.fromkeys(st["sources"] + atom["sources"])))
                        key = (round(v, 8), e)
                        if key not in visited:
                            visited.add(key)
                            candidates.append({
                                "v": v, "expr": e, "depth": depth,
                                "sources": list(dict.fromkeys(st["sources"] + atom["sources"]))
                            })
                        if bfs_ops >= BFS_STATE_LIMIT: break
                    if bfs_ops >= BFS_STATE_LIMIT: break
                if bfs_ops >= BFS_STATE_LIMIT: break
        # Beam: garde les états les plus distincts et les moins complexes.
        dedup = {}
        for c in candidates:
            k = round(c["v"], 8)
            if k not in dedup or len(c["expr"]) < len(dedup[k]["expr"]):
                dedup[k] = c
        frontier = sorted(dedup.values(), key=lambda z: (abs(z["v"]-target), len(z["expr"])))[:min(1200, BFS_STATE_LIMIT)]
        if not frontier or bfs_ops >= BFS_STATE_LIMIT:
            break
        if len(found) >= MAX_FORMULAS_PER_TARGET * 4:
            break

    # DFS borné : explore des chaînes d'opérations distinctes, avec budget explicite.
    dfs_nodes = 0
    stack = [(a["v"], a["expr"], 0, a["sources"]) for a in atoms[:min(len(atoms), 18)]]
    while stack and dfs_nodes < DFS_NODE_LIMIT and len(found) < MAX_FORMULAS_PER_TARGET * 6:
        v0, e0, depth, src0 = stack.pop()
        dfs_nodes += 1
        record(v0, e0, depth, src0)
        if depth >= MAX_DEPTH:
            continue
        # Unaires
        for v, e in unary_ops(v0, e0)[:8]:
            dfs_nodes += 1
            record(v, e, depth+1, src0)
            if dfs_nodes >= DFS_NODE_LIMIT: break
            if abs(v-target) < 5:
                stack.append((v, e, depth+1, src0))
        # Binaires avec petit échantillon diversifié d'atomes.
        for atom in atoms[:min(14, len(atoms))]:
            if dfs_nodes >= DFS_NODE_LIMIT: break
            for v, e in binary_ops(v0, e0, atom["v"], atom["expr"])[:8]:
                dfs_nodes += 1
                record(v, e, depth+1, list(dict.fromkeys(src0 + atom["sources"])))
                if dfs_nodes >= DFS_NODE_LIMIT: break
                if abs(v-target) < 5:
                    stack.append((v, e, depth+1, src0 + atom["sources"]))
    formulas = sorted(found.values(), key=lambda z: (-z["complexity_score"], len(z["expression"])))
    return {
        "target": target, "formulas": formulas[:MAX_FORMULAS_PER_TARGET],
        "formula_count": len(found), "bfs_operations": bfs_ops,
        "dfs_nodes": dfs_nodes, "atoms_used": len(atoms),
        "elapsed_seconds": round(time.perf_counter()-start, 3),
        "search_budget": {"bfs_limit": BFS_STATE_LIMIT, "dfs_limit": DFS_NODE_LIMIT, "max_depth": MAX_DEPTH}
    }


def pair_discovery(home_result, away_result):
    """Relations entre les deux buts et formules individuelles découvertes."""
    h = home_result.get("formulas", [])
    a = away_result.get("formulas", [])
    pairs = []
    for x in h[:20]:
        for y in a[:20]:
            pairs.append({
                "home_formula": x["expression"],
                "away_formula": y["expression"],
                "pair": f"{home_result['target']}-{away_result['target']}",
                "combined_complexity": round(x["complexity_score"] + y["complexity_score"], 6)
            })
    pairs.sort(key=lambda z: z["combined_complexity"], reverse=True)
    return pairs[:30]


def monte_carlo_formula_control(inventory, target, trials=MC_FORMULA_TRIALS):
    """Contrôle exploratoire : taux de hits de formules aléatoires à partir des atomes."""
    atoms = atomize(inventory)
    if not atoms:
        return {"trials": 0, "hits": 0, "hit_rate_percent": 0}
    hits = 0
    for _ in range(trials):
        a = random.choice(atoms)["v"]
        b = random.choice(atoms)["v"]
        ops = binary_ops(a, str(clean_num(a)), b, str(clean_num(b)))
        if any(abs(v-target) <= EPS for v, _ in ops):
            hits += 1
    return {
        "trials": trials, "hits": hits,
        "hit_rate_percent": round(100*hits/max(trials, 1), 6),
        "interpretation": "Taux de reconstruction dans cet échantillonnage de formules; pas une probabilité du score."
    }


def poisson_lam(history, home, away):
    if not history:
        return 1.35, 1.10
    teams, _ = team_table(history)
    gh = statistics.mean(m["hg"] for m in history)
    ga = statistics.mean(m["ag"] for m in history)
    hs, aws = teams.get(home), teams.get(away)
    if not hs or not aws:
        return max(0.1, gh), max(0.1, ga)
    lh = (hs["home_gf"]/max(hs["home_p"],1) + aws["away_ga"]/max(aws["away_p"],1))/2
    la = (aws["away_gf"]/max(aws["away_p"],1) + hs["home_ga"]/max(hs["home_p"],1))/2
    return max(0.05, lh), max(0.05, la)


def poisson_p(k, lam):
    try:
        return math.exp(-lam) * lam**k / math.factorial(k)
    except (ValueError, OverflowError, ZeroDivisionError):
        return 0.0


def predict_score(history, target_match):
    lh, la = poisson_lam(history, target_match["home"], target_match["away"])
    rows = []
    for hg in range(MAX_GOALS+1):
        for ag in range(MAX_GOALS+1):
            rows.append((poisson_p(hg, lh)*poisson_p(ag, la), f"{hg}-{ag}"))
    rows.sort(reverse=True)
    return [{"score": s, "model_probability_percent": round(p*100, 5)} for p, s in rows[:10]]


def blind_test(matches):
    """Prédit chaque journée avec les seules journées antérieures."""
    tested, top1, top3, top5 = 0, 0, 0, 0
    rows = []
    for rnd in sorted({m["round"] for m in matches}):
        history = [m for m in matches if m["round"] < rnd]
        if not history:
            continue
        for m in [x for x in matches if x["round"] == rnd]:
            pred = predict_score(history, m)
            scores = [x["score"] for x in pred]
            tested += 1
            h1 = bool(scores and scores[0] == m["score"])
            h3 = m["score"] in scores[:3]
            h5 = m["score"] in scores[:5]
            top1 += int(h1); top3 += int(h3); top5 += int(h5)
            rows.append({
                "round": rnd, "home": m["home"], "away": m["away"],
                "observed": m["score"], "predicted_top5": scores[:5],
                "top1": h1, "top3": h3, "top5": h5
            })
    return {
        "tested": tested, "top1_hits": top1, "top3_hits": top3, "top5_hits": top5,
        "top1_percent": round(100*top1/max(tested,1), 4),
        "top3_percent": round(100*top3/max(tested,1), 4),
        "top5_percent": round(100*top5/max(tested,1), 4),
        "details": rows
    }


def discovery_for_tournament(name, matches):
    started = time.perf_counter()
    all_inventory = numeric_inventory(matches)
    unique_goals = sorted({g for m in matches for g in (m["hg"], m["ag"])})
    cache = {}
    for goal in unique_goals:
        cache[goal] = search_target(all_inventory, goal, name)
    details = []
    selected = matches[:MAX_DISCOVERY_MATCHES]
    for m in selected:
        hr, ar = cache[m["hg"]], cache[m["ag"]]
        details.append({
            "round": m["round"], "home": m["home"], "away": m["away"],
            "observed_score": m["score"],
            "home_goal_discovery": hr,
            "away_goal_discovery": ar,
            "joint_pair_patterns": pair_discovery(hr, ar),
            "mode": "RETROSPECTIVE_DISCOVERY"
        })
    return {
        "unique_goal_targets": unique_goals,
        "target_searches": cache,
        "match_discoveries": details,
        "matches_processed": len(details),
        "elapsed_seconds": round(time.perf_counter()-started, 3)
    }


def blind_math_for_latest(matches):
    latest = max(m["round"] for m in matches)
    history = [m for m in matches if m["round"] < latest]
    inv = numeric_inventory(history)
    results = []
    for goal in range(MAX_GOALS+1):
        r = search_target(inv, goal, "BLIND_LATEST")
        results.append({
            "candidate_goal": goal,
            "formula_count": r.get("formula_count", 0),
            "bfs_operations": r.get("bfs_operations", 0),
            "dfs_nodes": r.get("dfs_nodes", 0),
            "formulas": r.get("formulas", [])[:10]
        })
    return {"target_round": latest, "history_matches": len(history), "goal_searches": results}


def summary_stats(matches):
    scores = Counter(m["score"] for m in matches)
    return {
        "matches": len(matches), "rounds": len({m["round"] for m in matches}),
        "distinct_scores": len(scores), "score_frequency": dict(scores.most_common()),
        "home_average": round(statistics.mean(m["hg"] for m in matches), 5),
        "away_average": round(statistics.mean(m["ag"] for m in matches), 5),
        "btts_percent": round(100*statistics.mean(m["btts"] for m in matches), 4)
    }


def cross_validation(tournaments):
    if len(tournaments) < 2:
        return {"status": "NO_EXTERNAL_TOURNAMENT", "tournaments_found": len(tournaments)}
    return {
        "status": "COMPARISON_AVAILABLE",
        "tournaments": {
            name: summary_stats(rows) for name, rows in tournaments.items()
        }
    }




def pattern_investigation(matches):
    """Analyse fréquences, transitions, cycles et anomalies sans prétendre inférer le RNG."""
    score_counts = Counter(m["score"] for m in matches)
    home_counts = Counter(m["hg"] for m in matches)
    away_counts = Counter(m["ag"] for m in matches)
    round_scores = defaultdict(list)
    for m in matches:
        round_scores[m["round"]].append(m["score"])

    transitions = Counter()
    ordered = sorted(matches, key=lambda x: (x["round"], x["home"], x["away"]))
    for left, right in zip(ordered, ordered[1:]):
        transitions[(left["score"], right["score"])] += 1

    intervals = {}
    for score in score_counts:
        positions = [i for i, m in enumerate(ordered) if m["score"] == score]
        intervals[score] = [positions[i] - positions[i-1] for i in range(1, len(positions))]

    total_mean = statistics.mean(m["total"] for m in matches) if matches else 0
    total_sd = statistics.pstdev(m["total"] for m in matches) if len(matches) > 1 else 0
    anomalies = []
    for m in ordered:
        z = ((m["total"] - total_mean) / total_sd) if total_sd > EPS else 0
        if abs(z) >= 2:
            anomalies.append({
                "round": m["round"], "home": m["home"], "away": m["away"],
                "score": m["score"], "total_goals_zscore": round(z, 4)
            })

    return {
        "score_frequencies": dict(score_counts.most_common()),
        "home_goal_frequencies": dict(sorted(home_counts.items())),
        "away_goal_frequencies": dict(sorted(away_counts.items())),
        "score_transition_top": [
            {"from": a, "to": b, "count": n}
            for (a, b), n in transitions.most_common(30)
        ],
        "repeat_intervals_by_score": intervals,
        "round_score_repetitions": {
            str(r): dict(Counter(v)) for r, v in sorted(round_scores.items())
        },
        "total_goal_anomalies_abs_z_ge_2": anomalies,
        "interpretation": "Descriptif : les cycles et anomalies observés ne prouvent pas une règle causale."
    }


def pair_hunter(matches):
    """Étudie les paires exactes et leurs dépendances descriptives."""
    pair_counts = Counter((m["hg"], m["ag"]) for m in matches)
    home_away = defaultdict(Counter)
    for m in matches:
        home_away[m["hg"]][m["ag"]] += 1
    return {
        "exact_score_pairs": [
            {"score": f"{h}-{a}", "count": n,
             "frequency_percent": round(100*n/max(len(matches), 1), 4)}
            for (h, a), n in pair_counts.most_common()
        ],
        "away_distribution_by_home_goals": {
            str(h): dict(sorted(counter.items()))
            for h, counter in sorted(home_away.items())
        }
    }


def per_match_score_audit(matches):
    """Audit explicatif par match; rétro, donc explicitement non prédictif."""
    output = []
    for m in matches:
        output.append({
            "round": m["round"], "home": m["home"], "away": m["away"],
            "observed_score": m["score"],
            "home_goal": m["hg"], "away_goal": m["ag"],
            "total": m["total"], "difference": m["difference"],
            "same_score_frequency": sum(
                1 for x in matches if x["score"] == m["score"]
            ),
            "same_home_goal_frequency": sum(
                1 for x in matches if x["hg"] == m["hg"]
            ),
            "same_away_goal_frequency": sum(
                1 for x in matches if x["ag"] == m["ag"]
            ),
            "mode": "RETROSPECTIVE_AUDIT"
        })
    return output


def telegram_send(text):
    if not TOKEN or not CHAT_ID:
        print("Telegram non configuré : rapport conservé dans output/.")
        return False
    try:
        import urllib.request, urllib.parse
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.status == 200
    except Exception as e:
        print("Telegram error:", e)
        return False



STATE_PATH = os.path.join(BASE, "tesla_notification_state.json")


def sha256_files(paths):
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(os.path.basename(path).encode("utf-8"))
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def load_notification_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            value = json.load(f)
            return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def discovery_signature(discovery):
    """Hash only stable mathematical findings, excluding elapsed time/counters."""
    compact = {}
    for target, result in sorted(discovery.get("target_searches", {}).items()):
        compact[str(target)] = [
            item.get("expression")
            for item in result.get("formulas", [])
        ]
    raw = json.dumps(compact, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_notification_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def notification_decision(previous, current_data_hash, current_discovery_hash):
    if not previous:
        return True, "INITIAL_ANALYSIS"
    data_changed = previous.get("data_hash") != current_data_hash
    discovery_changed = previous.get("discovery_hash") != current_discovery_hash
    if data_changed and discovery_changed:
        return True, "NEW_DATA_AND_NEW_DISCOVERY"
    if data_changed:
        return True, "NEW_DATA"
    if discovery_changed:
        return True, "NEW_MATHEMATICAL_DISCOVERY"
    return False, "NO_CHANGE"


def report_text(all_reports, total_matches, reason):
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "🧠 TESLA V7 — DEEP SCORE INVESTIGATION",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔔 Motif : {reason}",
        f"🏆 Tournois : {len(all_reports)}",
        f"⚽ Matchs analysés : {total_matches}",
        ""
    ]
    for name, item in sorted(all_reports.items()):
        stats = item["stats"]
        blind = item["blind"]
        lines.extend([
            f"📚 {name}",
            f"Matchs : {stats['matches']} | Journées : {stats['rounds']}",
            f"Scores distincts : {stats['distinct_scores']}",
            f"Moyenne buts domicile/extérieur : {stats['home_average']} / {stats['away_average']}",
            f"BTTS historique (descriptif) : {stats['btts_percent']}%",
            "🔬 Validation chronologique BLIND",
            f"Testés : {blind['tested']} | Top1 : {blind['top1_percent']}% | Top3 : {blind['top3_percent']}% | Top5 : {blind['top5_percent']}%",
            f"Recherches de buts distincts : {item['discovery_targets']}",
            f"BFS opérations : {item['bfs_operations']:,} | DFS nœuds : {item['dfs_nodes']:,}",
            f"Formules mathématiques distinctes : {item['formula_count']}",
            ""
        ])
    lines.extend([
        "🔎 V7 : fréquences, paires, transitions, intervalles, cycles et anomalies.",
        "ℹ️ DISCOVERY reconstruit après observation.",
        "BLIND utilise seulement les journées précédentes.",
        "Une formule ajustée après coup n'est pas une preuve du mécanisme RNG.",
        "━━━━━━━━━━━━━━━━━━━━"
    ])
    return "\n".join(lines)


def main():
    files = sorted(
        os.path.join(DATA_DIR, x) for x in os.listdir(DATA_DIR)
        if x.lower().endswith(".txt")
    )
    if not files:
        print("Ajoute les fichiers tournoi_001.txt dans data/tournaments/")
        return

    data_hash = sha256_files(files)
    tournaments = {}
    for path in files:
        name, rows = parse_file(path)
        if rows:
            tournaments[name] = rows
    if not tournaments:
        print("Aucun match reconnu. Vérifie le format des fichiers.")
        return

    global_start = time.perf_counter()
    global_reports = {}
    discovery_hashes = {}

    for name, matches in tournaments.items():
        print(f"\\n=== TESLA V7 : {name} | {len(matches)} matchs ===")
        stats = summary_stats(matches)

        print("Recherche massive de formules DISCOVERY...")
        discovery = discovery_for_tournament(name, matches)
        print("Validation chronologique BLIND...")
        blind = blind_test(matches)
        print("Recherche mathématique BLIND sur la dernière journée...")
        blind_math = blind_math_for_latest(matches)
        patterns = pattern_investigation(matches)
        pairs = pair_hunter(matches)
        score_audit = per_match_score_audit(matches)

        inv = numeric_inventory(matches)
        mc_control = {
            str(g): monte_carlo_formula_control(inv, g)
            for g in sorted({v for m in matches for v in (m["hg"], m["ag"])})
        }

        last_round = max(m["round"] for m in matches)
        history = [m for m in matches if m["round"] < last_round]
        replay = []
        for m in [x for x in matches if x["round"] == last_round]:
            replay.append({
                "home": m["home"], "away": m["away"],
                "observed": m["score"],
                "prior_history_top10": predict_score(history, m),
                "mode": "HISTORICAL_REPLAY"
            })

        prefix = re.sub(r"[^A-Za-z0-9_-]", "_", name)
        write_json(f"{prefix}_summary.json", stats)
        write_json(f"{prefix}_discovery.json", discovery)
        write_json(f"{prefix}_blind_backtest.json", blind)
        write_json(f"{prefix}_blind_math_latest.json", blind_math)
        write_json(f"{prefix}_monte_carlo_formula_control.json", mc_control)
        write_json(f"{prefix}_latest_replay.json", replay)
        write_json(f"{prefix}_patterns_cycles_anomalies.json", patterns)
        write_json(f"{prefix}_pair_hunter.json", pairs)
        write_json(f"{prefix}_score_audit.json", score_audit)

        total_bfs = sum(x["bfs_operations"] for x in discovery["target_searches"].values())
        total_dfs = sum(x["dfs_nodes"] for x in discovery["target_searches"].values())
        total_formulas = sum(x.get("formula_count", 0) for x in discovery["target_searches"].values())
        discovery_hashes[name] = discovery_signature(discovery)

        global_reports[name] = {
            "stats": stats,
            "blind": {k: v for k, v in blind.items() if k != "details"},
            "discovery_elapsed_seconds": discovery["elapsed_seconds"],
            "discovery_targets": len(discovery["unique_goal_targets"]),
            "bfs_operations": total_bfs,
            "dfs_nodes": total_dfs,
            "formula_count": total_formulas
        }

    cross = cross_validation(tournaments)
    write_json("cross_tournament.json", cross)

    current_discovery_hash = hashlib.sha256(
        json.dumps(discovery_hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()

    previous = load_notification_state()
    now = datetime.now(timezone.utc)
    last_text = previous.get("last_notification_utc")
    due = True
    if last_text:
        try:
            last_dt = datetime.fromisoformat(last_text.replace("Z", "+00:00"))
            due = (now - last_dt).total_seconds() >= int(os.getenv("TESLA_NOTIFICATION_INTERVAL", "3600"))
        except (ValueError, TypeError):
            due = True
    should_notify = due
    reason = "HOURLY_REPORT" if due else "WAITING_FOR_HOURLY_REPORT"

    total_matches = sum(len(x) for x in tournaments.values())
    elapsed = round(time.perf_counter() - global_start, 3)

    final = {
        "version": "TESLA_V7",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
        "notification": {
            "should_notify": should_notify,
            "reason": reason,
            "policy": "Analyze every 15 minutes; send a report every 3600 seconds"
        },
        "configuration": {
            "bfs_state_limit": BFS_STATE_LIMIT,
            "dfs_node_limit": DFS_NODE_LIMIT,
            "max_atoms": MAX_ATOMS,
            "max_depth": MAX_DEPTH,
            "monte_carlo_formula_trials_per_goal": MC_FORMULA_TRIALS
        },
        "tournaments": global_reports,
        "cross_validation": cross
    }
    write_json("global_summary.json", final)

    if should_notify:
        message = report_text(global_reports, total_matches, reason)
        sent = telegram_send(message)
        if sent:
            previous["last_notification_utc"] = datetime.now(timezone.utc).isoformat()
            previous["last_notification_reason"] = reason
            print("Telegram : rapport horaire envoyé.")
        else:
            print("Telegram : échec ou secrets absents. L'envoi sera retenté au prochain lancement.")
    else:
        print("Telegram : prochain rapport horaire pas encore dû.")

    previous.update({
        "data_hash": data_hash,
        "discovery_hash": current_discovery_hash,
        "last_analysis_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_interval_seconds": 900,
        "notification_interval_seconds": int(os.getenv("TESLA_NOTIFICATION_INTERVAL", "3600"))
    })
    save_notification_state(previous)

    print(f"\\nTESLA V7 terminé en {elapsed}s. Résultats dans output/.")
    print("IMPORTANT : pour mémoriser l'anti-doublon entre exécutions GitHub Actions,")
    print("le workflow doit committer tesla_notification_state.json à la racine du dépôt.")


if __name__ == "__main__":
    main()
