import os
import json
import time
import itertools
import statistics
import urllib.request
import urllib.parse
from datetime import datetime, timezone

import websocket


# =====================================================
# BOOM1000 SPIKE INTELLIGENCE V2
# DERIV API + STATISTICAL RESEARCH + TELEGRAM
# =====================================================

SYMBOL = "BOOM1000"

APP_ID = os.getenv("DERIV_APP_ID", "1089")

WS_URL = (
    f"wss://ws.derivws.com/websockets/v3"
    f"?app_id={APP_ID}"
)

DB_FILE = "dataset.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID")

CANDLE_COUNT = 1000
TICK_COUNT = 2000

TIMEFRAMES = {
    "M1": 60,
    "M3": 180
}

SPIKE_ATR_MULTIPLIER = 2.0
PREDICTION_HORIZON = 3

MAX_STRATEGIES = 600


# =====================================================
# DATABASE
# =====================================================

def load_db():

    if os.path.exists(DB_FILE):

        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)

        except Exception:
            pass

    return {
        "project": "BOOM1000 SPIKE INTELLIGENCE",
        "created": datetime.now(timezone.utc).isoformat(),
        "ticks": [],
        "candles": {},
        "analyses": [],
        "best_strategies": {},
        "signals": [],
        "statistics": {
            "runs": 0,
            "strategies_tested": 0
        }
    }


def save_db(db):

    temp = DB_FILE + ".tmp"

    with open(temp, "w") as f:
        json.dump(db, f, indent=2)

    os.replace(temp, DB_FILE)


# =====================================================
# TELEGRAM
# =====================================================

def telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print("Telegram non configure")
        return

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT,
        "text": message,
        "parse_mode": "HTML"
    }).encode()

    try:

        req = urllib.request.Request(url, data=data)

        urllib.request.urlopen(req, timeout=20)

        print("Telegram: message envoye")

    except Exception as e:

        print("Telegram error:", e)


# =====================================================
# DERIV API
# =====================================================

def deriv_request(ws, request, req_id):

    request["req_id"] = req_id

    ws.send(json.dumps(request))

    while True:

        response = json.loads(ws.recv())

        if response.get("req_id") == req_id:

            if "error" in response:
                raise Exception(
                    response["error"].get("message", "Deriv error")
                )

            return response


def connect_deriv():

    ws = websocket.create_connection(
        WS_URL,
        timeout=30
    )

    print("Connexion Deriv OK")

    return ws


def get_active_symbols(ws):

    response = deriv_request(
        ws,
        {"active_symbols": "brief"},
        1
    )

    symbols = response.get("active_symbols", [])

    for item in symbols:

        symbol = item.get("symbol", "")

        name = item.get("display_name", "").upper()

        if "BOOM 1000" in name or symbol == SYMBOL:

            print("Symbole trouve:", symbol)

            return symbol

    raise Exception(
        "BOOM1000 introuvable dans active_symbols"
    )


def get_candles(ws, symbol, granularity):

    response = deriv_request(
        ws,
        {
            "ticks_history": symbol,
            "end": "latest",
            "count": CANDLE_COUNT,
            "style": "candles",
            "granularity": granularity
        },
        10 + granularity
    )

    candles = response.get("candles", [])

    result = []

    for c in candles:

        result.append({
            "time": int(c["epoch"]),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"])
        })

    return sorted(result, key=lambda x: x["time"])


def get_ticks(ws, symbol):

    response = deriv_request(
        ws,
        {
            "ticks_history": symbol,
            "end": "latest",
            "count": TICK_COUNT,
            "style": "ticks"
        },
        20
    )

    history = response.get("history", {})

    prices = history.get("prices", [])
    times = history.get("times", [])

    return [
        {
            "time": int(t),
            "price": float(p)
        }
        for t, p in zip(times, prices)
    ]


# =====================================================
# INDICATORS
# =====================================================

def sma(values, period):

    result = [None] * len(values)

    for i in range(period - 1, len(values)):

        result[i] = statistics.mean(
            values[i-period+1:i+1]
        )

    return result


def ema(values, period):

    result = [None] * len(values)

    if len(values) < period:
        return result

    multiplier = 2 / (period + 1)

    current = statistics.mean(values[:period])

    result[period-1] = current

    for i in range(period, len(values)):

        current = (
            values[i] * multiplier
            + current * (1 - multiplier)
        )

        result[i] = current

    return result


def rsi(values, period=14):

    result = [None] * len(values)

    if len(values) <= period:
        return result

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i-1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = statistics.mean(gains[:period])
    avg_loss = statistics.mean(losses[:period])

    def calculate(g, l):

        if l == 0:
            return 100

        rs = g / l

        return 100 - (100 / (1 + rs))

    result[period] = calculate(
        avg_gain,
        avg_loss
    )

    for i in range(period + 1, len(values)):

        avg_gain = (
            avg_gain * (period - 1)
            + gains[i-1]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i-1]
        ) / period

        result[i] = calculate(
            avg_gain,
            avg_loss
        )

    return result


def stochastic(candles, k_period=14, d_period=3):

    k_values = [None] * len(candles)

    for i in range(k_period - 1, len(candles)):

        window = candles[i-k_period+1:i+1]

        highest = max(c["high"] for c in window)
        lowest = min(c["low"] for c in window)

        if highest == lowest:
            k_values[i] = 50

        else:
            k_values[i] = (
                (candles[i]["close"] - lowest)
                / (highest - lowest)
            ) * 100

    valid = [
        x if x is not None else 0
        for x in k_values
    ]

    d_values = sma(valid, d_period)

    return k_values, d_values


def atr(candles, period=14):

    tr = [0]

    for i in range(1, len(candles)):

        c = candles[i]
        previous = candles[i-1]["close"]

        tr.append(max(
            c["high"] - c["low"],
            abs(c["high"] - previous),
            abs(c["low"] - previous)
        ))

    return sma(tr, period)


def bollinger(values, period=20, deviation=2):

    middle = sma(values, period)

    upper = [None] * len(values)
    lower = [None] * len(values)

    for i in range(period - 1, len(values)):

        window = values[i-period+1:i+1]

        std = statistics.pstdev(window)

        upper[i] = middle[i] + deviation * std
        lower[i] = middle[i] - deviation * std

    return upper, middle, lower


# =====================================================
# SPIKE DETECTION
# =====================================================

def detect_spike(candles, index, atr_values):

    if index + PREDICTION_HORIZON >= len(candles):
        return None

    current_atr = atr_values[index]

    if current_atr is None or current_atr <= 0:
        return None

    current_price = candles[index]["close"]

    future = candles[
        index+1:
        index+1+PREDICTION_HORIZON
    ]

    highest = max(c["high"] for c in future)

    rise = highest - current_price

    return rise >= (
        current_atr * SPIKE_ATR_MULTIPLIER
    )


# =====================================================
# STRATEGY ENGINE
# =====================================================

def strategy_signal(
    candles,
    index,
    rsi_values,
    k_values,
    d_values,
    fast_ema,
    slow_ema,
    rsi_limit,
    stoch_limit
):

    if index < 1:
        return False

    required = [
        rsi_values[index],
        rsi_values[index-1],
        k_values[index],
        k_values[index-1],
        d_values[index],
        d_values[index-1],
        fast_ema[index],
        slow_ema[index]
    ]

    if any(x is None for x in required):
        return False

    rsi_cross = (
        rsi_values[index-1] < rsi_limit
        and rsi_values[index] >= rsi_limit
    )

    stoch_cross = (
        k_values[index-1] <= d_values[index-1]
        and k_values[index] > d_values[index]
        and k_values[index] < stoch_limit
    )

    trend = fast_ema[index] > slow_ema[index]

    return (
        rsi_cross
        and stoch_cross
        and trend
    )


# =====================================================
# COMBINATION GENERATOR
# =====================================================

def generate_strategies():

    strategies = []

    combinations = itertools.product(

        [5, 7, 9, 14, 21],

        [20, 25, 30, 35],

        [5, 9, 14],

        [3, 5],

        [(5, 20), (9, 30), (20, 50)],

        [15, 20, 25]

    )

    for values in combinations:

        rsi_period, rsi_limit, k_period, d_period, ema_pair, stoch_limit = values

        strategies.append({

            "rsi": rsi_period,
            "rsi_limit": rsi_limit,
            "stoch_k": k_period,
            "stoch_d": d_period,
            "ema_fast": ema_pair[0],
            "ema_slow": ema_pair[1],
            "stoch_limit": stoch_limit

        })

    return strategies[:MAX_STRATEGIES]


# =====================================================
# BACKTESTING
# =====================================================

def evaluate_strategy(candles, strategy):

    closes = [c["close"] for c in candles]

    rsi_values = rsi(
        closes,
        strategy["rsi"]
    )

    k_values, d_values = stochastic(
        candles,
        strategy["stoch_k"],
        strategy["stoch_d"]
    )

    fast = ema(
        closes,
        strategy["ema_fast"]
    )

    slow = ema(
        closes,
        strategy["ema_slow"]
    )

    atr_values = atr(candles, 14)

    split = int(len(candles) * 0.70)

    results = {
        "train": {},
        "test": {}
    }

    for section, start, end in [
        ("train", 1, split),
        ("test", split, len(candles)-PREDICTION_HORIZON)
    ]:

        tp = 0
        fp = 0
        fn = 0
        signals = 0

        for i in range(start, end):

            signal = strategy_signal(
                candles,
                i,
                rsi_values,
                k_values,
                d_values,
                fast,
                slow,
                strategy["rsi_limit"],
                strategy["stoch_limit"]
            )

            actual = detect_spike(
                candles,
                i,
                atr_values
            )

            if actual is None:
                continue

            if signal:
                signals += 1

                if actual:
                    tp += 1
                else:
                    fp += 1

            elif actual:
                fn += 1

        precision = tp / max(1, tp + fp)

        recall = tp / max(1, tp + fn)

        f1 = (
            2 * precision * recall
            / max(0.000001, precision + recall)
        )

        results[section] = {

            "signals": signals,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4)

        }

    return results


# =====================================================
# RESEARCH
# =====================================================

def research(candles):

    strategies = generate_strategies()

    results = []

    print(
        "Combinaisons a tester:",
        len(strategies)
    )

    for strategy in strategies:

        try:

            evaluation = evaluate_strategy(
                candles,
                strategy
            )

            test = evaluation["test"]

            if test["signals"] < 5:
                continue

            results.append({

                "strategy": strategy,
                "evaluation": evaluation,
                "score": test["f1"]

            })

        except Exception as e:

            print("Strategy error:", e)

    results.sort(
        key=lambda x: (
            x["score"],
            x["evaluation"]["test"]["precision"]
        ),
        reverse=True
    )

    return results[:10]


# =====================================================
# CURRENT SIGNAL
# =====================================================

def get_current_signal(candles, strategy):

    closes = [c["close"] for c in candles]

    r = rsi(closes, strategy["rsi"])

    k, d = stochastic(
        candles,
        strategy["stoch_k"],
        strategy["stoch_d"]
    )

    fast = ema(
        closes,
        strategy["ema_fast"]
    )

    slow = ema(
        closes,
        strategy["ema_slow"]
    )

    i = len(candles) - 1

    if strategy_signal(
        candles,
        i,
        r,
        k,
        d,
        fast,
        slow,
        strategy["rsi_limit"],
        strategy["stoch_limit"]
    ):

        return "BUY"

    return "WAIT"


# =====================================================
# REPORT
# =====================================================

def build_report(db, research_results):

    now = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    message = [
        "⚡ <b>BOOM1000 SPIKE INTELLIGENCE</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"📅 {now}",
        "📡 Source: Deriv API",
        ""
    ]

    for timeframe, results in research_results.items():

        message.append(
            f"📊 <b>TIMEFRAME {timeframe}</b>"
        )

        if not results:

            message.append(
                "Pas assez de données pour classer les stratégies."
            )

            continue

        best = results[0]

        strategy = best["strategy"]
        test = best["evaluation"]["test"]

        message.extend([

            f"🏆 Score F1: {test['f1']:.2%}",

            f"🎯 Precision: {test['precision']:.2%}",

            f"📈 Recall: {test['recall']:.2%}",

            f"🔍 Signaux testés: {test['signals']}",

            f"❌ Faux signaux: {test['false_positive']}",

            "",
            "<b>MEILLEURE COMBINAISON</b>",

            f"RSI: {strategy['rsi']}",

            f"RSI seuil: {strategy['rsi_limit']}",

            f"Stochastic: {strategy['stoch_k']}/{strategy['stoch_d']}",

            f"EMA: {strategy['ema_fast']}/{strategy['ema_slow']}",

            f"Stoch seuil: {strategy['stoch_limit']}",

            ""

        ])

    message.extend([

        "━━━━━━━━━━━━━━━━━━",
        "🧠 <b>RECHERCHE STATISTIQUE</b>",
        f"Total combinaisons: {db['statistics']['strategies_tested']}",
        f"Nombre analyses: {db['statistics']['runs']}",
        "",
        "⚠️ Résultats historiques, non garantis.",
        "Aucun ordre automatique."

    ])

    return "\n".join(message)


# =====================================================
# MAIN
# =====================================================

def main():

    print("================================")
    print(" BOOM1000 SPIKE INTELLIGENCE ")
    print("================================")

    db = load_db()

    ws = None

    try:

        ws = connect_deriv()

        symbol = get_active_symbols(ws)

        ticks = get_ticks(ws, symbol)

        db["ticks"].extend(ticks)

        db["ticks"] = sorted(
            {
                (x["time"], x["price"]): x
                for x in db["ticks"]
            }.values(),
            key=lambda x: x["time"]
        )[-10000:]

        research_results = {}

        for timeframe, granularity in TIMEFRAMES.items():

            print("Collecte", timeframe)

            candles = get_candles(
                ws,
                symbol,
                granularity
            )

            if len(candles) < 150:

                print("Historique insuffisant:", timeframe)

                continue

            db["candles"][timeframe] = candles[-2000:]

            results = research(candles)

            research_results[timeframe] = results

            if results:

                best = results[0]

                db["best_strategies"][timeframe] = best

                signal = get_current_signal(
                    candles,
                    best["strategy"]
                )

                db["signals"].append({

                    "time": datetime.now(
                        timezone.utc
                    ).isoformat(),

                    "timeframe": timeframe,

                    "signal": signal,

                    "strategy": best["strategy"],

                    "historical_score": best["score"]

                })

                print(
                    timeframe,
                    "SIGNAL:",
                    signal
                )

        db["statistics"]["runs"] += 1

        db["statistics"]["strategies_tested"] += (
            len(generate_strategies())
            * len(TIMEFRAMES)
        )

        db["analyses"].append({

            "time": datetime.now(
                timezone.utc
            ).isoformat(),

            "symbol": symbol,

            "strategies": research_results

        })

        db["analyses"] = db["analyses"][-100:]

        db["signals"] = db["signals"][-500:]

        save_db(db)

        report = build_report(
            db,
            research_results
        )

        telegram(report)

        print("Analyse terminee avec succes")

    except Exception as e:

        error = (
            "🚨 <b>BOOM1000 ERROR</b>\n"
            f"<code>{str(e)[:1000]}</code>"
        )

        print(error)

        telegram(error)

        raise

    finally:

        if ws:

            ws.close()


if __name__ == "__main__":
    main()