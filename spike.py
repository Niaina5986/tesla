import os
import json
import time
import random
import itertools
import statistics
import urllib.request
import urllib.parse

from datetime import datetime, timezone

import websocket


# =====================================================
# BOOM1000 SPIKE INTELLIGENCE V3
# =====================================================

PROJECT = "BOOM1000 SPIKE INTELLIGENCE V3"

APP_ID = os.getenv("DERIV_APP_ID", "1089")

DB_FILE = "dataset.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL_NAME = "BOOM 1000"

CANDLE_COUNT = 1000
TICK_COUNT = 2000

MAX_STRATEGIES = 600

HORIZON = 3

SPIKE_MULTIPLIER = 2.0

TIMEFRAMES = {
    "M1": 60,
    "M3": 180
}

WS_ENDPOINTS = [
    f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}",
    f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
]


# =====================================================
# DATABASE
# =====================================================

def load_db():

    if os.path.exists(DB_FILE):

        try:

            with open(DB_FILE, "r") as f:
                db = json.load(f)

            return db

        except Exception as e:

            print("Database recovery:", e)

    return {
        "project": PROJECT,
        "created": datetime.now(timezone.utc).isoformat(),
        "ticks": [],
        "candles": {},
        "signals": [],
        "analyses": [],
        "best_strategies": {},
        "statistics": {
            "runs": 0,
            "strategies_tested": 0
        }
    }


def save_db(db):

    temp = DB_FILE + ".tmp"

    with open(temp, "w") as f:

        json.dump(
            db,
            f,
            indent=2,
            allow_nan=False
        )

    os.replace(temp, DB_FILE)


# =====================================================
# TELEGRAM
# =====================================================

def telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:

        print("Telegram non configure")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({

        "chat_id": TELEGRAM_CHAT,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"

    }).encode()

    try:

        req = urllib.request.Request(
            url,
            data=data
        )

        with urllib.request.urlopen(
            req,
            timeout=25
        ) as response:

            result = json.loads(
                response.read().decode()
            )

            return result.get("ok", False)

    except Exception as e:

        print("Telegram error:", e)
        return False


# =====================================================
# DERIV CONNECTION
# =====================================================

def connect_deriv():

    last_error = None

    for attempt in range(1, 8):

        for endpoint in WS_ENDPOINTS:

            try:

                print(
                    f"DERIV CONNECTION "
                    f"{attempt}/7"
                )

                print("Endpoint:", endpoint.split("?")[0])

                ws = websocket.create_connection(

                    endpoint,

                    timeout=25,

                    enable_multithread=True,

                    suppress_origin=True,

                    http_proxy_host=None

                )

                ws.settimeout(40)

                print("DERIV CONNECTED")

                return ws

            except Exception as e:

                last_error = e

                print("Connection error:", str(e))

        if attempt < 7:

            delay = min(
                5 * (2 ** (attempt - 1)),
                90
            )

            delay += random.uniform(1, 5)

            print(
                f"Retry in {delay:.1f} seconds"
            )

            time.sleep(delay)

    raise Exception(
        f"DERIV CONNECTION FAILED: {last_error}"
    )


# =====================================================
# DERIV REQUEST
# =====================================================

def deriv_request(ws, request, req_id):

    request["req_id"] = req_id

    ws.send(json.dumps(request))

    deadline = time.time() + 45

    while time.time() < deadline:

        response = json.loads(ws.recv())

        if response.get("req_id") != req_id:
            continue

        if "error" in response:

            raise Exception(
                response["error"].get(
                    "message",
                    "Deriv API error"
                )
            )

        return response

    raise TimeoutError(
        f"Deriv request timeout: {req_id}"
    )


# =====================================================
# FIND BOOM1000 SYMBOL
# =====================================================

def get_active_symbols(ws):

    response = deriv_request(

        ws,

        {
            "active_symbols": "brief"
        },

        101

    )

    symbols = response.get(
        "active_symbols",
        []
    )

    for item in symbols:

        name = item.get(
            "display_name",
            ""
        ).upper()

        symbol = item.get(
            "symbol",
            ""
        ).upper()

        if (
            "BOOM 1000" in name
            or "BOOM1000" in symbol
        ):

            print(
                "BOOM1000 SYMBOL:",
                item["symbol"]
            )

            return item["symbol"]

    raise Exception(
        "BOOM1000 not found in Deriv active symbols"
    )


# =====================================================
# CANDLES
# =====================================================

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

        200 + granularity

    )

    candles = []

    for c in response.get("candles", []):

        candles.append({

            "time": int(c["epoch"]),

            "open": float(c["open"]),

            "high": float(c["high"]),

            "low": float(c["low"]),

            "close": float(c["close"])

        })

    candles.sort(
        key=lambda x: x["time"]
    )

    # Exclude the most recent candle because it may
    # still be forming. Never use an incomplete candle.

    if len(candles) > 1:
        candles = candles[:-1]

    return candles


# =====================================================
# TICKS
# =====================================================

def get_ticks(ws, symbol):

    response = deriv_request(

        ws,

        {
            "ticks_history": symbol,
            "end": "latest",
            "count": TICK_COUNT,
            "style": "ticks"
        },

        301

    )

    history = response.get(
        "history",
        {}
    )

    prices = history.get(
        "prices",
        []
    )

    times = history.get(
        "times",
        []
    )

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

    current = statistics.mean(
        values[:period]
    )

    result[period-1] = current

    multiplier = 2 / (period + 1)

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

    changes = [

        values[i] - values[i-1]

        for i in range(1, len(values))

    ]

    gains = [
        max(x, 0)
        for x in changes
    ]

    losses = [
        max(-x, 0)
        for x in changes
    ]

    avg_gain = statistics.mean(
        gains[:period]
    )

    avg_loss = statistics.mean(
        losses[:period]
    )

    def calculate(g, l):

        if l == 0:
            return 100

        return 100 - (
            100 / (1 + g / l)
        )

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

    k = [None] * len(candles)

    for i in range(k_period - 1, len(candles)):

        window = candles[
            i-k_period+1:i+1
        ]

        highest = max(
            x["high"]
            for x in window
        )

        lowest = min(
            x["low"]
            for x in window
        )

        if highest == lowest:

            k[i] = 50

        else:

            k[i] = (

                (
                    candles[i]["close"]
                    - lowest
                )

                /

                (highest - lowest)

            ) * 100

    d = [None] * len(candles)

    for i in range(len(candles)):

        if i < k_period + d_period - 2:
            continue

        window = k[
            i-d_period+1:i+1
        ]

        if all(x is not None for x in window):

            d[i] = statistics.mean(window)

    return k, d


def atr(candles, period=14):

    tr = [0]

    for i in range(1, len(candles)):

        current = candles[i]

        previous_close = candles[i-1]["close"]

        tr.append(max(

            current["high"] - current["low"],

            abs(
                current["high"] - previous_close
            ),

            abs(
                current["low"] - previous_close
            )

        ))

    return sma(tr, period)


def bollinger(values, period=20, deviation=2):

    middle = sma(values, period)

    upper = [None] * len(values)

    lower = [None] * len(values)

    for i in range(period - 1, len(values)):

        window = values[
            i-period+1:i+1
        ]

        std = statistics.pstdev(window)

        upper[i] = (
            middle[i] + deviation * std
        )

        lower[i] = (
            middle[i] - deviation * std
        )

    return upper, middle, lower


# =====================================================
# SPIKE DETECTION
# =====================================================

def detect_spike(candles, index, atr_values):

    if index + HORIZON >= len(candles):
        return None

    current_atr = atr_values[index]

    if current_atr is None or current_atr <= 0:
        return None

    current_price = candles[index]["close"]

    future = candles[
        index+1:index+1+HORIZON
    ]

    highest = max(
        x["high"]
        for x in future
    )

    rise = highest - current_price

    return rise >= (
        current_atr * SPIKE_MULTIPLIER
    )


# =====================================================
# STRATEGY SIGNAL
# =====================================================

def strategy_signal(
    i,
    r,
    k,
    d,
    fast,
    slow,
    rsi_limit,
    stoch_limit
):

    if i < 1:
        return False

    required = [

        r[i],
        r[i-1],

        k[i],
        k[i-1],

        d[i],
        d[i-1],

        fast[i],
        slow[i]

    ]

    if any(
        x is None
        for x in required
    ):
        return False

    rsi_cross = (

        r[i-1] < rsi_limit
        and r[i] >= rsi_limit

    )

    stochastic_cross = (

        k[i-1] <= d[i-1]

        and k[i] > d[i]

        and k[i] < stoch_limit

    )

    trend = (
        fast[i] > slow[i]
    )

    return (
        rsi_cross
        and stochastic_cross
        and trend
    )


# =====================================================
# STRATEGY GENERATION
# =====================================================

def generate_strategies():

    combinations = list(
        itertools.product(

            [5, 7, 9, 14, 21],

            [20, 25, 30, 35],

            [5, 9, 14],

            [3, 5],

            [(5, 20), (9, 30), (20, 50)],

            [15, 20, 25]

        )
    )

    # Reproducible and diversified sample
    random.Random(42).shuffle(combinations)

    strategies = []

    for x in combinations[:MAX_STRATEGIES]:

        strategies.append({

            "rsi": x[0],

            "rsi_limit": x[1],

            "stoch_k": x[2],

            "stoch_d": x[3],

            "ema_fast": x[4][0],

            "ema_slow": x[4][1],

            "stoch_limit": x[5]

        })

    return strategies


# =====================================================
# EVALUATION
# =====================================================

def calculate_metrics(
    candles,
    start,
    end,
    r,
    k,
    d,
    fast,
    slow,
    atr_values,
    strategy
):

    tp = 0
    fp = 0
    fn = 0

    for i in range(start, end):

        signal = strategy_signal(

            i,
            r,
            k,
            d,
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

        if signal and actual:
            tp += 1

        elif signal and not actual:
            fp += 1

        elif not signal and actual:
            fn += 1

    precision = tp / max(1, tp + fp)

    recall = tp / max(1, tp + fn)

    f1 = (

        2 * precision * recall

    ) / max(
        0.000001,
        precision + recall
    )

    return {

        "true_positive": tp,

        "false_positive": fp,

        "false_negative": fn,

        "signals": tp + fp,

        "precision": round(precision, 4),

        "recall": round(recall, 4),

        "f1": round(f1, 4)

    }


def evaluate_strategy(candles, strategy):

    closes = [
        c["close"]
        for c in candles
    ]

    r = rsi(
        closes,
        strategy["rsi"]
    )

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

    atr_values = atr(candles, 14)

    # Chronological split:
    # 60% training
    # 20% validation
    # 20% final test

    n = len(candles)

    train_end = int(n * 0.60)

    validation_end = int(n * 0.80)

    validation = calculate_metrics(

        candles,

        train_end,

        validation_end - HORIZON,

        r, k, d, fast, slow, atr_values,

        strategy

    )

    test = calculate_metrics(

        candles,

        validation_end,

        n - HORIZON,

        r, k, d, fast, slow, atr_values,

        strategy

    )

    return {

        "validation": validation,

        "test": test

    }


# =====================================================
# RESEARCH ENGINE
# =====================================================

def research(candles):

    strategies = generate_strategies()

    results = []

    print(
        "Testing strategies:",
        len(strategies)
    )

    for number, strategy in enumerate(
        strategies,
        1
    ):

        try:

            evaluation = evaluate_strategy(

                candles,

                strategy

            )

            validation = evaluation["validation"]

            # Avoid selecting strategies with too few
            # validation observations.

            if validation["signals"] < 5:
                continue

            results.append({

                "strategy": strategy,

                "evaluation": evaluation,

                "score": validation["f1"]

            })

        except Exception as e:

            print(
                "Strategy error:",
                str(e)
            )

        if number % 100 == 0:

            print(
                "Progress:",
                number,
                "/",
                len(strategies)
            )

    # Selection is based on validation,
    # never on final test performance.

    results.sort(

        key=lambda x: (

            x["score"],

            x["evaluation"]["validation"]["precision"]

        ),

        reverse=True

    )

    return results[:10]


# =====================================================
# CURRENT SIGNAL
# =====================================================

def current_signal(candles, strategy):

    closes = [
        c["close"]
        for c in candles
    ]

    r = rsi(
        closes,
        strategy["rsi"]
    )

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

    signal = strategy_signal(

        i,

        r,

        k,

        d,

        fast,

        slow,

        strategy["rsi_limit"],

        strategy["stoch_limit"]

    )

    return {

        "signal": "BUY" if signal else "WAIT",

        "price": closes[-1],

        "rsi": r[-1],

        "stochastic_k": k[-1],

        "stochastic_d": d[-1],

        "time": candles[-1]["time"]

    }


# =====================================================
# REPORT
# =====================================================

def build_report(db, reports):

    now = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [

        "⚡ <b>BOOM1000 SPIKE INTELLIGENCE V3</b>",

        "━━━━━━━━━━━━━━━━━━",

        f"📅 {now}",

        "📡 Source: Deriv API",

        ""

    ]

    for timeframe, results in reports.items():

        lines.append(
            f"📊 <b>{timeframe}</b>"
        )

        if not results:

            lines.append(
                "Pas assez de données."
            )

            continue

        best = results[0]

        strategy = best["strategy"]

        validation = best["evaluation"]["validation"]

        test = best["evaluation"]["test"]

        lines.extend([

            "🏆 <b>MEILLEURE STRATEGIE</b>",

            f"RSI: {strategy['rsi']}",

            f"RSI seuil: {strategy['rsi_limit']}",

            f"Stochastic: {strategy['stoch_k']}/{strategy['stoch_d']}",

            f"EMA: {strategy['ema_fast']}/{strategy['ema_slow']}",

            "",

            "<b>VALIDATION</b>",

            f"F1: {validation['f1']:.2%}",

            f"Precision: {validation['precision']:.2%}",

            f"Signaux: {validation['signals']}",

            "",

            "<b>TEST INDEPENDANT</b>",

            f"F1: {test['f1']:.2%}",

            f"Precision: {test['precision']:.2%}",

            f"Recall: {test['recall']:.2%}",

            f"Faux signaux: {test['false_positive']}",

            ""

        ])

    lines.extend([

        "━━━━━━━━━━━━━━━━━━",

        "🧠 <b>STATISTIQUES</b>",

        f"Analyses: {db['statistics']['runs']}",

        f"Combinaisons testees: {db['statistics']['strategies_tested']}",

        "",

        "⚠️ Les performances historiques ne garantissent pas les futures.",

        "Aucun ordre automatique."

    ])

    return "\n".join(lines)


# =====================================================
# MAIN
# =====================================================

def main():

    print("=" * 50)

    print(PROJECT)

    print("=" * 50)

    db = load_db()

    ws = None

    try:

        # CONNECTION

        ws = connect_deriv()

        symbol = get_active_symbols(ws)

        # TICKS

        ticks = get_ticks(
            ws,
            symbol
        )

        db["ticks"].extend(ticks)

        unique = {}

        for tick in db["ticks"]:

            key = (
                tick["time"],
                tick["price"]
            )

            unique[key] = tick

        db["ticks"] = sorted(

            unique.values(),

            key=lambda x: x["time"]

        )[-10000:]

        print(
            "Ticks collected:",
            len(ticks)
        )

        reports = {}

        # M1 / M3 RESEARCH

        for timeframe, granularity in TIMEFRAMES.items():

            print(
                "Collecting:",
                timeframe
            )

            candles = get_candles(

                ws,

                symbol,

                granularity

            )

            if len(candles) < 200:

                print(
                    "Insufficient candles:",
                    timeframe
                )

                continue

            db["candles"][timeframe] = candles[-1000:]

            results = research(candles)

            reports[timeframe] = results

            if not results:
                continue

            best = results[0]

            signal = current_signal(

                candles,

                best["strategy"]

            )

            # Store compact result

            db["best_strategies"][timeframe] = {

                "strategy": best["strategy"],

                "validation": best["evaluation"]["validation"],

                "test": best["evaluation"]["test"],

                "selection_score": best["score"]

            }

            db["signals"].append({

                "time": datetime.now(
                    timezone.utc
                ).isoformat(),

                "timeframe": timeframe,

                **signal,

                "strategy": best["strategy"],

                "validation_score": best["score"]

            })

            print(
                timeframe,
                signal["signal"]
            )

        # DATABASE UPDATE

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

            "results": {

                timeframe: [

                    {

                        "strategy": x["strategy"],

                        "score": x["score"],

                        "validation": x["evaluation"]["validation"],

                        "test": x["evaluation"]["test"]

                    }

                    for x in results

                ]

                for timeframe, results in reports.items()

            }

        })

        db["analyses"] = db["analyses"][-100:]

        db["signals"] = db["signals"][-500:]

        save_db(db)

        print(
            "Database saved"
        )

        # TELEGRAM

        message = build_report(
            db,
            reports
        )

        if not telegram(message):

            raise Exception(
                "Telegram report delivery failed"
            )

        print(
            "Analysis completed successfully"
        )

    except Exception as e:

        print(
            "FATAL ERROR:",
            str(e)
        )

        telegram(

            "🚨 <b>BOOM1000 ERROR</b>\n\n"

            f"<code>{str(e)[:2500]}</code>"

        )

        raise

    finally:

        if ws:

            try:
                ws.close()

            except Exception:
                pass


if __name__ == "__main__":

    main()